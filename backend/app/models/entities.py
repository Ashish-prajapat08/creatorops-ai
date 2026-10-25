import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def now():
    return datetime.now(UTC)


class Record:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TenantRecord(Record):
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id"), index=True)


class Agency(Record, Base):
    __tablename__ = "agencies"
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), unique=True)
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    auth_provider_id: Mapped[str] = mapped_column(String(160), unique=True)


class Membership(TenantRecord, Base):
    __tablename__ = "agency_memberships"
    __table_args__ = (
        UniqueConstraint("agency_id", "user_id"),
        CheckConstraint("role IN ('OWNER','ADMIN','FINANCE','OPS','VIEWER')"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))


class Brand(TenantRecord, Base):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("agency_id", "id"),
        Index("brand_agency_name", "agency_id", "name"),
    )
    name: Mapped[str] = mapped_column(String(160))
    contact_name: Mapped[str] = mapped_column(String(160), default="")
    contact_email: Mapped[str] = mapped_column(String(254))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    notes: Mapped[str] = mapped_column(Text, default="")


class Creator(TenantRecord, Base):
    __tablename__ = "creators"
    __table_args__ = (
        UniqueConstraint("agency_id", "id"),
        CheckConstraint("default_payout_percentage >= 0 AND default_payout_percentage <= 100"),
    )
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254))
    default_payout_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=80)
    notes: Mapped[str] = mapped_column(Text, default="")


class Campaign(TenantRecord, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("agency_id", "id"),
        UniqueConstraint("agency_id", "id", "brand_id"),
        ForeignKeyConstraint(["agency_id", "brand_id"], ["brands.agency_id", "brands.id"]),
        ForeignKeyConstraint(["agency_id", "creator_id"], ["creators.agency_id", "creators.id"]),
        CheckConstraint("deal_value > 0"),
        CheckConstraint("end_date >= start_date"),
        CheckConstraint("status IN ('DRAFT','ACTIVE','COMPLETED','CANCELLED')"),
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    deal_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class Invoice(TenantRecord, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("agency_id", "id"),
        UniqueConstraint("agency_id", "invoice_number"),
        ForeignKeyConstraint(["agency_id", "brand_id"], ["brands.agency_id", "brands.id"]),
        ForeignKeyConstraint(
            ["agency_id", "campaign_id", "brand_id"],
            ["campaigns.agency_id", "campaigns.id", "campaigns.brand_id"],
        ),
        CheckConstraint("amount > 0"),
        CheckConstraint("due_date >= issue_date"),
        CheckConstraint("status IN ('DRAFT','SENT','DUE','OVERDUE','PAID','VOID')"),
        Index("invoice_due_status", "agency_id", "status", "due_date"),
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    invoice_number: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="SENT")
    description: Mapped[str] = mapped_column(Text, default="")
    payment_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    reconciliation_managed: Mapped[bool] = mapped_column(default=False)


class CollectionTask(TenantRecord, Base):
    __tablename__ = "collection_tasks"
    __table_args__ = (
        UniqueConstraint("agency_id", "invoice_id", "workflow_key", name="uq_collection_stage"),
        UniqueConstraint("agency_id", "id"),
        ForeignKeyConstraint(["agency_id", "invoice_id"], ["invoices.agency_id", "invoices.id"]),
        CheckConstraint(
            "status IN ('PENDING','DRAFTING','DRAFTED','APPROVED','SENDING','SENT','COMPLETED','REJECTED','FAILED','SEND_UNCERTAIN')"
        ),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workflow_key: Mapped[str] = mapped_column(String(100), default="OVERDUE")
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="NORMAL")
    task_type: Mapped[str] = mapped_column(String(32), default="PAYMENT_FOLLOW_UP")
    recommended_action: Mapped[str] = mapped_column(
        Text, default="Send a professional payment follow-up"
    )
    draft_subject: Mapped[str | None] = mapped_column(String(250))
    draft_body: Mapped[str | None] = mapped_column(Text)
    recipient: Mapped[str | None] = mapped_column(String(254))
    context_summary: Mapped[dict | None] = mapped_column(JSON)
    draft_revision: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_snapshot: Mapped[dict | None] = mapped_column(JSON)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gmail_message_id: Mapped[str | None] = mapped_column(String(160))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(160))
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


class EmailThread(TenantRecord, Base):
    __tablename__ = "email_threads"
    __table_args__ = (
        UniqueConstraint("agency_id", "gmail_thread_id"),
        UniqueConstraint("agency_id", "id"),
        ForeignKeyConstraint(["agency_id", "invoice_id"], ["invoices.agency_id", "invoices.id"]),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    brand_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    gmail_thread_id: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(250))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EmailMessage(TenantRecord, Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("agency_id", "gmail_message_id"),
        UniqueConstraint("agency_id", "id", name="uq_email_message_tenant_id"),
        ForeignKeyConstraint(
            ["agency_id", "thread_id"], ["email_threads.agency_id", "email_threads.id"]
        ),
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    gmail_message_id: Mapped[str] = mapped_column(String(160))
    direction: Mapped[str] = mapped_column(String(16))
    sender_email: Mapped[str] = mapped_column(String(254))
    recipient_emails: Mapped[list] = mapped_column(JSON)
    subject: Mapped[str] = mapped_column(String(250))
    body_text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Integration(TenantRecord, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("agency_id", "provider"),)
    provider: Mapped[str] = mapped_column(String(16), default="GMAIL")
    status: Mapped[str] = mapped_column(String(24), default="CONNECTED")
    external_account_id: Mapped[str] = mapped_column(String(254))
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthState(TenantRecord, Base):
    __tablename__ = "oauth_states"
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAction(TenantRecord, Base):
    __tablename__ = "ai_actions"
    entity_type: Mapped[str] = mapped_column(String(40), default="collection_task")
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action_type: Mapped[str] = mapped_column(String(40), default="COLLECTION_DRAFT")
    status: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(80))
    input_reference: Mapped[str] = mapped_column(String(160))
    output_summary: Mapped[dict | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(TenantRecord, Base):
    __tablename__ = "audit_logs"
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(TenantRecord, Base):
    """Transactional outbox; PostgreSQL owns intent, Redis only transports IDs."""

    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


# Register the additional normalized V2 tables for migrations and application metadata.
from app.models import operations as _operations  # noqa: E402,F401
