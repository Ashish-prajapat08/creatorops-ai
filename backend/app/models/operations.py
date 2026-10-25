import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TenantRecord


class EmailAnalysis(TenantRecord, Base):
    __tablename__ = "email_analyses"
    __table_args__ = (
        UniqueConstraint("agency_id", "message_id", name="uq_analysis_message"),
        UniqueConstraint("agency_id", "id"),
        ForeignKeyConstraint(
            ["agency_id", "message_id"], ["email_messages.agency_id", "email_messages.id"]
        ),
        ForeignKeyConstraint(["agency_id", "invoice_id"], ["invoices.agency_id", "invoices.id"]),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','REVIEW','ACCEPTED','REJECTED','FAILED')"
        ),
    )
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    schema_version: Mapped[str] = mapped_column(String(16), default="email-v1")
    model: Mapped[str | None] = mapped_column(String(80))
    model_output: Mapped[dict | None] = mapped_column(JSON)
    classification: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(default=0)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_decision: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))


class PaymentPromise(TenantRecord, Base):
    __tablename__ = "payment_promises"
    __table_args__ = (
        UniqueConstraint("agency_id", "analysis_id", name="uq_promise_analysis"),
        UniqueConstraint("agency_id", "id"),
        ForeignKeyConstraint(
            ["agency_id", "analysis_id"], ["email_analyses.agency_id", "email_analyses.id"]
        ),
        ForeignKeyConstraint(
            ["agency_id", "source_message_id"], ["email_messages.agency_id", "email_messages.id"]
        ),
        ForeignKeyConstraint(["agency_id", "invoice_id"], ["invoices.agency_id", "invoices.id"]),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_message_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    promised_date: Mapped[date | None] = mapped_column(Date, index=True)
    date_status: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="CLAIMED")
    evidence: Mapped[str] = mapped_column(Text)
    # A promise is a sender claim, never evidence of a received payment.


class EmailSync(TenantRecord, Base):
    __tablename__ = "email_syncs"
    __table_args__ = (
        UniqueConstraint("agency_id", "invoice_id", name="uq_sync_invoice"),
        ForeignKeyConstraint(["agency_id", "invoice_id"], ["invoices.agency_id", "invoices.id"]),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    checkpoint_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="IDLE")
    error_code: Mapped[str | None] = mapped_column(String(80))


class PaymentTransaction(TenantRecord, Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint("agency_id", "id"),
        UniqueConstraint("agency_id", "source", "external_id", name="uq_transaction_source_id"),
        UniqueConstraint("agency_id", "dedupe_key", name="uq_transaction_dedupe"),
        ForeignKeyConstraint(["agency_id", "brand_id"], ["brands.agency_id", "brands.id"]),
        ForeignKeyConstraint(["agency_id", "invoice_id"], ["invoices.agency_id", "invoices.id"]),
        CheckConstraint("amount > 0"),
        CheckConstraint("source IN ('MANUAL','MOCK')"),
    )
    external_id: Mapped[str] = mapped_column(String(160))
    dedupe_key: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    transaction_date: Mapped[date] = mapped_column(Date)
    external_reference: Mapped[str | None] = mapped_column(String(160))
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    invoice_reference: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="UNMATCHED", index=True)
    imported_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(default=1)


class PaymentAllocation(TenantRecord, Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("agency_id", "id"),
        ForeignKeyConstraint(
            ["agency_id", "transaction_id"],
            ["payment_transactions.agency_id", "payment_transactions.id"],
        ),
        ForeignKeyConstraint(["agency_id", "invoice_id"], ["invoices.agency_id", "invoices.id"]),
        CheckConstraint("amount > 0"),
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(16), default="CONFIRMED")
    confirmed_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(Text)


class ReconciliationDecision(TenantRecord, Base):
    __tablename__ = "reconciliation_decisions"
    __table_args__ = (
        UniqueConstraint(
            "agency_id", "transaction_id", "idempotency_key", name="uq_reconciliation_request"
        ),
        ForeignKeyConstraint(
            ["agency_id", "transaction_id"],
            ["payment_transactions.agency_id", "payment_transactions.id"],
        ),
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid)
