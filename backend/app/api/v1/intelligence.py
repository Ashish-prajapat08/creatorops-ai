from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Scope, scope
from app.models.entities import EmailMessage, Invoice
from app.models.operations import EmailAnalysis, EmailSync, PaymentPromise
from app.repositories.tenant import TenantRepository
from app.schemas.contracts import Envelope
from app.schemas.operations import (
    AnalysisDetail,
    AnalysisOut,
    EmailReview,
    PromiseOut,
    SourceEmail,
    SyncOut,
)
from app.services import email_intelligence, email_sync

router = APIRouter(tags=["email intelligence"])


def detail(db, repo, analysis):
    return {
        **AnalysisOut.model_validate(analysis).model_dump(),
        "source": SourceEmail.model_validate(repo.get(EmailMessage, analysis.message_id)),
    }


@router.get("/email-intelligence", response_model=Envelope[list[AnalysisDetail]])
def listing(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: str | None = None,
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    repo = TenantRepository(db, ctx.agency_id)
    query = repo.query(EmailAnalysis)
    if status:
        query = query.where(EmailAnalysis.status == status)
    rows = db.scalars(
        query.order_by(EmailAnalysis.created_at.desc(), EmailAnalysis.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "data": [detail(db, repo, row) for row in rows],
        "meta": {"offset": offset, "limit": limit},
    }


@router.get("/email-intelligence/{analysis_id}", response_model=Envelope[AnalysisDetail])
def get(analysis_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    repo = TenantRepository(db, ctx.agency_id)
    return {"data": detail(db, repo, repo.get(EmailAnalysis, analysis_id))}


@router.post("/email-intelligence/{analysis_id}/review", response_model=Envelope[AnalysisOut])
def review(
    analysis_id: UUID, data: EmailReview, ctx: Scope = Depends(scope), db: Session = Depends(get_db)
):
    return {"data": email_intelligence.review(db, ctx, analysis_id, data)}


@router.post(
    "/email-intelligence/{analysis_id}/reprocess",
    response_model=Envelope[AnalysisOut],
    status_code=202,
)
def reprocess(analysis_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": email_intelligence.reprocess(db, ctx, analysis_id)}


@router.post("/invoices/{invoice_id}/sync-email", response_model=Envelope[SyncOut], status_code=202)
def sync(
    invoice_id: UUID, full: bool = False, ctx: Scope = Depends(scope), db: Session = Depends(get_db)
):
    return {"data": email_sync.request_sync(db, ctx, invoice_id, full)}


@router.get("/email-sync", response_model=Envelope[list[SyncOut]])
def sync_status(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return {"data": TenantRepository(db, ctx.agency_id).list(EmailSync, offset, limit)}


@router.get("/invoices/{invoice_id}/promises", response_model=Envelope[list[PromiseOut]])
def promises(invoice_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    repo = TenantRepository(db, ctx.agency_id)
    repo.get(Invoice, invoice_id)
    return {
        "data": db.scalars(
            repo.query(PaymentPromise)
            .where(PaymentPromise.invoice_id == invoice_id)
            .order_by(PaymentPromise.created_at.desc())
        ).all()
    }
