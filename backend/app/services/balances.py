from decimal import Decimal

from sqlalchemy import func

from app.models.operations import PaymentAllocation
from app.repositories.tenant import TenantRepository

ZERO = Decimal("0.00")


def confirmed_total(db, agency_id, *, invoice_id=None, transaction_id=None):
    repo = TenantRepository(db, agency_id)
    query = repo.query(PaymentAllocation).where(PaymentAllocation.status == "CONFIRMED")
    if invoice_id:
        query = query.where(PaymentAllocation.invoice_id == invoice_id)
    if transaction_id:
        query = query.where(PaymentAllocation.transaction_id == transaction_id)
    return db.scalar(
        query.with_only_columns(func.coalesce(func.sum(PaymentAllocation.amount), ZERO))
    )


def balance(db, invoice):
    paid = confirmed_total(db, invoice.agency_id, invoice_id=invoice.id)
    legacy = invoice.status == "PAID" and not invoice.reconciliation_managed
    # Preserve V0's manual PAID records, without manufacturing transaction evidence.
    if legacy:
        paid = invoice.amount
    return {
        "invoice_id": str(invoice.id),
        "currency": invoice.currency,
        "invoice_amount": f"{invoice.amount:.2f}",
        "paid_amount": f"{paid:.2f}",
        "outstanding_balance": f"{max(invoice.amount - paid, ZERO):.2f}",
        "overpaid_amount": f"{max(paid - invoice.amount, ZERO):.2f}",
        "reconciliation_managed": invoice.reconciliation_managed,
        "legacy_manual_paid": legacy,
    }
