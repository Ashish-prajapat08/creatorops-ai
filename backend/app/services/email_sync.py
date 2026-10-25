import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.errors import AppError
from app.core.security import require
from app.integrations.gmail.client import gmail_client, utc
from app.models.entities import Agency, Brand, EmailMessage, Integration, Invoice, Job
from app.models.operations import EmailSync
from app.repositories.tenant import TenantRepository
from app.services.audit import audit
from app.services.collection_execution import store_context
from app.services.email_intelligence import queue_messages


def enqueue_sync(db, agency_id, invoice_id):
    repo = TenantRepository(db, agency_id)
    repo.get(Invoice, invoice_id)
    sync = db.scalar(repo.query(EmailSync).where(EmailSync.invoice_id == invoice_id))
    if not sync:
        sync = EmailSync(agency_id=agency_id, invoice_id=invoice_id)
        db.add(sync)
        db.flush()
    if sync.status in {"QUEUED", "RUNNING"}:
        return sync
    sync.status, sync.error_code = "QUEUED", None
    db.add(Job(agency_id=agency_id, kind="SYNC_EMAIL", entity_id=invoice_id))
    return sync


def request_sync(db, ctx, invoice_id, full=False):
    require(ctx, "email_review")
    db.scalar(select(Agency).where(Agency.id == ctx.agency_id).with_for_update())
    if full:
        previous = db.scalar(
            TenantRepository(db, ctx.agency_id)
            .query(EmailSync)
            .where(EmailSync.invoice_id == invoice_id)
        )
        if previous and previous.status in {"QUEUED", "RUNNING"}:
            raise AppError(
                "SYNC_IN_FLIGHT", "Wait for the current synchronization before rescanning", 409
            )
        if previous:
            previous.checkpoint_at = None
    sync = enqueue_sync(db, ctx.agency_id, invoice_id)
    audit(db, ctx.agency_id, "EMAIL_SYNC_REQUESTED", sync, ctx.user_id, "USER")
    db.commit()
    return sync


def poll_agency(db, agency):
    repo = TenantRepository(db, agency.id)
    connected = db.scalar(
        repo.query(Integration).where(
            Integration.provider == "GMAIL", Integration.status == "CONNECTED"
        )
    )
    if not connected:
        return
    db.scalar(select(Agency).where(Agency.id == agency.id).with_for_update())
    for invoice in db.scalars(
        repo.query(Invoice).where(Invoice.status.notin_(["DRAFT", "VOID"]))
    ).all():
        enqueue_sync(db, agency.id, invoice.id)
    db.commit()


def sync_invoice(db, agency_id, invoice_id):
    repo = TenantRepository(db, agency_id)
    db.scalar(select(Agency).where(Agency.id == agency_id).with_for_update())
    invoice = repo.get(Invoice, invoice_id)
    sync = db.scalar(
        repo.query(EmailSync).where(EmailSync.invoice_id == invoice_id).with_for_update()
    )
    if not sync or sync.status not in {"QUEUED", "RUNNING"}:
        db.rollback()
        return
    brand = repo.get(Brand, invoice.brand_id)
    checkpoint, brand_email, started = sync.checkpoint_at, brand.contact_email, datetime.now(UTC)
    sync.status = "RUNNING"
    db.commit()
    client = gmail_client(db, agency_id)
    messages = client.context(
        invoice, brand, after=utc(checkpoint) - timedelta(days=1) if checkpoint else None
    )
    account = getattr(
        getattr(client, "integration", None), "external_account_id", "finance@example.com"
    )
    db.scalar(select(Agency).where(Agency.id == agency_id).with_for_update())
    invoice = repo.get(Invoice, invoice_id)
    if repo.get(Brand, invoice.brand_id).contact_email != brand_email:
        raise AppError("STALE_EMAIL_CONTEXT", "Brand contact changed during synchronization", 409)
    sync = db.scalar(
        repo.query(EmailSync).where(EmailSync.invoice_id == invoice_id).with_for_update()
    )
    invoice_numbers = list(
        db.scalars(repo.query(Invoice).with_only_columns(Invoice.invoice_number))
    )
    for message in messages:
        if (
            message["direction"] != "INBOUND"
            or message["sender"].casefold() != brand_email.casefold()
            or message["sender"].casefold() == account.casefold()
        ):
            continue
        source = message["subject"] + "\n" + message["body"]
        references = [
            number
            for number in invoice_numbers
            if re.search(r"(?<![\w-])" + re.escape(number) + r"(?![\w-])", source, re.I)
        ]
        if references != [invoice.invoice_number]:
            audit(
                db,
                agency_id,
                "EMAIL_ASSOCIATION_SKIPPED",
                sync,
                details={
                    "gmail_message_id": message["message_id"],
                    "reason": "AMBIGUOUS_OR_MISSING_INVOICE",
                },
            )
            continue
        existing = db.scalar(
            repo.query(EmailMessage).where(EmailMessage.gmail_message_id == message["message_id"])
        )
        if not existing:
            store_context(db, repo, invoice, [message])
    queued = queue_messages(db, agency_id, invoice_id)
    # Advance only after every page and all inserts complete. Overlap catches delayed indexing.
    sync.checkpoint_at, sync.last_success_at, sync.status, sync.error_code = (
        started,
        datetime.now(UTC),
        "IDLE",
        None,
    )
    audit(
        db,
        agency_id,
        "EMAIL_SYNC_COMPLETED",
        sync,
        details={"classification_jobs": queued, "invoice_id": str(invoice_id)},
    )
    db.commit()
