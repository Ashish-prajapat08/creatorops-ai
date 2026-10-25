import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select

from app.core.errors import AppError
from app.core.security import require, require_current
from app.models.entities import Agency, Brand, CollectionTask, Invoice
from app.models.operations import PaymentAllocation, PaymentTransaction, ReconciliationDecision
from app.repositories.tenant import TenantRepository
from app.schemas.operations import AllocationOut, ReconciliationOut, TransactionOut
from app.services.audit import audit
from app.services.balances import ZERO, balance, confirmed_total
from app.services.finance import invoice_status, today_for


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def lock_agency(db, agency_id):
    return db.scalar(select(Agency).where(Agency.id == agency_id).with_for_update())


def import_transaction(db, ctx, data):
    require(ctx, "transactions")
    lock_agency(db, ctx.agency_id)
    require_current(db, ctx, "transactions")
    repo = TenantRepository(db, ctx.agency_id)
    if data.brand_id:
        repo.get(Brand, data.brand_id)
    if data.invoice_id:
        invoice = repo.get(Invoice, data.invoice_id)
        if data.brand_id and data.brand_id != invoice.brand_id:
            raise AppError("BRAND_MISMATCH", "Explicit invoice and payer brand disagree", 422)
    fingerprint = digest(
        {"reference": data.external_reference.casefold()}
        if data.external_reference
        else {"source": data.source, "id": data.external_id}
    )
    existing = db.scalar(
        repo.query(PaymentTransaction).where(
            or_(
                PaymentTransaction.dedupe_key == fingerprint,
                (PaymentTransaction.source == data.source)
                & (PaymentTransaction.external_id == data.external_id),
            )
        )
    )
    if existing:
        values = data.model_dump(mode="json")
        saved = {
            key: TransactionOut.model_validate(existing).model_dump(mode="json")[key]
            for key in values
        }
        # Different source identifiers may refer to the same external payment reference.
        compare_keys = set(values) - {"external_id", "source"}
        if any(values[key] != saved[key] for key in compare_keys):
            raise AppError(
                "DUPLICATE_TRANSACTION_CONFLICT",
                "This source ID or external reference already exists with different details",
                409,
            )
        return existing
    transaction = PaymentTransaction(
        agency_id=ctx.agency_id,
        imported_by=ctx.user_id,
        dedupe_key=fingerprint,
        **data.model_dump(),
    )
    db.add(transaction)
    db.flush()
    audit(
        db,
        ctx.agency_id,
        "MANUAL_TRANSACTION_IMPORTED",
        transaction,
        ctx.user_id,
        "USER",
        {
            "source": data.source,
            "amount": str(data.amount),
            "currency": data.currency,
            "external_id": data.external_id,
        },
    )
    db.commit()
    return transaction


def warnings_for(db, repo, transaction, invoice, amount):
    warnings = []
    values = balance(db, invoice)
    outstanding = Decimal(values["outstanding_balance"])
    if invoice.currency != transaction.currency:
        warnings.append("CURRENCY_MISMATCH")
    if (transaction.invoice_id and transaction.invoice_id != invoice.id) or (
        transaction.invoice_reference
        and transaction.invoice_reference.casefold() != invoice.invoice_number.casefold()
    ):
        warnings.append("EXPLICIT_REFERENCE_MISMATCH")
    if transaction.brand_id and invoice.brand_id != transaction.brand_id:
        warnings.append("BRAND_MISMATCH")
    if transaction.transaction_date < invoice.issue_date:
        warnings.append("PRE_ISSUE_DATE")
    if amount > outstanding:
        warnings.append("OVERPAYMENT")
    elif amount < outstanding:
        warnings.append("PARTIAL_PAYMENT")
    duplicate = db.scalar(
        repo.query(PaymentTransaction).where(
            PaymentTransaction.id != transaction.id,
            PaymentTransaction.amount == transaction.amount,
            PaymentTransaction.currency == transaction.currency,
            PaymentTransaction.transaction_date == transaction.transaction_date,
            PaymentTransaction.brand_id == transaction.brand_id,
        )
    )
    if duplicate:
        warnings.append("POSSIBLE_DUPLICATE")
    return warnings


