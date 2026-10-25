from datetime import UTC, datetime

from sqlalchemy import select

from app.agents.collections.graph import draft_from_context
from app.core.config import settings
from app.core.errors import AppError
from app.integrations.gmail.client import gmail_client
from app.models.entities import (
    Agency,
    AIAction,
    AuditLog,
    Brand,
    Campaign,
    CollectionTask,
    EmailMessage,
    EmailThread,
    Invoice,
    Membership,
)
from app.models.operations import PaymentPromise
from app.repositories.tenant import TenantRepository
from app.services.audit import audit
from app.services.balances import balance
from app.services.collections import invoice_snapshot
from app.services.finance import collection_eligible, today_for


def lock_context(db, agency_id, task_id):
    repo = TenantRepository(db, agency_id)
    task = repo.get(CollectionTask, task_id)
    agency = db.scalar(select(Agency).where(Agency.id == agency_id).with_for_update())
    invoice = repo.get(Invoice, task.invoice_id, lock=True)
    task = repo.get(CollectionTask, task_id, lock=True)
    return repo, task, invoice, agency


def store_context(db, repo, invoice, messages):
    for message in messages:
        thread = db.scalar(
            repo.query(EmailThread).where(EmailThread.gmail_thread_id == message["thread_id"])
        )
        if thread and thread.invoice_id != invoice.id:
            raise AppError(
                "AMBIGUOUS_THREAD",
                "This thread references another invoice; review it manually",
                409,
            )
        if not thread:
            thread = EmailThread(
                agency_id=repo.agency_id,
                invoice_id=invoice.id,
                brand_id=invoice.brand_id,
                gmail_thread_id=message["thread_id"],
                subject=message["subject"],
                last_message_at=message["sent_at"],
            )
            db.add(thread)
            db.flush()
        if not db.scalar(
            repo.query(EmailMessage).where(EmailMessage.gmail_message_id == message["message_id"])
        ):
            db.add(
                EmailMessage(
                    agency_id=repo.agency_id,
                    thread_id=thread.id,
                    gmail_message_id=message["message_id"],
                    direction=message["direction"],
                    sender_email=message["sender"],
                    recipient_emails=message["recipients"],
                    subject=message["subject"],
                    body_text=message["body"],
                    sent_at=message["sent_at"],
                )
            )
    db.flush()


