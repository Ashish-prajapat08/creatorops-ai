from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Scope, scope
from app.models.entities import Invoice
from app.models.operations import PaymentAllocation, PaymentTransaction
from app.repositories.tenant import TenantRepository
from app.schemas.contracts import Envelope
from app.schemas.operations import (
    AllocationOut,
    BalanceOut,
    ReconcileIn,
    ReconciliationOut,
    RejectionIn,
    ReversalIn,
    TransactionIn,
    TransactionOut,
)
from app.services import reconciliation
from app.services.balances import balance

router = APIRouter(tags=["manual payment reconciliation"])


@router.post("/transactions", response_model=Envelope[TransactionOut], status_code=201)
def create(data: TransactionIn, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": reconciliation.import_transaction(db, ctx, data)}


@router.get("/transactions", response_model=Envelope[list[TransactionOut]])
def listing(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return {
        "data": TenantRepository(db, ctx.agency_id).list(PaymentTransaction, offset, limit),
        "meta": {"offset": offset, "limit": limit},
    }


@router.get(
    "/transactions/{transaction_id}/reconciliation", response_model=Envelope[ReconciliationOut]
)
def get(transaction_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": reconciliation.view(db, ctx, transaction_id)}


@router.post("/transactions/{transaction_id}/approve", response_model=Envelope[ReconciliationOut])
def approve(
    transaction_id: UUID,
    data: ReconcileIn,
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return {"data": reconciliation.approve(db, ctx, transaction_id, data)}


@router.post("/transactions/{transaction_id}/reject", response_model=Envelope[ReconciliationOut])
def reject(
    transaction_id: UUID,
    data: RejectionIn,
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return {"data": reconciliation.reject(db, ctx, transaction_id, data)}


@router.post("/allocations/{allocation_id}/reverse", response_model=Envelope[ReconciliationOut])
def reverse(
    allocation_id: UUID,
    data: ReversalIn,
    ctx: Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return {"data": reconciliation.reverse(db, ctx, allocation_id, data)}


@router.get("/invoices/{invoice_id}/balance", response_model=Envelope[BalanceOut])
def balances(invoice_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": balance(db, TenantRepository(db, ctx.agency_id).get(Invoice, invoice_id))}


@router.get("/invoices/{invoice_id}/allocations", response_model=Envelope[list[AllocationOut]])
def allocations(invoice_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    repo = TenantRepository(db, ctx.agency_id)
    repo.get(Invoice, invoice_id)
    return {
        "data": db.scalars(
            repo.query(PaymentAllocation)
            .where(PaymentAllocation.invoice_id == invoice_id)
            .order_by(PaymentAllocation.created_at)
        ).all()
    }
