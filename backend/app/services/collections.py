from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.core.security import require, require_current
from app.models.entities import Agency, Brand, CollectionTask, Invoice, Job
from app.repositories.tenant import TenantRepository
from app.schemas.contracts import InvoiceIn
from app.services.audit import audit
from app.services.balances import balance
from app.services.finance import collection_eligible, today_for


def invoice_snapshot(invoice):
    return InvoiceIn.model_validate(invoice).model_dump(mode="json")


class CollectionService:
    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx
        self.repo = TenantRepository(db, ctx.agency_id)

    def locked(self, task_id):
        # Consistent lock order: agency -> invoice -> collection task.
        task = self.repo.get(CollectionTask, task_id)
        self.db.scalar(select(Agency).where(Agency.id == self.ctx.agency_id).with_for_update())
        invoice = self.repo.get(Invoice, task.invoice_id, lock=True)
        task = self.repo.get(CollectionTask, task_id, lock=True)
        return task, invoice

    def draft(self, task_id):
        require(self.ctx, "draft")
        task, invoice = self.locked(task_id)
        require_current(self.db, self.ctx, "draft")
        agency = self.db.get(Agency, self.ctx.agency_id)
        if not collection_eligible(invoice, task, today_for(agency), self.db):
            raise AppError("INVOICE_NOT_OVERDUE", "This invoice no longer needs a collection", 409)
        if task.status not in {"PENDING", "FAILED", "REJECTED", "DRAFTED"}:
            raise AppError("INVALID_TRANSITION", "This collection cannot be drafted now", 409)
        task.status, task.error_code = "DRAFTING", None
        task.approved_by = task.approved_at = task.approved_snapshot = None
        self.db.add(Job(agency_id=self.ctx.agency_id, kind="DRAFT", entity_id=task.id))
        audit(
            self.db,
            self.ctx.agency_id,
            "COLLECTION_DRAFT_REQUESTED",
            task,
            self.ctx.user_id,
            "USER",
        )
        self.db.commit()
        return task

    def edit(self, task_id, data):
        require(self.ctx, "draft")
        task, _ = self.locked(task_id)
        require_current(self.db, self.ctx, "draft")
        if task.status != "DRAFTED" or task.draft_revision != data.revision:
            raise AppError("STALE_DRAFT", "Reload the draft before editing", 409)
        task.draft_subject, task.draft_body = data.subject, data.body
        task.draft_revision += 1
        audit(
            self.db,
            self.ctx.agency_id,
            "COLLECTION_DRAFT_EDITED",
            task,
            self.ctx.user_id,
            "USER",
            {
                "revision": task.draft_revision,
                "subject": task.draft_subject,
                "body": task.draft_body,
                "recipient": task.recipient,
            },
        )
        self.db.commit()
        return task

    def approve(self, task_id, data):
        require(self.ctx, "approve")
        task, invoice = self.locked(task_id)
        require_current(self.db, self.ctx, "approve")
        if (
            task.status in {"APPROVED", "SENDING", "SENT", "SEND_UNCERTAIN"}
            and task.draft_revision == data.revision
        ):
            return task
        if task.status != "DRAFTED" or task.draft_revision != data.revision:
            raise AppError("STALE_DRAFT", "Review the current draft before approval", 409)
        agency = self.db.get(Agency, self.ctx.agency_id)
        brand = self.repo.get(Brand, invoice.brand_id)
        if not collection_eligible(invoice, task, today_for(agency), self.db):
            raise AppError("INVOICE_NOT_OVERDUE", "The invoice no longer requires collection", 409)
        if brand.contact_email != task.recipient:
            raise AppError(
                "RECIPIENT_CHANGED", "Regenerate the draft after the contact changed", 409
            )
        if not task.draft_subject or not task.draft_body:
            raise AppError("DRAFT_REQUIRED", "Generate and review a draft first", 409)
        from app.integrations.gmail.client import gmail_client

        client = gmail_client(self.db, self.ctx.agency_id)
        sender = getattr(
            getattr(client, "integration", None), "external_account_id", "test@example.com"
        )
        if (
            task.context_summary
            and task.context_summary.get("balance")
            and task.context_summary["balance"] != balance(self.db, invoice)
        ):
            raise AppError("STALE_DRAFT", "The invoice balance changed; regenerate this draft", 409)
        task.approved_snapshot = {
            "invoice": invoice_snapshot(invoice),
            "balance": balance(self.db, invoice),
            "subject": task.draft_subject,
            "body": task.draft_body,
            "recipient": task.recipient,
            "revision": task.draft_revision,
            "sender": sender,
        }
        task.status = "APPROVED"
        task.approved_by, task.approved_at = self.ctx.user_id, datetime.now(UTC)
        self.db.add(Job(agency_id=self.ctx.agency_id, kind="SEND", entity_id=task.id))
        audit(
            self.db,
            self.ctx.agency_id,
            "COLLECTION_APPROVED",
            task,
            self.ctx.user_id,
            "USER",
            {"revision": task.draft_revision, "recipient": task.recipient},
        )
        self.db.commit()
        return task

    def reject(self, task_id):
        require(self.ctx, "draft")
        task, _ = self.locked(task_id)
        require_current(self.db, self.ctx, "draft")
        if task.status not in {"DRAFTED", "PENDING", "FAILED", "APPROVED"}:
            raise AppError("INVALID_TRANSITION", "This collection cannot be rejected now", 409)
        task.status = "REJECTED"
        audit(self.db, self.ctx.agency_id, "COLLECTION_REJECTED", task, self.ctx.user_id, "USER")
        self.db.commit()
        return task

    def reconcile(self, task_id):
        require(self.ctx, "approve")
        task, _ = self.locked(task_id)
        require_current(self.db, self.ctx, "approve")
        if task.status != "SEND_UNCERTAIN":
            raise AppError("INVALID_TRANSITION", "Only an uncertain send needs reconciliation", 409)
        self.db.add(Job(agency_id=self.ctx.agency_id, kind="RECONCILE", entity_id=task.id))
        audit(
            self.db,
            self.ctx.agency_id,
            "SEND_RECONCILIATION_REQUESTED",
            task,
            self.ctx.user_id,
            "USER",
        )
        self.db.commit()
        return task