def proposals(db, repo, transaction):
    candidates = []
    available = transaction.amount - confirmed_total(
        db, repo.agency_id, transaction_id=transaction.id
    )
    invoices = db.scalars(repo.query(Invoice).where(Invoice.status.notin_(["DRAFT", "VOID"]))).all()
    for invoice in invoices:
        explicit = transaction.invoice_id == invoice.id or (
            transaction.invoice_reference
            and transaction.invoice_reference.casefold() == invoice.invoice_number.casefold()
        )
        external = (
            transaction.external_reference
            and invoice.payment_reference
            and transaction.external_reference.casefold() == invoice.payment_reference.casefold()
        )
        payer = transaction.brand_id == invoice.brand_id
        if not (explicit or external or payer):
            continue
        values = balance(db, invoice)
        if values["legacy_manual_paid"]:
            continue
        outstanding = Decimal(values["outstanding_balance"])
        if outstanding <= 0 and not explicit:
            continue
        if transaction.invoice_id and transaction.invoice_id != invoice.id:
            continue
        match_type = (
            "EXPLICIT_INVOICE"
            if explicit
            else "EXTERNAL_REFERENCE"
            if external
            else "BRAND_AMOUNT"
            if available == outstanding
            else "BRAND_PARTIAL"
        )
        reasons = [
            match_type,
            "DATE_ON_OR_AFTER_ISSUE"
            if transaction.transaction_date >= invoice.issue_date
            else "DATE_PRECEDES_ISSUE",
        ]
        candidates.append(
            {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "currency": invoice.currency,
                "outstanding_balance": values["outstanding_balance"],
                "amount_difference": f"{available - outstanding:.2f}",
                "match_type": match_type,
                "reasons": reasons,
                "warnings": warnings_for(db, repo, transaction, invoice, available),
            }
        )
    rank = {"EXPLICIT_INVOICE": 0, "EXTERNAL_REFERENCE": 1, "BRAND_AMOUNT": 2, "BRAND_PARTIAL": 3}
    candidates.sort(key=lambda item: (rank[item["match_type"]], item["invoice_number"]))
    usable = [c for c in candidates if "CURRENCY_MISMATCH" not in c["warnings"]]
    strongest = [c for c in usable if c["match_type"] == usable[0]["match_type"]] if usable else []
    match_status = "UNMATCHED" if not usable else "AMBIGUOUS" if len(strongest) > 1 else "SUGGESTED"
    return candidates, match_status


def view(db, ctx, transaction_id):
    repo = TenantRepository(db, ctx.agency_id)
    transaction = repo.get(PaymentTransaction, transaction_id)
    candidates, match_status = proposals(db, repo, transaction)
    allocated = confirmed_total(db, ctx.agency_id, transaction_id=transaction_id)
    if transaction.status == "REJECTED":
        match_status = "REJECTED"
    elif allocated == transaction.amount:
        match_status = "RECONCILED"
    elif allocated > 0:
        match_status = "PARTIALLY_ALLOCATED"
    history = db.scalars(
        repo.query(ReconciliationDecision)
        .where(ReconciliationDecision.transaction_id == transaction_id)
        .order_by(ReconciliationDecision.created_at)
    ).all()
    rows = db.scalars(
        repo.query(PaymentAllocation)
        .where(PaymentAllocation.transaction_id == transaction_id)
        .order_by(PaymentAllocation.created_at)
    ).all()
    return ReconciliationOut(
        transaction=TransactionOut.model_validate(transaction),
        allocated_amount=f"{allocated:.2f}",
        unallocated_amount=f"{transaction.amount - allocated:.2f}",
        match_status=match_status,
        warnings=["MANUAL_OR_MOCK_RECORD_NOT_BANK_VERIFIED"],
        candidates=candidates,
        allocations=[AllocationOut.model_validate(a) for a in rows],
        history=[
            {
                "id": str(d.id),
                "decision": d.decision,
                "details": d.details,
                "actor_id": str(d.actor_id),
                "created_at": d.created_at.isoformat(),
            }
            for d in history
        ],
    )


