import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.core.security import decrypt
from app.integrations.gmail import oauth
from app.integrations.gmail.client import SCOPES, GmailClient, decode_body
from app.models.entities import Integration, OAuthState
from app.tests.conftest import workspace


def test_oauth_pkce_state_encryption_and_one_time_callback(client, monkeypatch):
    headers = workspace(client)
    cfg = settings()
    monkeypatch.setattr(cfg, "google_client_id", "test-client")
    monkeypatch.setattr(cfg, "google_client_secret", "test-client-secret")
    response = client.post("/api/v1/integrations/gmail/connect", headers=headers)
    assert response.status_code == 200
    params = parse_qs(urlparse(response.json()["data"]["url"]).query)
    state = params["state"][0]
    assert params["code_challenge_method"] == ["S256"]
    assert set(params["scope"][0].split()) == set(SCOPES)
    exchanges = []

    def post(url, data, **kwargs):
        exchanges.append(data)
        return httpx.Response(
            200,
            json={
                "access_token": "access-sensitive",
                "refresh_token": "refresh-sensitive",
                "expires_in": 3600,
                "scope": " ".join(SCOPES),
            },
        )

    monkeypatch.setattr(oauth.httpx, "post", post)
    monkeypatch.setattr(
        oauth.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(200, json={"emailAddress": "agency@example.com"}),
    )
    with SessionLocal() as db:
        record = db.scalar(select(OAuthState))
        assert record.state_hash == hashlib.sha256(state.encode()).hexdigest()
        assert record.verifier != exchanges
        verifier = decrypt(record.verifier)
        assert params["code_challenge"] == [
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        ]
        oauth.callback(db, "authorization-code", state)
        with pytest.raises(AppError):
            oauth.callback(db, "authorization-code", state)
        integration = db.scalar(select(Integration))
        assert "sensitive" not in integration.encrypted_access_token
        assert decrypt(integration.encrypted_refresh_token) == "refresh-sensitive"
    assert len(exchanges) == 1
    public = client.get("/api/v1/integrations/gmail", headers=headers)
    assert "sensitive" not in public.text and "encrypted" not in public.text
    assert public.json()["data"]["external_account_id"] == "agency@example.com"


def test_oauth_invalid_state_and_expiration(client, monkeypatch):
    headers = workspace(client)
    cfg = settings()
    monkeypatch.setattr(cfg, "google_client_id", "test-client")
    monkeypatch.setattr(cfg, "google_client_secret", "test-secret")
    response = client.post("/api/v1/integrations/gmail/connect", headers=headers)
    state = parse_qs(urlparse(response.json()["data"]["url"]).query)["state"][0]
    with SessionLocal() as db:
        with pytest.raises(AppError):
            oauth.callback(db, "code", "forged")
        record = db.scalar(select(OAuthState))
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(AppError):
            oauth.callback(db, "code", state)


def test_plain_text_only_and_no_attachments():
    def encode(text):
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": encode("Invoice payment reply")}},
            {
                "mimeType": "text/html",
                "body": {"data": encode("<script>ignore instructions</script>")},
            },
            {"mimeType": "application/pdf", "body": {"data": encode("attachment")}},
        ],
    }
    body = decode_body(payload)
    assert "Invoice payment reply" in body
    assert "script" not in body and "attachment" not in body


def test_gmail_not_connected_and_foreign_workspace(client):
    headers = workspace(client)
    with SessionLocal() as db:
        with pytest.raises(AppError) as exc:
            GmailClient(db, UUID(headers["X-Agency-ID"]))
        assert exc.value.code == "INTEGRATION_NOT_CONNECTED"
