from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.contracts import InvoiceIn
from app.services.finance import invoice_status
from app.tests.conftest import records, workspace


@pytest.mark.parametrize(
    "status,delta,expected",
    [
        ("SENT", -1, "OVERDUE"),
        ("SENT", 0, "DUE"),
        ("OVERDUE", 1, "SENT"),
        ("PAID", -10, "PAID"),
        ("VOID", -10, "VOID"),
        ("DRAFT", -10, "DRAFT"),
    ],
)
def test_status_is_deterministic(status, delta, expected):
    today = date(2026, 10, 10)
    assert invoice_status(status, today + timedelta(days=delta), today) == expected


def test_decimal_dashboard_keeps_currency_separate(client):
    headers = workspace(client)
    records(client, headers, amount="0.10")
    records(client, headers, number="INV-1002", amount="0.20")
    records(client, headers, number="INV-INR", amount="1000.00", currency="INR")
    totals = client.get("/api/v1/dashboard/summary", headers=headers).json()["data"]["totals"]
    assert {t["currency"]: t["total_outstanding"] for t in totals} == {
        "USD": "0.30",
        "INR": "1000.00",
    }


def test_financial_validation(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    for invalid in [
        {"amount": 10.25},
        {"amount": "-1"},
        {"amount": "10.123"},
        {"currency": "usd"},
        {"due_date": "2000-01-01"},
    ]:
        response = client.patch(f"/api/v1/invoices/{invoice['id']}", headers=headers, json=invalid)
        assert response.status_code == 422, response.text
    assert client.delete(f"/api/v1/invoices/{invoice['id']}", headers=headers).status_code == 409


def test_money_contract_rejects_invalid_payload():
    with pytest.raises(ValidationError):
        InvoiceIn.model_validate({"amount": "NaN"})
