from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import Scope, require, scope
from app.integrations.gmail import oauth
from app.models.entities import (
    Agency,
    AuditLog,
    CollectionTask,
    EmailMessage,
    EmailThread,
    Integration,
    Invoice,
)
from app.models.operations import (
    EmailAnalysis,
    PaymentAllocation,
    PaymentPromise,
    ReconciliationDecision,
)
from app.repositories.tenant import TenantRepository
from app.schemas.contracts import (
    ApprovalIn,
    AuditOut,
    DraftEdit,
    Envelope,
    IntegrationOut,
    InvoiceOut,
    InvoiceStatus,
    SummaryOut,
    TaskOut,
)
from app.schemas.operations import AllocationOut, PromiseOut
from app.services.balances import balance
from app.services.collections import CollectionService
from app.services.finance import dashboard, invoice_status, scan_agency, today_for

router = APIRouter(tags=["operations"])


@router.get("/dashboard/summary", response_model=Envelope[SummaryOut])
def summary(ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": dashboard(db, db.get(Agency, ctx.agency_id))}


@router.get("/invoices/overdue", response_model=Envelope[list[InvoiceOut]])
def overdue(ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": dashboard(db, db.get(Agency, ctx.agency_id))["overdue_invoices"]}


@router.post("/collections/scan", response_model=Envelope[dict])
def scan(ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    require(ctx, "draft")
    return {"data": {"created": scan_agency(db, db.get(Agency, ctx.agency_id))}}


@router.get("/collections/tasks", response_model=Envelope[list[TaskOut]])
def tasks(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return {
        "data": TenantRepository(db, ctx.agency_id).list(CollectionTask, offset, limit),
        "meta": {"offset": offset, "limit": limit},
    }


@router.get("/collections/tasks/{task_id}", response_model=Envelope[TaskOut])
def task(task_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": TenantRepository(db, ctx.agency_id).get(CollectionTask, task_id)}


@router.post(
    "/collections/tasks/{task_id}/draft", response_model=Envelope[TaskOut], status_code=202
)
def draft(task_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": CollectionService(db, ctx).draft(task_id)}


@router.patch("/collections/tasks/{task_id}/draft", response_model=Envelope[TaskOut])
def edit(
    task_id: UUID, data: DraftEdit, ctx: Scope = Depends(scope), db: Session = Depends(get_db)
):
    return {"data": CollectionService(db, ctx).edit(task_id, data)}


@router.post(
    "/collections/tasks/{task_id}/approve", response_model=Envelope[TaskOut], status_code=202
)
def approve(
    task_id: UUID, data: ApprovalIn, ctx: Scope = Depends(scope), db: Session = Depends(get_db)
):
    return {"data": CollectionService(db, ctx).approve(task_id, data)}


@router.post("/collections/tasks/{task_id}/reject", response_model=Envelope[TaskOut])
def reject(task_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": CollectionService(db, ctx).reject(task_id)}


@router.post(
    "/collections/tasks/{task_id}/reconcile", response_model=Envelope[TaskOut], status_code=202
)
def reconcile(task_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": CollectionService(db, ctx).reconcile(task_id)}


@router.get("/invoices/{invoice_id}/history", response_model=Envelope[dict])
def invoice_history(invoice_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    repo = TenantRepository(db, ctx.agency_id)
    invoice = repo.get(Invoice, invoice_id)
    agency = db.get(Agency, ctx.agency_id)
    invoice_view = InvoiceOut.model_validate(invoice).model_copy(
        update={
            "status": InvoiceStatus(
                invoice_status(invoice.status, invoice.due_date, today_for(agency))
            )
        }
    )
    task_list = db.scalars(
        repo.query(CollectionTask).where(CollectionTask.invoice_id == invoice_id)
    ).all()
    task_ids = [t.id for t in task_list]
    analyses = db.scalars(
        repo.query(EmailAnalysis).where(EmailAnalysis.invoice_id == invoice_id)
    ).all()
    promises = db.scalars(
        repo.query(PaymentPromise).where(PaymentPromise.invoice_id == invoice_id)
    ).all()
    allocations = db.scalars(
        repo.query(PaymentAllocation).where(PaymentAllocation.invoice_id == invoice_id)
    ).all()
    transaction_ids = [a.transaction_id for a in allocations]
    decisions = db.scalars(
        repo.query(ReconciliationDecision).where(
            ReconciliationDecision.transaction_id.in_(transaction_ids)
        )
    ).all()
    event_ids = [
        invoice_id,
        *task_ids,
        *transaction_ids,
        *[x.id for x in [*analyses, *promises, *allocations, *decisions]],
    ]
    logs = db.scalars(
        repo.query(AuditLog).where(AuditLog.entity_id.in_(event_ids)).order_by(AuditLog.created_at)
    ).all()
    emails = db.scalars(
        repo.query(EmailMessage)
        .join(
            EmailThread,
            (EmailThread.id == EmailMessage.thread_id) & (EmailThread.agency_id == ctx.agency_id),
        )
        .where(EmailThread.invoice_id == invoice_id)
        .order_by(EmailMessage.sent_at)
    ).all()
    return {
        "data": {
            "invoice": invoice_view.model_dump(mode="json"),
            "balance": balance(db, invoice),
            "promises": [PromiseOut.model_validate(p).model_dump(mode="json") for p in promises],
            "allocations": [
                AllocationOut.model_validate(a).model_dump(mode="json") for a in allocations
            ],
            "tasks": [TaskOut.model_validate(t).model_dump(mode="json") for t in task_list],
            "audit": [AuditOut.model_validate(log).model_dump(mode="json") for log in logs],
            "emails": [
                {
                    "id": str(m.id),
                    "direction": m.direction,
                    "sender": m.sender_email,
                    "subject": m.subject,
                    "body": m.body_text,
                    "sent_at": m.sent_at.isoformat(),
                }
                for m in emails
            ],
        }
    }


@router.get("/audit", response_model=Envelope[list[AuditOut]])
def audit(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return {
        "data": TenantRepository(db, ctx.agency_id).list(AuditLog, offset, limit),
        "meta": {"offset": offset, "limit": limit},
    }


@router.get("/integrations/gmail", response_model=Envelope[IntegrationOut])
def integration(ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    integration = db.scalar(
        TenantRepository(db, ctx.agency_id)
        .query(Integration)
        .where(Integration.provider == "GMAIL")
    )
    return {"data": integration or {"status": "DISCONNECTED"}}


@router.post("/integrations/gmail/connect", response_model=Envelope[dict])
def connect(ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": {"url": oauth.connect(db, ctx)}}


@router.get("/integrations/gmail/callback")
def callback(code: str, state: str, db: Session = Depends(get_db)):
    oauth.callback(db, code, state)
    return RedirectResponse(f"{settings().frontend_url}/settings?gmail=connected", status_code=303)


@router.delete("/integrations/gmail", response_model=Envelope[dict])
def disconnect(ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    oauth.disconnect(db, ctx)
    return {"data": {"disconnected": True}}
