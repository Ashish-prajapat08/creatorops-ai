from concurrent.futures import ThreadPoolExecutor

import httpx

from app.core import security
from app.core.config import settings
from app.tests.conftest import user_headers


def test_provider_verification_rejects_unconfirmed_identity(client, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "test_mode", False)
    monkeypatch.setattr(cfg, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(cfg, "supabase_publishable_key", "publishable-test-key")
    calls = []

    def get(url, headers, **kwargs):
        calls.append((url, headers))
        return httpx.Response(
            200,
            json={
                "id": "provider-user",
                "email": "provider@example.com",
                "email_confirmed_at": None,
            },
        )

    monkeypatch.setattr(security.httpx, "get", get)
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer provider-session"})
    assert response.status_code == 403
    assert calls[0][0] == "https://project.supabase.co/auth/v1/user"
    assert calls[0][1]["Authorization"] == "Bearer provider-session"
    monkeypatch.setattr(
        security.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(401, json={"error": "invalid token"}),
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer forged-session"}
        ).status_code
        == 401
    )


def test_verified_provider_identity_can_create_workspace(client, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "test_mode", False)
    monkeypatch.setattr(cfg, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(cfg, "supabase_publishable_key", "publishable-test-key")
    monkeypatch.setattr(
        security.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={
                "id": "provider-user",
                "email": "provider@example.com",
                "email_confirmed_at": "2026-10-01T00:00:00Z",
                "user_metadata": {"name": "Verified Owner"},
            },
        ),
    )
    headers = {"Authorization": "Bearer provider-session"}
    response = client.post("/api/v1/agencies", headers=headers, json={"name": "Verified Agency"})
    assert response.status_code == 201
    headers["X-Agency-ID"] = response.json()["data"]["id"]
    assert client.get("/api/v1/brands", headers=headers).status_code == 200


def test_concurrent_identity_creation_has_one_user_and_no_conflicts(client):
    headers = user_headers()
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(
            pool.map(lambda _: client.get("/api/v1/auth/me", headers=headers), range(6))
        )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["data"]["id"] for response in responses}) == 1