def invalidate_collections(db, repo, invoice):
    tasks = db.scalars(
        repo.query(CollectionTask).where(CollectionTask.invoice_id == invoice.id).with_for_update()
    ).all()
    if any(t.status in {"SENDING", "SEND_UNCERTAIN", "DRAFTING"} for t in tasks):
        raise AppError(
            "COLLECTION_IN_FLIGHT",
            "Resolve the in-flight collection before changing its payment balance",
            409,
        )
    for task in tasks:
        if task.status in {"DRAFTED", "APPROVED"}:
            task.status = "PENDING"
            task.draft_revision += 1
            task.approved_by = task.approved_at = task.approved_snapshot = None
            audit(
                db,
                repo.agency_id,
                "COLLECTION_DRAFT_INVALIDATED",
                task,
                details={"reason": "PAYMENT_BALANCE_CHANGED"},
            )


def update_invoice(db, repo, invoice, agency):
    invoice.reconciliation_managed = True
    paid = confirmed_total(db, repo.agency_id, invoice_id=invoice.id)
    invoice.status = (
        "PAID"
        if paid >= invoice.amount
        else invoice_status("SENT", invoice.due_date, today_for(agency))
    )
    audit(
        db,
        repo.agency_id,
        "INVOICE_BALANCE_UPDATED",
        invoice,
        details={
            "paid_amount": f"{paid:.2f}",
            "outstanding_balance": f"{max(invoice.amount - paid, ZERO):.2f}",
            "status": invoice.status,
        },
    )


def previous_decision(db, repo, transaction, key, payload):
    previous = db.scalar(
        repo.query(ReconciliationDecision).where(
            ReconciliationDecision.transaction_id == transaction.id,
            ReconciliationDecision.idempotency_key == key,
        )
    )
    if previous and previous.request_digest != digest(payload):
        raise AppError(
            "IDEMPOTENCY_CONFLICT", "This approval key was used for different instructions", 409
        )
    return previous


def approve(db, ctx, transaction_id, data):
    require(ctx, "reconciliation")
    agency = lock_agency(db, ctx.agency_id)
    require_current(db, ctx, "reconciliation")
    repo = TenantRepository(db, ctx.agency_id)
    transaction = repo.get(PaymentTransaction, transaction_id, lock=True)
    payload = {"decision": "APPROVE", **data.model_dump(mode="json")}
    if previous_decision(db, repo, transaction, data.idempotency_key, payload):
        return view(db, ctx, transaction.id)
    if transaction.revision != data.revision or transaction.status == "REJECTED":
        raise AppError(
            "STALE_RECONCILIATION", "Reload the current transaction before approval", 409
        )
    used = confirmed_total(db, ctx.agency_id, transaction_id=transaction.id)
    if sum((item.amount for item in data.allocations), ZERO) > transaction.amount - used:
        raise AppError(
            "TRANSACTION_OVERALLOCATED",
            "Allocations exceed the transaction's unallocated amount",
            422,
        )
    if len(data.allocations) > 1 and not data.acknowledge_warnings:
        raise AppError("REVIEW_REQUIRED", "Explicitly acknowledge a multi-invoice allocation", 409)
    for item in sorted(data.allocations, key=lambda item: str(item.invoice_id)):
        invoice = repo.get(Invoice, item.invoice_id, lock=True)
        if invoice.currency != transaction.currency:
            raise AppError(
                "CURRENCY_MISMATCH", "Transaction and invoice currencies must match", 422
            )
        if invoice.status in {"DRAFT", "VOID"} or (
            invoice.status == "PAID" and not invoice.reconciliation_managed
        ):
            raise AppError(
                "INVOICE_NOT_RECONCILABLE",
                "This draft, void, or legacy manually-paid invoice cannot receive allocations",
                409,
            )
        warnings = warnings_for(db, repo, transaction, invoice, item.amount)
        if (
            set(warnings)
            & {
                "OVERPAYMENT",
                "BRAND_MISMATCH",
                "POSSIBLE_DUPLICATE",
                "PRE_ISSUE_DATE",
                "EXPLICIT_REFERENCE_MISMATCH",
            }
            and not data.acknowledge_warnings
        ):
            raise AppError(
                "REVIEW_REQUIRED",
                "Review and acknowledge the transaction discrepancies before allocating",
                409,
            )
        invalidate_collections(db, repo, invoice)
        allocation = PaymentAllocation(
            agency_id=ctx.agency_id,
            transaction_id=transaction.id,
            invoice_id=invoice.id,
            amount=item.amount,
            confirmed_by=ctx.user_id,
            confirmed_at=datetime.now(UTC),
        )
        db.add(allocation)
        db.flush()
        audit(
            db,
            ctx.agency_id,
            "PAYMENT_ALLOCATION_CONFIRMED",
            allocation,
            ctx.user_id,
            "USER",
            {
                "transaction_id": str(transaction.id),
                "invoice_id": str(invoice.id),
                "amount": f"{item.amount:.2f}",
                "currency": invoice.currency,
                "warnings": warnings,
            },
        )
        update_invoice(db, repo, invoice, agency)
    transaction.revision += 1
    total = confirmed_total(db, ctx.agency_id, transaction_id=transaction.id)
    transaction.status = "RECONCILED" if total == transaction.amount else "PARTIAL"
    decision = ReconciliationDecision(
        agency_id=ctx.agency_id,
        transaction_id=transaction.id,
        idempotency_key=data.idempotency_key,
        request_digest=digest(payload),
        decision="APPROVE",
        details=payload,
        actor_id=ctx.user_id,
    )
    db.add(decision)
    db.flush()
    audit(
        db,
        ctx.agency_id,
        "RECONCILIATION_APPROVED",
        decision,
        ctx.user_id,
        "USER",
        {"transaction_id": str(transaction.id), "reason": data.reason},
    )
    db.commit()
    return view(db, ctx, transaction.id)


