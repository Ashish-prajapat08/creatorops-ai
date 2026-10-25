from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


def exact_decimal(value):
    if isinstance(value, float):
        raise ValueError("Send decimal values as strings; floating point money is not accepted")
    return value


Money = Annotated[
    Decimal, BeforeValidator(exact_decimal), Field(gt=0, max_digits=18, decimal_places=2)
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Name = Annotated[str, Field(min_length=1, max_length=160)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: dict = Field(default_factory=dict)


class RecordOut(Schema):
    id: UUID
    created_at: datetime
    updated_at: datetime


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    FINANCE = "FINANCE"
    OPS = "OPS"
    VIEWER = "VIEWER"


class AgencyIn(Schema):
    name: Name
    default_currency: Currency = "USD"
    timezone: str = "Asia/Kolkata"

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        return value


class AgencyOut(AgencyIn, RecordOut):
    slug: str
    role: Role


class UserOut(RecordOut):
    name: str
    email: EmailStr


class MemberIn(Schema):
    email: EmailStr
    role: Role


class MemberOut(Schema):
    id: UUID
    user_id: UUID
    email: EmailStr
    name: str
    role: Role


class BrandIn(Schema):
    name: Name
    contact_name: str = Field(default="", max_length=160)
    contact_email: EmailStr
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    notes: str = Field(default="", max_length=5000)


class BrandOut(BrandIn, RecordOut):
    agency_id: UUID


class CreatorIn(Schema):
    name: Name
    email: EmailStr
    default_payout_percentage: Decimal = Field(
        default=Decimal("80"), ge=0, le=100, decimal_places=2
    )
    notes: str = Field(default="", max_length=5000)


class CreatorOut(CreatorIn, RecordOut):
    agency_id: UUID


class CampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CampaignIn(Schema):
    name: Name
    brand_id: UUID
    creator_id: UUID
    description: str = Field(default="", max_length=5000)
    deal_value: Money
    currency: Currency
    start_date: date
    end_date: date
    status: CampaignStatus = CampaignStatus.ACTIVE

    @model_validator(mode="after")
    def dates_valid(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class CampaignOut(CampaignIn, RecordOut):
    agency_id: UUID


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceIn(Schema):
    payment_reference: str | None = Field(default=None, max_length=160)
    invoice_number: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    brand_id: UUID
    campaign_id: UUID
    amount: Money
    currency: Currency
    issue_date: date
    due_date: date
    status: InvoiceStatus = InvoiceStatus.SENT
    description: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def dates_valid(self):
        if self.due_date < self.issue_date:
            raise ValueError("Due date must be on or after issue date")
        return self


class InvoiceOut(InvoiceIn, RecordOut):
    agency_id: UUID


class DraftEdit(Schema):
    subject: str = Field(min_length=1, max_length=250, pattern=r"^[^\r\n]+$")
    body: str = Field(min_length=1, max_length=10000)
    revision: int = Field(ge=1)


class ApprovalIn(Schema):
    revision: int = Field(ge=1)


class TaskOut(RecordOut):
    workflow_key: str
    task_type: str
    gmail_thread_id: str | None
    agency_id: UUID
    invoice_id: UUID
    status: str
    priority: str
    recommended_action: str
    draft_subject: str | None
    draft_body: str | None
    recipient: str | None
    context_summary: dict | None
    draft_revision: int
    approved_by: UUID | None
    approved_at: datetime | None
    sent_at: datetime | None
    gmail_message_id: str | None
    error_code: str | None


class Intent(StrEnum):
    PAYMENT_PROMISE = "PAYMENT_PROMISE"
    PAYMENT_SENT = "PAYMENT_SENT"
    PAYMENT_DELAY = "PAYMENT_DELAY"
    DISPUTE = "DISPUTE"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"
    PO_REQUIRED = "PO_REQUIRED"
    WRONG_INVOICE = "WRONG_INVOICE"
    NO_RESPONSE = "NO_RESPONSE"
    OTHER = "OTHER"


class Understanding(Schema):
    intent: Intent
    promised_date: date | None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1200)
    evidence: str = Field(max_length=2000)


class DraftOutput(Schema):
    """AI only writes prose; invoice facts and recipient are rendered by Python."""

    greeting: str = Field(min_length=1, max_length=200, pattern=r"^[^\r\n]+$")
    request: str = Field(min_length=1, max_length=2000)
    closing: str = Field(min_length=1, max_length=200)
    understanding: Understanding


class AuditOut(RecordOut):
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: UUID
    details: dict


class IntegrationOut(Schema):
    status: str
    external_account_id: str | None = None


class CurrencyTotals(Schema):
    currency: str
    total_outstanding: str
    overdue_amount: str
    due_soon_amount: str
    paid_amount: str


class SummaryOut(Schema):
    totals: list[CurrencyTotals]
    overdue_invoice_count: int
    pending_approval_count: int
    overdue_invoices: list[InvoiceOut]
