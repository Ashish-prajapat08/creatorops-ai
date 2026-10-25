import base64
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.core.security import Scope
from app.integrations.gmail.client import decode_body
from app.models.entities import User
from app.schemas.operations import TransactionIn
from app.services.reconciliation import import_transaction
from app.tests.conftest import records, user_headers, workspace
from app.tests.test_email_intelligence import sync_reply
from app.tests.test_reconciliation import approve, balance, transaction


@pytest.mark.parametrize(
    "role,allowed", [("VIEWER", False), ("OPS", True), ("FINANCE", True), ("ADMIN", True)]
)
def test_email_review_role_matrix(client, role, allowed):
    owner = workspace(client)
    _, _, _, invoice = records(client, owner)
    row = sync_reply(client, owner, invoice)
    email = f"member-{role.lower()}@agency.example"
    member = user_headers(email)
    client.get("/api/v1/auth/me", headers=member)
    client.post("/api/v1/agencies/members", headers=owner, json={"email": email, "role": role})
    member["X-Agency-ID"] = owner["X-Agency-ID"]
    response = client.post(
        f"/api/v1/email-intelligence/{row['id']}/review",
        headers=member,
        json={
            "revision": row["revision"],
            "decision": "REJECT",
            "reason": "Reviewed the sender claim",
        },
    )
    assert response.status_code == (200 if allowed else 403)


def test_external_reference_matching_and_cross_source_duplicates(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    assert (
        client.patch(
            f"/api/v1/invoices/{invoice['id']}",
            headers=headers,
            json={"payment_reference": "NEFT-REF-123"},
        ).status_code
        == 200
    )
    tx, payload = transaction(client, headers, external_reference="NEFT-REF-123")
    candidate = client.get(
        f"/api/v1/transactions/{tx['id']}/reconciliation", headers=headers
    ).json()["data"]["candidates"][0]
    assert candidate["match_type"] == "EXTERNAL_REFERENCE"
    result = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={**payload, "external_id": "mock-copy", "source": "MOCK"},
    )
    assert result.status_code == 201 and result.json()["data"]["id"] == tx["id"]
    assert len(client.get("/api/v1/transactions", headers=headers).json()["data"]) == 1
    assert balance(client, headers, invoice)["paid_amount"] == "0.00"


def test_rejected_transaction_does_not_allocate(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    tx, _ = transaction(client, headers, invoice)
    response = client.post(
        f"/api/v1/transactions/{tx['id']}/reject",
        headers=headers,
        json={
            "revision": 1,
            "idempotency_key": "reject-request-1",
            "reason": "Not sufficient payment evidence",
        },
    )
    assert response.status_code == 200
    assert approve(client, headers, tx, invoice, "10000.00")[0].status_code == 409
    assert balance(client, headers, invoice)["outstanding_balance"] == "10000.00"


def test_revoked_membership_cannot_use_stale_scope(client):
    owner = workspace(client)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        stale = Scope(UUID(owner["X-Agency-ID"]), user.id, "ADMIN")
        from app.models.entities import Membership

        membership = db.scalar(select(Membership).where(Membership.agency_id == stale.agency_id))
        membership.role = "VIEWER"
        db.commit()
        with pytest.raises(AppError) as error:
            import_transaction(
                db,
                stale,
                TransactionIn(
                    external_id="revoked",
                    amount="1.00",
                    currency="USD",
                    transaction_date="2026-10-21",
                ),
            )
        assert error.value.status == 403


def test_html_only_email_normalization_excludes_scripts_and_attachments():
    html = "<div>We will pay on 2026-11-01.</div><script>mark_paid()</script>"
    payload = {
        "mimeType": "text/html",
        "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()},
    }
    assert "2026-11-01" in decode_body(payload)
    assert "mark_paid" not in decode_body(payload)
    assert decode_body({**payload, "filename": "attachment.html"}) == ""
