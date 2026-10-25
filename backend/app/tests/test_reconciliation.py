from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

from app.tests.conftest import records, user_headers, workspace


def transaction(client, headers, invoice=None, amount="10000.00", currency="USD", **extra):
    data = {
        "external_id": str(uuid4()),
        "amount": amount,
        "currency": currency,
        "transaction_date": date.today().isoformat(),
        "source": "MANUAL",
        **({"invoice_id": invoice["id"]} if invoice else {}),
        **extra,
    }
    response = client.post("/api/v1/transactions", headers=headers, json=data)
    assert response.status_code == 201, response.text
    return response.json()["data"], data


def approve(client, headers, tx, invoice, amount, **extra):
    data = {
        "idempotency_key": str(uuid4()),
        "revision": tx["revision"],
        "allocations": [{"invoice_id": invoice["id"], "amount": amount}],
        "reason": "Finance reviewed the manual payment record",
        **extra,
    }
    return client.post(f"/api/v1/transactions/{tx['id']}/approve", headers=headers, json=data), data


def balance(client, headers, invoice):
    return client.get(f"/api/v1/invoices/{invoice['id']}/balance", headers=headers).json()["data"]


def test_exact_partial_multiple_payments_reversal_and_audit(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    tx, _ = transaction(client, headers, invoice, amount="4000.00")
    view = client.get(f"/api/v1/transactions/{tx['id']}/reconciliation", headers=headers).json()[
        "data"
    ]
    assert view["candidates"][0]["match_type"] == "EXPLICIT_INVOICE"
    response, request = approve(client, headers, tx, invoice, "4000.00")
    assert response.status_code == 200, response.text
    assert balance(client, headers, invoice)["outstanding_balance"] == "6000.00"
    assert (
        client.get(f"/api/v1/invoices/{invoice['id']}", headers=headers).json()["data"]["status"]
        == "OVERDUE"
    )
    assert (
        client.post(
            f"/api/v1/transactions/{tx['id']}/approve", headers=headers, json=request
        ).status_code
        == 200
    )
    assert balance(client, headers, invoice)["paid_amount"] == "4000.00"
    tx2, _ = transaction(client, headers, invoice, amount="6000.00")
    response, _ = approve(client, headers, tx2, invoice, "6000.00")
    assert response.status_code == 200, response.text
    assert balance(client, headers, invoice)["outstanding_balance"] == "0.00"
    assert (
        client.get(f"/api/v1/invoices/{invoice['id']}", headers=headers).json()["data"]["status"]
        == "PAID"
    )
    allocation = response.json()["data"]["allocations"][0]
    for _ in range(2):
        response = client.post(
            f"/api/v1/allocations/{allocation['id']}/reverse",
            headers=headers,
            json={"reason": "Entered against the wrong invoice"},
        )
        assert response.status_code == 200, response.text
    assert balance(client, headers, invoice)["outstanding_balance"] == "6000.00"
    assert (
        client.patch(
            f"/api/v1/invoices/{invoice['id']}", headers=headers, json={"status": "PAID"}
        ).status_code
        == 409
    )
    actions = [
        a["action"] for a in client.get("/api/v1/audit?limit=100", headers=headers).json()["data"]
    ]
    assert "PAYMENT_ALLOCATION_REVERSED" in actions and "RECONCILIATION_APPROVED" in actions


def test_duplicate_import_conflict_and_amount_only_unmatched(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    tx, payload = transaction(client, headers)
    assert (
        client.post("/api/v1/transactions", headers=headers, json=payload).json()["data"]["id"]
        == tx["id"]
    )
    assert (
        client.post(
            "/api/v1/transactions", headers=headers, json={**payload, "amount": "1.00"}
        ).status_code
        == 409
    )
    view = client.get(f"/api/v1/transactions/{tx['id']}/reconciliation", headers=headers).json()[
        "data"
    ]
    assert view["match_status"] == "UNMATCHED" and view["candidates"] == []
    assert balance(client, headers, invoice)["paid_amount"] == "0.00"


def test_currency_mismatch_overpayment_and_ambiguous_match(client):
    headers = workspace(client)
    brand, _, _, invoice = records(client, headers)
    tx, _ = transaction(client, headers, invoice, currency="INR")
    response, _ = approve(client, headers, tx, invoice, "10000.00", acknowledge_warnings=True)
    assert response.status_code == 422
    tx, _ = transaction(client, headers, invoice, amount="12000.00")
    response, _ = approve(client, headers, tx, invoice, "12000.00")
    assert response.status_code == 409
    response, _ = approve(client, headers, tx, invoice, "12000.00", acknowledge_warnings=True)
    assert response.status_code == 200, response.text
    assert balance(client, headers, invoice)["overpaid_amount"] == "2000.00"


def test_brand_candidates_ambiguous_no_silent_match(client):
    headers = workspace(client)
    brand, _, campaign, invoice = records(client, headers)
    second = {
        key: invoice[key]
        for key in ["brand_id", "campaign_id", "amount", "currency", "issue_date", "due_date"]
    }
    second["invoice_number"] = "INV-SECOND"
    assert client.post("/api/v1/invoices", headers=headers, json=second).status_code == 201
    tx, _ = transaction(client, headers, brand_id=brand["id"])
    view = client.get(f"/api/v1/transactions/{tx['id']}/reconciliation", headers=headers).json()[
        "data"
    ]
    assert view["match_status"] == "AMBIGUOUS" and len(view["candidates"]) == 2
    assert balance(client, headers, invoice)["paid_amount"] == "0.00"


def test_concurrent_approval_and_overallocation(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    tx, _ = transaction(client, headers, invoice)
    payload = {
        "idempotency_key": str(uuid4()),
        "revision": tx["revision"],
        "allocations": [{"invoice_id": invoice["id"], "amount": "10000.00"}],
        "reason": "Reviewed manual transaction",
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda _: client.post(
                    f"/api/v1/transactions/{tx['id']}/approve", headers=headers, json=payload
                ),
                range(3),
            )
        )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert balance(client, headers, invoice)["paid_amount"] == "10000.00"
    response = client.post(
        f"/api/v1/transactions/{tx['id']}/approve",
        headers=headers,
        json={**payload, "allocations": [{"invoice_id": invoice["id"], "amount": "1.00"}]},
    )
    assert response.status_code == 409
    tx_view = client.get(f"/api/v1/transactions/{tx['id']}/reconciliation", headers=headers).json()[
        "data"
    ]
    response, _ = approve(
        client, headers, tx_view["transaction"], invoice, "1.00", acknowledge_warnings=True
    )
    assert response.status_code == 422


def test_cross_tenant_and_rbac(client):
    owner = workspace(client)
    other = workspace(client, "other@example.com")
    _, _, _, invoice = records(client, owner)
    tx, _ = transaction(client, owner, invoice)
    assert (
        client.get(f"/api/v1/transactions/{tx['id']}/reconciliation", headers=other).status_code
        == 404
    )
    assert client.get(f"/api/v1/invoices/{invoice['id']}/balance", headers=other).status_code == 404
    assert (
        client.post(
            "/api/v1/transactions",
            headers=other,
            json={
                "external_id": "bad",
                "amount": "1.00",
                "currency": "USD",
                "transaction_date": "2026-10-21",
                "invoice_id": invoice["id"],
            },
        ).status_code
        == 404
    )
    for role in ["VIEWER", "OPS", "FINANCE"]:
        member = user_headers(f"{role.lower()}@agency.example")
        client.get("/api/v1/auth/me", headers=member)
        client.post(
            "/api/v1/agencies/members",
            headers=owner,
            json={"email": f"{role.lower()}@agency.example", "role": role},
        )
        member["X-Agency-ID"] = owner["X-Agency-ID"]
        assert (
            client.post(
                "/api/v1/transactions",
                headers=member,
                json={
                    "external_id": "blocked",
                    "amount": "1.00",
                    "currency": "USD",
                    "transaction_date": "2026-10-21",
                },
            ).status_code
            == 403
        )
        if role != "FINANCE":
            assert approve(client, member, tx, invoice, "10000.00")[0].status_code == 403


def test_explicit_multi_invoice_split_requires_review(client):
    headers = workspace(client)
    _, _, _, one = records(client, headers, amount="100.00")
    _, _, _, two = records(client, headers, number="INV-TWO", amount="200.00")
    tx, _ = transaction(client, headers, amount="300.00")
    payload = {
        "idempotency_key": str(uuid4()),
        "revision": 1,
        "allocations": [
            {"invoice_id": one["id"], "amount": "100.00"},
            {"invoice_id": two["id"], "amount": "200.00"},
        ],
        "reason": "Reviewed combined payment",
    }
    url = f"/api/v1/transactions/{tx['id']}/approve"
    assert client.post(url, headers=headers, json=payload).status_code == 409
    assert (
        client.post(
            url, headers=headers, json={**payload, "acknowledge_warnings": True}
        ).status_code
        == 200
    )
    assert balance(client, headers, one)["outstanding_balance"] == "0.00"
    assert balance(client, headers, two)["outstanding_balance"] == "0.00"
