from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import settings
from app.models.entities import Agency, CollectionTask, Invoice
from app.repositories.tenant import TenantRepository
from app.schemas.contracts import InvoiceOut, InvoiceStatus
from app.services.audit import audit
from app.services.balances import balance


def today_for(agency):
    return datetime.now(ZoneInfo(agency.timezone)).date()


def invoice_status(status, due_date, today):
    if status in {"PAID", "VOID", "DRAFT"}:
        return status
    return "OVERDUE" if today > due_date else "DUE" if today == due_date else "SENT"


def collection_eligible(invoice, task, today, db=None):
    if invoice.status in {"PAID", "VOID", "DRAFT"}:
        return False
    if task.workflow_key == "DUE_SOON":
        return (
            today <= invoice.due_date <= today + timedelta(days=settings().collection_due_soon_days)
        )
    if task.workflow_key.startswith("PROMISE_MISSED:"):
        if db is None:
            return False
        from uuid import UUID

        from app.models.operations import PaymentPromise

        promise = db.scalar(
            TenantRepository(db, invoice.agency_id)
            .query(PaymentPromise)
            .where(
                PaymentPromise.id == UUID(task.workflow_key.split(":", 1)[1]),
                PaymentPromise.invoice_id == invoice.id,
            )
        )
        return bool(
            promise
            and promise.status == "MISSED"
            and promise.promised_date
            and promise.promised_date < today
        )
    return task.workflow_key == "OVERDUE" and today > invoice.due_date


def create_stage(db, agency_id, invoice_id, key, recommendation):
    repo = TenantRepository(db, agency_id)
    task = db.scalar(
        repo.query(CollectionTask).where(
            CollectionTask.invoice_id == invoice_id, CollectionTask.workflow_key == key
        )
    )
    if task:
        return False
    task = CollectionTask(
        agency_id=agency_id,
        invoice_id=invoice_id,
        workflow_key=key,
        task_type=key.split(":")[0],
        recommended_action=recommendation,
    )
    db.add(task)
    db.flush()
    audit(db, agency_id, "COLLECTION_TASK_CREATED", task, details={"stage": key})
    return True


def scan_agency(db, agency: Agency):
    agency = db.scalar(select(Agency).where(Agency.id == agency.id).with_for_update())
    repo = TenantRepository(db, agency.id)
    today, count = today_for(agency), 0
    for invoice in db.scalars(repo.query(Invoice).order_by(Invoice.id).with_for_update()).all():
        status = invoice_status(invoice.status, invoice.due_date, today)
        if status != invoice.status:
            invoice.status = status
            audit(db, agency.id, "INVOICE_STATUS_UPDATED", invoice, details={"status": status})
        tasks = db.scalars(
            repo.query(CollectionTask).where(CollectionTask.invoice_id == invoice.id)
        ).all()
        if (
            status not in {"PAID", "VOID", "DRAFT"}
            and Decimal(balance(db, invoice)["outstanding_balance"]) > 0
        ):
            if status == "OVERDUE":
                count += create_stage(
                    db, agency.id, invoice.id, "OVERDUE", "Send a professional payment follow-up"
                )
            elif invoice.due_date <= today + timedelta(days=settings().collection_due_soon_days):
                count += create_stage(
                    db,
                    agency.id,
                    invoice.id,
                    "DUE_SOON",
                    "Prepare a courteous upcoming-payment reminder",
                )
        for task in tasks:
            if not collection_eligible(invoice, task, today, db) and task.status in {
                "PENDING",
                "DRAFTED",
                "FAILED",
                "APPROVED",
            }:
                task.status = "COMPLETED"
                audit(db, agency.id, "COLLECTION_COMPLETED", task)
    db.commit()
    return count


def dashboard(db, agency):
    today = today_for(agency)
    invoices = db.scalars(TenantRepository(db, agency.id).query(Invoice)).all()
    totals = defaultdict(
        lambda: {
            key: Decimal("0.00")
            for key in ["total_outstanding", "overdue_amount", "due_soon_amount", "paid_amount"]
        }
    )
    overdue = []
    for invoice in invoices:
        state = invoice_status(invoice.status, invoice.due_date, today)
        group = totals[invoice.currency]
        values = balance(db, invoice)
        if state == "PAID" or invoice.reconciliation_managed:
            group["paid_amount"] += Decimal(values["paid_amount"])
        if state not in {"DRAFT", "VOID", "PAID"}:
            outstanding = Decimal(values["outstanding_balance"])
            group["total_outstanding"] += outstanding
            if state == "OVERDUE":
                group["overdue_amount"] += outstanding
                overdue.append(
                    InvoiceOut.model_validate(invoice).model_copy(
                        update={"status": InvoiceStatus.OVERDUE}
                    )
                )
            elif invoice.due_date <= today + timedelta(days=7):
                group["due_soon_amount"] += outstanding
    tasks = db.scalars(
        TenantRepository(db, agency.id)
        .query(CollectionTask)
        .where(CollectionTask.status == "DRAFTED")
    ).all()
    return {
        "totals": [
            {"currency": c, **{k: f"{v:.2f}" for k, v in g.items()}}
            for c, g in sorted(totals.items())
        ],
        "overdue_invoice_count": len(overdue),
        "pending_approval_count": len(tasks),
        "overdue_invoices": sorted(overdue, key=lambda i: i.due_date)[:50],
    }
