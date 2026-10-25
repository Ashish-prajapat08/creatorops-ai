from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.contracts import Currency, Money, RecordOut, Schema


class Classification(StrEnum):
    PAYMENT_PROMISED = "PAYMENT_PROMISED"
    PAYMENT_SENT = "PAYMENT_SENT"
    DISPUTE = "DISPUTE"
    PO_REQUIRED = "PO_REQUIRED"
    INFORMATION_REQUESTED = "INFORMATION_REQUESTED"
    PAYMENT_DELAYED = "PAYMENT_DELAYED"
    OTHER = "OTHER"
    UNCERTAIN = "UNCERTAIN"


class Evidence(Schema):
    field: Literal[
        "classification",
        "invoice_reference",
        "brand_reference",
        "promised_date",
        "payment_amount",
        "currency",
        "payment_reference",
        "delay_reason",
        "missing_information",
    ]
    quote: str = Field(min_length=1, max_length=1200)


class EmailInsight(Schema):
    classification: Classification
    confidence: float = Field(ge=0, le=1)
    invoice_reference: str | None = Field(max_length=80)
    brand_reference: str | None = Field(max_length=160)
    promised_date: date | None
    date_status: Literal["EXPLICIT", "AMBIGUOUS", "MISSING", "NOT_APPLICABLE"]
    payment_amount: Money | None
    currency: Currency | None
    payment_reference: str | None = Field(max_length=160)
    delay_reason: str | None = Field(max_length=1000)
    missing_information: list[Annotated[str, Field(max_length=300)]] = Field(max_length=10)
    summary: str = Field(min_length=1, max_length=1200)
    recommended_action: str = Field(min_length=1, max_length=1000)
    evidence: list[Evidence] = Field(max_length=20)

    @model_validator(mode="after")
    def date_consistency(self):
        if (self.date_status == "EXPLICIT") != (self.promised_date is not None):
            raise ValueError("Only explicit dates may have an extracted payment date")
        if self.classification != "PAYMENT_PROMISED" and self.date_status != "NOT_APPLICABLE":
            raise ValueError("A promised payment date requires a payment-promise classification")
        return self


class AnalysisOut(RecordOut):
    message_id: UUID
    invoice_id: UUID
    status: str
    schema_version: str
    model_output: dict | None
    classification: str | None
    confidence: Decimal | None
    review_reasons: list[str]
    revision: int
    review_decision: dict | None
    error_code: str | None


class EmailReview(Schema):
    revision: int = Field(ge=0)
    decision: Literal["ACCEPT", "REJECT"]
    classification: Classification | None = None
    promised_date: date | None = None
    date_status: Literal["EXPLICIT", "AMBIGUOUS", "MISSING", "NOT_APPLICABLE"] | None = None
    reason: str = Field(min_length=3, max_length=1000)


class SourceEmail(Schema):
    id: UUID
    subject: str
    sender_email: str
    body_text: str
    sent_at: datetime


class AnalysisDetail(AnalysisOut):
    source: SourceEmail


class SyncOut(RecordOut):
    invoice_id: UUID
    checkpoint_at: datetime | None
    last_success_at: datetime | None
    status: str
    error_code: str | None


class PromiseOut(RecordOut):
    invoice_id: UUID
    analysis_id: UUID
    source_message_id: UUID
    promised_date: date | None
    date_status: str
    status: str
    evidence: str


class TransactionIn(Schema):
    external_id: str = Field(min_length=1, max_length=160)
    amount: Money
    currency: Currency
    transaction_date: date
    external_reference: str | None = Field(default=None, min_length=1, max_length=160)
    brand_id: UUID | None = None
    invoice_id: UUID | None = None
    invoice_reference: str | None = Field(default=None, min_length=1, max_length=80)
    description: str = Field(default="", max_length=5000)
    source: Literal["MANUAL", "MOCK"] = "MANUAL"


class TransactionOut(TransactionIn, RecordOut):
    status: str
    revision: int


class AllocationIn(Schema):
    invoice_id: UUID
    amount: Money


class ReconcileIn(Schema):
    idempotency_key: str = Field(min_length=8, max_length=100)
    revision: int = Field(ge=1)
    allocations: list[AllocationIn] = Field(min_length=1, max_length=20)
    acknowledge_warnings: bool = False
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def no_duplicate_invoices(self):
        if len({a.invoice_id for a in self.allocations}) != len(self.allocations):
            raise ValueError("Each invoice may appear only once in an approval")
        return self


class RejectionIn(Schema):
    idempotency_key: str = Field(min_length=8, max_length=100)
    revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class ReversalIn(Schema):
    reason: str = Field(min_length=3, max_length=1000)


class AllocationOut(RecordOut):
    transaction_id: UUID
    invoice_id: UUID
    amount: Decimal
    status: str
    confirmed_by: UUID
    confirmed_at: datetime
    reversed_by: UUID | None
    reversed_at: datetime | None
    reversal_reason: str | None


class BalanceOut(Schema):
    invoice_id: UUID
    currency: str
    invoice_amount: str
    paid_amount: str
    outstanding_balance: str
    overpaid_amount: str
    reconciliation_managed: bool
    legacy_manual_paid: bool


class CandidateOut(Schema):
    invoice_id: UUID
    invoice_number: str
    currency: str
    outstanding_balance: str
    amount_difference: str
    match_type: str
    reasons: list[str]
    warnings: list[str]


class ReconciliationOut(Schema):
    transaction: TransactionOut
    allocated_amount: str
    unallocated_amount: str
    match_status: str
    warnings: list[str]
    candidates: list[CandidateOut]
    allocations: list[AllocationOut]
    history: list[dict]