def generate_draft(db, agency_id, task_id):
    repo, task, invoice, agency = lock_context(db, agency_id, task_id)
    if task.status != "DRAFTING":
        db.rollback()
        return
    snapshot = invoice_snapshot(invoice)
    campaign = repo.get(Campaign, invoice.campaign_id)
    financial_balance = balance(db, invoice)
    history = db.scalars(
        repo.query(AuditLog)
        .where(AuditLog.entity_id.in_([invoice.id, task.id]))
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    ).all()
    brand = repo.get(Brand, invoice.brand_id)
    brand_email, brand_name, agency_name = brand.contact_email, brand.name, agency.name
    action = AIAction(
        agency_id=agency_id,
        entity_id=task.id,
        status="RUNNING",
        model="TEST" if settings().test_mode else settings().ai_model,
        input_reference=str(invoice.id),
    )
    db.add(action)
    db.commit()
    try:
        messages = gmail_client(db, agency_id).context(invoice, brand)
        inbound = [message["body"] for message in messages if message["direction"] == "INBOUND"]
        context = {
            "invoice": snapshot,
            "brand": brand_name,
            "agency": agency_name,
            "campaign": {"name": campaign.name, "description": campaign.description[:1000]},
            "payment_terms_days": brand.payment_terms_days,
            "balance": financial_balance,
            "collection_stage": task.workflow_key,
            "payment_promises": [
                {
                    "date": str(p.promised_date) if p.promised_date else None,
                    "status": p.status,
                    "source_message_id": str(p.source_message_id),
                }
                for p in db.scalars(
                    repo.query(PaymentPromise).where(PaymentPromise.invoice_id == invoice.id)
                ).all()
            ],
            "history": [
                {"action": event.action, "at": event.created_at.isoformat()} for event in history
            ],
            "emails": [
                {"direction": m["direction"], "body": m["body"][:1000]} for m in messages[-6:]
            ],
            "latest_inbound": inbound[-1][:2000] if inbound else "",
        }
        result = draft_from_context(context)
        repo, task, invoice, agency = lock_context(db, agency_id, task_id)
        if (
            task.status != "DRAFTING"
            or snapshot != invoice_snapshot(invoice)
            or not collection_eligible(invoice, task, today_for(agency), db)
        ):
            raise AppError("STALE_CONTEXT", "Invoice changed during drafting", 409)
        brand = repo.get(Brand, invoice.brand_id)
        if brand.contact_email != brand_email:
            raise AppError("STALE_CONTEXT", "Brand contact changed during drafting", 409)
        store_context(db, repo, invoice, messages)
        audit(
            db,
            agency_id,
            "COLLECTION_CONTEXT_LOADED",
            task,
            details={
                "message_ids": [m["message_id"] for m in messages],
                "campaign_id": str(campaign.id),
            },
        )
        task.draft_subject = f"Payment follow-up — {invoice.invoice_number}"
        task.draft_body = f"{result['greeting']}\n\nFollowing up on invoice {invoice.invoice_number} for {invoice.currency} {invoice.amount:.2f}, due on {invoice.due_date.isoformat()}.\n\n{result['request']}\n\n{result['closing']}"
        if invoice.reconciliation_managed:
            task.draft_body += f"\n\nOutstanding balance: {invoice.currency} {financial_balance['outstanding_balance']}."
        task.recipient = brand_email
        task.context_summary = {
            **result["understanding"],
            "message_count": len(messages),
            "balance": financial_balance,
            "invoice": snapshot,
            "source": "Gmail" if not settings().test_mode else "Test Gmail",
        }
        task.draft_revision += 1
        task.status, task.error_code = "DRAFTED", None
        action.status, action.completed_at, action.output_summary = (
            "COMPLETED",
            datetime.now(UTC),
            {"intent": result["understanding"]["intent"], "message_count": len(messages)},
        )
        audit(
            db,
            agency_id,
            "COLLECTION_DRAFT_CREATED",
            task,
            actor_type="AI",
            details={
                "revision": task.draft_revision,
                "ai_action_id": str(action.id),
                "subject": task.draft_subject,
                "body": task.draft_body,
                "recipient": task.recipient,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        action = repo.get(AIAction, action.id, lock=True)
        action.status, action.completed_at = "FAILED", datetime.now(UTC)
        db.commit()
        raise


def message_identifier(task):
    return f"creatorops-{task.id}-r{task.draft_revision}@creatorops.invalid"


def record_sent(db, task, message_id, thread_id=None):
    task.gmail_thread_id = thread_id or task.gmail_thread_id
    task.status, task.gmail_message_id, task.sent_at, task.error_code = (
        "SENT",
        message_id,
        datetime.now(UTC),
        None,
    )
    audit(
        db,
        task.agency_id,
        "EMAIL_SENT",
        task,
        details={
            "gmail_message_id": message_id,
            "recipient": task.recipient,
            "revision": task.draft_revision,
        },
    )
    # Persist the exact approved outbound content for invoice collection history.
    repo = TenantRepository(db, task.agency_id)
    invoice = repo.get(Invoice, task.invoice_id)
    store_context(
        db,
        repo,
        invoice,
        [
            {
                "thread_id": task.gmail_thread_id or f"sent-{task.id}",
                "message_id": message_id,
                "subject": task.approved_snapshot["subject"],
                "body": task.approved_snapshot["body"],
                "sender": task.approved_snapshot["sender"],
                "recipients": [task.recipient],
                "sent_at": task.sent_at,
                "direction": "OUTBOUND",
            }
        ],
    )
    db.commit()


def send_approved(db, agency_id, task_id):
    repo, task, invoice, agency = lock_context(db, agency_id, task_id)
    if task.status != "APPROVED":
        db.rollback()
        return
    snapshot = task.approved_snapshot
    approver = db.scalar(repo.query(Membership).where(Membership.user_id == task.approved_by))
    if not approver or approver.role not in {"OWNER", "ADMIN", "FINANCE"}:
        task.status, task.error_code = "FAILED", "APPROVAL_REVOKED"
        audit(db, agency_id, "EMAIL_SEND_BLOCKED", task, details={"code": "APPROVAL_REVOKED"})
        db.commit()
        return
    brand = repo.get(Brand, invoice.brand_id)
    if (
        not snapshot
        or snapshot["invoice"] != invoice_snapshot(invoice)
        or (snapshot.get("balance") is not None and snapshot["balance"] != balance(db, invoice))
        or snapshot["recipient"] != brand.contact_email
        or not collection_eligible(invoice, task, today_for(agency), db)
    ):
        task.status, task.error_code = "FAILED", "STALE_APPROVAL"
        audit(db, agency_id, "EMAIL_SEND_BLOCKED", task, details={"code": "STALE_APPROVAL"})
        db.commit()
        return
    client = gmail_client(db, agency_id)
    sender = getattr(
        getattr(client, "integration", None), "external_account_id", "test@example.com"
    )
    if sender != snapshot["sender"]:
        raise AppError("SENDER_CHANGED", "Reconnect changed the sending account", 409)
    # Durable barrier BEFORE calling Gmail. A crash now must never auto-send again.
    task.status, task.send_started_at = "SENDING", datetime.now(UTC)
    audit(db, agency_id, "EMAIL_SEND_INITIATED", task, details={"revision": task.draft_revision})
    db.commit()
    try:
        message_id = client.send(
            snapshot["recipient"], snapshot["subject"], snapshot["body"], message_identifier(task)
        )
        task = repo.get(CollectionTask, task_id, lock=True)
        if isinstance(message_id, dict):
            record_sent(db, task, message_id["id"], message_id.get("threadId"))
        else:
            record_sent(db, task, message_id)
    except Exception:
        db.rollback()
        task = repo.get(CollectionTask, task_id, lock=True)
        task.status, task.error_code = "SEND_UNCERTAIN", "GMAIL_SEND_UNCONFIRMED"
        audit(db, agency_id, "EMAIL_SEND_UNCERTAIN", task)
        db.commit()
        raise


def reconcile_send(db, agency_id, task_id):
    repo, task, _, _ = lock_context(db, agency_id, task_id)
    if task.status != "SEND_UNCERTAIN":
        db.rollback()
        return
    client = gmail_client(db, agency_id)
    message_id = client.find_sent(message_identifier(task))
    task = repo.get(CollectionTask, task_id, lock=True)
    if message_id:
        if isinstance(message_id, dict):
            record_sent(db, task, message_id["id"], message_id.get("threadId"))
        else:
            record_sent(db, task, message_id)
    else:
        # Gmail search is eventually consistent: absence is not proof of failure.
        audit(db, agency_id, "EMAIL_SEND_STILL_UNCERTAIN", task)
        db.commit()
