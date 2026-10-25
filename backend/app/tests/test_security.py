import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.security import decrypt, encrypt
from app.tests.conftest import draft_task, records, user_headers, workspace


def test_unauthenticated_and_invalid_token(client):
    assert client.get("/api/v1/brands").status_code == 401
    assert (
        client.get("/api/v1/agencies", headers={"Authorization": "Bearer forged"}).status_code
        == 401
    )


def test_tenant_read_write_and_relationship_isolation(client):
    a = workspace(client)
    b = workspace(client, "other@example.com")
    brand, creator, campaign, invoice = records(client, a)
    task = draft_task(client, a)
    for kind, entity in [
        ("brands", brand),
        ("creators", creator),
        ("campaigns", campaign),
        ("invoices", invoice),
    ]:
        assert client.get(f"/api/v1/{kind}/{entity['id']}", headers=b).status_code == 404
        assert (
            client.patch(
                f"/api/v1/{kind}/{entity['id']}",
                headers=b,
                json={"description": "Stolen"} if kind == "invoices" else {"name": "Stolen"},
            ).status_code
            == 404
        )
        assert client.delete(f"/api/v1/{kind}/{entity['id']}", headers=b).status_code == 404
        assert client.get(f"/api/v1/{kind}", headers=b).json()["data"] == []
    assert client.get(f"/api/v1/invoices/{invoice['id']}/history", headers=b).status_code == 404
    for action in ["draft", "approve", "reject", "reconcile"]:
        response = client.post(
            f"/api/v1/collections/tasks/{task['id']}/{action}",
            headers=b,
            json={"revision": 1} if action == "approve" else None,
        )
        assert response.status_code == 404
    assert client.get(f"/api/v1/collections/tasks/{task['id']}", headers=b).status_code == 404
    assert (
        client.post(
            "/api/v1/campaigns",
            headers=b,
            json={
                "name": "Invalid",
                "brand_id": brand["id"],
                "creator_id": creator["id"],
                "deal_value": "100",
                "currency": "USD",
                "start_date": "2026-01-01",
                "end_date": "2026-10-10",
            },
        ).status_code
        == 404
    )
    foreign_headers = {**a, "X-Agency-ID": b["X-Agency-ID"]}
    assert client.get("/api/v1/brands", headers=foreign_headers).status_code == 403
    assert all(
        log["entity_id"] != invoice["id"]
        for log in client.get("/api/v1/audit", headers=b).json()["data"]
    )


@pytest.mark.parametrize(
    "role,brand_allowed,creator_allowed,invoice_allowed,approve_allowed",
    [
        ("OWNER", True, True, True, True),
        ("ADMIN", True, True, True, True),
        ("FINANCE", True, False, True, True),
        ("OPS", False, True, False, False),
        ("VIEWER", False, False, False, False),
    ],
)
def test_rbac_matrix(
    client, role, brand_allowed, creator_allowed, invoice_allowed, approve_allowed
):
    owner = workspace(client)
    _, _, _, invoice = records(client, owner)
    task = draft_task(client, owner)
    member = user_headers(f"member-{role.lower()}@example.com")
    assert client.get("/api/v1/auth/me", headers=member).status_code == 200
    response = client.post(
        "/api/v1/agencies/members",
        headers=owner,
        json={"email": f"member-{role.lower()}@example.com", "role": role},
    )
    assert response.status_code == 201
    member["X-Agency-ID"] = owner["X-Agency-ID"]
    assert client.get("/api/v1/invoices", headers=member).status_code == 200
    assert (
        client.post(
            "/api/v1/brands",
            headers=member,
            json={"name": "New", "contact_email": "new@example.com"},
        ).status_code
        == 201
    ) == brand_allowed
    assert (
        client.post(
            "/api/v1/creators", headers=member, json={"name": "New", "email": "new@example.com"}
        ).status_code
        == 201
    ) == creator_allowed
    assert (
        client.patch(
            f"/api/v1/invoices/{invoice['id']}", headers=member, json={"description": "Updated"}
        ).status_code
        == 200
    ) == invoice_allowed
    # An invoice edit invalidates the draft; use a newly reviewed draft.
    if invoice_allowed:
        task = draft_task(client, owner)
    response = client.post(
        f"/api/v1/collections/tasks/{task['id']}/approve",
        headers=member,
        json={"revision": task["draft_revision"]},
    )
    assert (response.status_code == 202) == approve_allowed
    assert (
        client.post("/api/v1/integrations/gmail/connect", headers=member).status_code == 403
    ) == (role not in {"OWNER", "ADMIN"})


def test_last_owner_and_admin_escalation(client):
    owner = workspace(client)
    members = client.get("/api/v1/agencies/members", headers=owner).json()["data"]
    assert (
        client.delete(f"/api/v1/agencies/members/{members[0]['id']}", headers=owner).status_code
        == 409
    )
    admin = user_headers("admin@example.com")
    client.get("/api/v1/auth/me", headers=admin)
    client.post(
        "/api/v1/agencies/members",
        headers=owner,
        json={"email": "admin@example.com", "role": "ADMIN"},
    )
    admin["X-Agency-ID"] = owner["X-Agency-ID"]
    assert (
        client.post(
            "/api/v1/agencies/members",
            headers=admin,
            json={"email": "admin@example.com", "role": "OWNER"},
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/agencies/members/{members[0]['id']}", headers=admin).status_code
        == 403
    )


def test_database_composite_fk_rejects_cross_tenant(client):
    a, b = workspace(client), workspace(client, "other@example.com")
    _, _, _, invoice = records(client, a)
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.execute(
            text("UPDATE invoices SET agency_id=:other WHERE id=:id"),
            {"other": b["X-Agency-ID"], "id": invoice["id"]},
        )
        db.commit()


def test_token_encryption_and_test_mode_fails_closed():
    encrypted = encrypt("refresh-token")
    assert "refresh-token" not in encrypted
    assert decrypt(encrypted) == "refresh-token"
    with pytest.raises(ValueError):
        Settings(environment="production", test_mode=True)