def reject(db, ctx, transaction_id, data):
    require(ctx, "reconciliation")
    lock_agency(db, ctx.agency_id)
    require_current(db, ctx, "reconciliation")
    repo = TenantRepository(db, ctx.agency_id)
    transaction = repo.get(PaymentTransaction, transaction_id, lock=True)
    payload = {"decision": "REJECT", **data.model_dump(mode="json")}
    if previous_decision(db, repo, transaction, data.idempotency_key, payload):
        return view(db, ctx, transaction.id)
    if (
        transaction.revision != data.revision
        or confirmed_total(db, ctx.agency_id, transaction_id=transaction.id) > 0
    ):
        raise AppError(
            "STALE_RECONCILIATION",
            "Reverse confirmed allocations before rejecting a transaction",
            409,
        )
    transaction.status = "REJECTED"
    transaction.revision += 1
    decision = ReconciliationDecision(
        agency_id=ctx.agency_id,
        transaction_id=transaction.id,
        idempotency_key=data.idempotency_key,
        request_digest=digest(payload),
        decision="REJECT",
        details=payload,
        actor_id=ctx.user_id,
    )
    db.add(decision)
    db.flush()
    audit(
        db,
        ctx.agency_id,
        "RECONCILIATION_REJECTED",
        decision,
        ctx.user_id,
        "USER",
        {"reason": data.reason},
    )
    db.commit()
    return view(db, ctx, transaction.id)


def reverse(db, ctx, allocation_id, data):
    require(ctx, "reconciliation")
    agency = lock_agency(db, ctx.agency_id)
    require_current(db, ctx, "reconciliation")
    repo = TenantRepository(db, ctx.agency_id)
    allocation = repo.get(PaymentAllocation, allocation_id, lock=True)
    if allocation.status == "REVERSED":
        return view(db, ctx, allocation.transaction_id)
    transaction = repo.get(PaymentTransaction, allocation.transaction_id, lock=True)
    invoice = repo.get(Invoice, allocation.invoice_id, lock=True)
    invalidate_collections(db, repo, invoice)
    (
        allocation.status,
        allocation.reversed_by,
        allocation.reversed_at,
        allocation.reversal_reason,
    ) = "REVERSED", ctx.user_id, datetime.now(UTC), data.reason
    db.flush()
    update_invoice(db, repo, invoice, agency)
    transaction.revision += 1
    transaction.status = (
        "PARTIAL"
        if confirmed_total(db, ctx.agency_id, transaction_id=transaction.id) > 0
        else "UNMATCHED"
    )
    audit(
        db,
        ctx.agency_id,
        "PAYMENT_ALLOCATION_REVERSED",
        allocation,
        ctx.user_id,
        "USER",
        {
            "invoice_id": str(invoice.id),
            "transaction_id": str(transaction.id),
            "reason": data.reason,
            "amount": str(allocation.amount),
        },
    )
    db.commit()
    return view(db, ctx, transaction.id)
