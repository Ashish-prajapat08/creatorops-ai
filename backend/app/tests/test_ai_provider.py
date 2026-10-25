import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agents import provider
from app.agents.collections.graph import TestDraftModel, validate_output
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.contracts import DraftOutput


@pytest.fixture(autouse=True)
def clean_database():
    # Provider contract tests do not access a database.
    yield


def configure(monkeypatch, content=None, finish="stop", key="dummy"):
    cfg = Settings(_env_file=None, ai_provider="nvidia", nvidia_api_key=key)
    monkeypatch.setattr(provider, "settings", lambda: cfg)
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))]
    )
    constructor = Mock(return_value=client)
    monkeypatch.setattr(provider, "OpenAI", constructor)
    return constructor, client


def test_nvidia_schema_and_endpoint(monkeypatch):
    raw = TestDraftModel().generate({"latest_inbound": ""})
    constructor, client = configure(monkeypatch, json.dumps(raw))
    assert provider.generate_structured("prompt", {}, DraftOutput) == raw
    assert constructor.call_args.kwargs["base_url"] == "https://integrate.api.nvidia.com/v1"
    args = client.chat.completions.create.call_args.kwargs
    assert args["response_format"]["type"] == "json_schema"
    assert args["model"] == "openai/gpt-oss-20b"


@pytest.mark.parametrize(
    "content,finish", [("{}", "stop"), ("not json", "stop"), (None, "stop"), ("{}", "length")]
)
def test_invalid_or_truncated_output_rejected(monkeypatch, content, finish):
    configure(monkeypatch, content, finish)
    with pytest.raises(AppError):
        provider.generate_structured("prompt", {}, DraftOutput)


def test_missing_key_never_calls_provider(monkeypatch):
    constructor, _ = configure(monkeypatch, key="")
    with pytest.raises(AppError, match="Configure"):
        provider.generate_structured("prompt", {}, DraftOutput)
    constructor.assert_not_called()


def test_nvidia_output_still_requires_business_validation(monkeypatch):
    raw = TestDraftModel().generate({"latest_inbound": ""})
    raw["request"] = "Pay $900 now."
    configure(monkeypatch, json.dumps(raw))
    output = provider.generate_structured("prompt", {}, DraftOutput)
    with pytest.raises(AppError):
        validate_output(output, {"latest_inbound": ""})


def test_openai_existing_path_preserved(monkeypatch):
    cfg = Settings(_env_file=None, ai_provider="openai", openai_api_key="dummy")
    monkeypatch.setattr(provider, "settings", lambda: cfg)
    raw = TestDraftModel().generate({"latest_inbound": ""})
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=DraftOutput.model_validate(raw)
    )
    monkeypatch.setattr(provider, "OpenAI", Mock(return_value=client))
    assert provider.generate_structured("prompt", {}, DraftOutput) == raw
    assert client.responses.parse.call_args.kwargs["store"] is False
    client.chat.completions.create.assert_not_called()


def test_nested_object_contract_is_explicit_and_invalid_shape_retried(monkeypatch):
    raw = TestDraftModel().generate({"latest_inbound": ""})
    invalid = {**raw, "understanding": "We appreciate your prompt response."}
    _, client = configure(monkeypatch)

    def response(value):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content=json.dumps(value))
                )
            ]
        )

    client.chat.completions.create.side_effect = [response(invalid), response(raw)]
    assert provider.generate_structured("prompt", {}, DraftOutput) == raw
    calls = client.chat.completions.create.call_args_list
    assert len(calls) == 2
    prompt = calls[0].kwargs["messages"][0]["content"]
    assert '"understanding"' in prompt and '"Understanding"' in prompt
    repair = calls[1].kwargs["messages"][0]["content"]
    assert "model_type" in repair
    assert invalid["understanding"] not in repair


def test_invalid_schema_retries_are_bounded(monkeypatch):
    _, client = configure(monkeypatch, "{}")
    with pytest.raises(AppError) as exc:
        provider.generate_structured("prompt", {}, DraftOutput)
    assert exc.value.code == "INVALID_AI_OUTPUT"
    assert client.chat.completions.create.call_count == 2


def test_nvidia_decimal_schema_avoids_unsupported_lookaround():
    from app.schemas.operations import EmailInsight

    wire = provider.nvidia_schema(EmailInsight)
    money = wire["properties"]["payment_amount"]["anyOf"][0]
    assert money["type"] == "string"
    assert money["pattern"] == r"^[0-9]+(\.[0-9]{1,2})?$"
    assert "decimal_places" not in money
    assert "max_digits" not in money
    assert "gt" not in money
    original = EmailInsight.model_json_schema(mode="serialization")
    assert "decimal_places" in original["properties"]["payment_amount"]["anyOf"][0]


@pytest.mark.parametrize("amount", ["0", "-1", "1.234", "1234567890123456789", 1.25])
def test_provider_translation_does_not_relax_local_money_validation(monkeypatch, amount):
    from app.agents.email_intelligence import TestEmailModel
    from app.schemas.operations import EmailInsight

    raw = TestEmailModel().generate({"body": "Thank you."})
    raw["payment_amount"] = amount
    configure(monkeypatch, json.dumps(raw))
    with pytest.raises(AppError) as exc:
        provider.generate_structured("prompt", {}, EmailInsight)
    assert exc.value.code == "INVALID_AI_OUTPUT"


@pytest.mark.parametrize("failure", ["missing_field_quote", "fabricated_quote"])
def test_evidence_retry_requires_exact_field_grounding(monkeypatch, failure):
    from app.agents.email_intelligence import TestEmailModel, validate_insight
    from app.schemas.operations import EmailInsight

    context = {
        "subject": "DEMO-001",
        "body": "We will pay on 2026-11-15.",
        "invoice_number": "DEMO-001",
        "currency": "INR",
    }
    valid = TestEmailModel().generate(context)
    valid["invoice_reference"] = "DEMO-001"
    valid["evidence"].append({"field": "invoice_reference", "quote": "DEMO-001"})
    invalid = json.loads(json.dumps(valid))
    if failure == "missing_field_quote":
        invalid["evidence"] = [e for e in invalid["evidence"] if e["field"] != "invoice_reference"]
    else:
        invalid["evidence"][0]["quote"] = "FABRICATED SOURCE TEXT"
    _, client = configure(monkeypatch)

    def response(value):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content=json.dumps(value))
                )
            ]
        )

    client.chat.completions.create.side_effect = [response(invalid), response(valid)]
    output = provider.generate_structured(
        "prompt", context, EmailInsight, validator=validate_insight
    )
    assert output["promised_date"] == "2026-11-15"
    assert client.chat.completions.create.call_count == 2
    feedback = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "FABRICATED SOURCE TEXT" not in feedback
    assert "evidence validation" in feedback


def test_repeated_invalid_evidence_fails_without_fallback(monkeypatch):
    from app.agents.email_intelligence import TestEmailModel, validate_insight
    from app.schemas.operations import EmailInsight

    context = {
        "subject": "DEMO-001",
        "body": "We will pay Friday.",
        "invoice_number": "DEMO-001",
        "currency": "INR",
    }
    raw = TestEmailModel().generate(context)
    raw["evidence"][0]["quote"] = "UNSUPPORTED CLAIM"
    _, client = configure(monkeypatch, json.dumps(raw))
    with pytest.raises(AppError) as exc:
        provider.generate_structured("prompt", context, EmailInsight, validator=validate_insight)
    assert exc.value.code == "INVALID_AI_EVIDENCE"
    assert client.chat.completions.create.call_count == 2
