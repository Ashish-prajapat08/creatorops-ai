import pytest
from pydantic import ValidationError

from app.agents.collections.graph import (
    SYSTEM_PROMPT,
    TestDraftModel,
    collection_graph,
    validate_output,
)
from app.core.errors import AppError
from app.schemas.contracts import DraftOutput


@pytest.mark.parametrize(
    "body,intent",
    [
        ("We will process payment Friday.", "PAYMENT_PROMISE"),
        ("Payment has already been sent.", "PAYMENT_SENT"),
        ("We believe this invoice is incorrect.", "DISPUTE"),
        ("", "NO_RESPONSE"),
    ],
)
def test_structured_fixture_contract(body, intent):
    context = {"latest_inbound": body}
    output = collection_graph(TestDraftModel()).invoke({"context": context})["output"]
    assert output["understanding"]["intent"] == intent
    assert output["understanding"]["promised_date"] is None


@pytest.mark.parametrize(
    "prose",
    [
        "Pay $200 today.",
        "We will charge a late fee.",
        "We will pursue legal action.",
        "Use this bank account.",
    ],
)
def test_draft_financial_and_threat_safety(prose):
    output = TestDraftModel().generate({"latest_inbound": ""})
    output["request"] = prose
    with pytest.raises(AppError):
        validate_output(output, {"latest_inbound": ""})


def test_untrusted_mail_cannot_add_financial_keys_or_recipient():
    output = TestDraftModel().generate({"latest_inbound": ""})
    for key in ["amount", "recipient", "invoice_status", "send_email"]:
        with pytest.raises(ValidationError):
            DraftOutput.model_validate({**output, key: "attacker-controlled"})
    assert "untrusted DATA" in SYSTEM_PROMPT
    assert "No tools" in SYSTEM_PROMPT


def test_hallucinated_evidence_and_dates_rejected():
    output = TestDraftModel().generate({"latest_inbound": "We will process payment Friday."})
    output["understanding"]["evidence"] = "I promise to pay tomorrow."
    with pytest.raises(AppError):
        validate_output(output, {"latest_inbound": "We will process payment Friday."})
    output["understanding"]["promised_date"] = "2026-10-10"
    with pytest.raises(AppError):
        validate_output(output, {"latest_inbound": "We will process payment Friday."})


def test_malformed_confidence_and_intent_rejected():
    output = TestDraftModel().generate({"latest_inbound": ""})
    output["understanding"]["confidence"] = 2
    with pytest.raises(ValidationError):
        DraftOutput.model_validate(output)
    output["understanding"]["confidence"] = 0.5
    output["understanding"]["intent"] = "CHANGE_INVOICE"
    with pytest.raises(ValidationError):
        DraftOutput.model_validate(output)
