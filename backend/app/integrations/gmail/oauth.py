import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import decrypt, encrypt, require
from app.integrations.gmail.client import SCOPES, utc
from app.models.entities import Integration, Membership, OAuthState
from app.repositories.tenant import TenantRepository
from app.services.audit import audit


def connect(db, ctx):
    require(ctx, "integrations")
    cfg = settings()
    if not cfg.google_client_id or not cfg.google_client_secret or not cfg.encryption_key:
        raise AppError("GMAIL_NOT_CONFIGURED", "Configure Google OAuth and token encryption", 503)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    db.add(
        OAuthState(
            agency_id=ctx.agency_id,
            user_id=ctx.user_id,
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            verifier=encrypt(verifier),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    db.commit()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": cfg.google_client_id,
            "redirect_uri": cfg.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


def callback(db, code, state):
    record = db.scalar(
        select(OAuthState)
        .where(OAuthState.state_hash == hashlib.sha256(state.encode()).hexdigest())
        .with_for_update()
    )
    if not record or record.consumed_at or utc(record.expires_at) < datetime.now(UTC):
        raise AppError("INVALID_OAUTH_STATE", "Connection expired; start again", 400)
    member = db.scalar(
        TenantRepository(db, record.agency_id)
        .query(Membership)
        .where(Membership.user_id == record.user_id)
    )
    if not member or member.role not in {"OWNER", "ADMIN"}:
        raise AppError("FORBIDDEN", "Workspace administration access is required", 403)
    verifier = decrypt(record.verifier)
    record.consumed_at = datetime.now(UTC)
    db.commit()  # one use, including failed exchanges
    cfg = settings()
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": cfg.google_client_id,
                "client_secret": cfg.google_client_secret,
                "redirect_uri": cfg.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=20,
        )
        if response.status_code != 200:
            raise AppError("OAUTH_EXCHANGE_FAILED", "Google connection failed; start again", 400)
        tokens = response.json()
        if not set(SCOPES).issubset(set(tokens.get("scope", "").split())) or not tokens.get(
            "refresh_token"
        ):
            raise AppError(
                "GMAIL_SCOPE_REQUIRED", "Grant read and send access to connect Gmail", 400
            )
        profile = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=20,
        )
        if profile.status_code != 200:
            raise AppError("GMAIL_PROFILE_FAILED", "Unable to identify Gmail account", 400)
    except httpx.HTTPError as exc:
        raise AppError(
            "GMAIL_UNAVAILABLE", "Google connection unavailable; start again", 503
        ) from exc
    # Serialize reconnect with disconnect and prevent account swaps while sends are pending.
    from app.models.entities import Agency, CollectionTask

    db.scalar(select(Agency).where(Agency.id == record.agency_id).with_for_update())
    member = db.scalar(
        TenantRepository(db, record.agency_id)
        .query(Membership)
        .where(Membership.user_id == record.user_id)
    )
    if not member or member.role not in {"OWNER", "ADMIN"}:
        raise AppError("FORBIDDEN", "Workspace administration access was revoked", 403)
    busy = db.scalar(
        TenantRepository(db, record.agency_id)
        .query(CollectionTask)
        .where(CollectionTask.status.in_(["APPROVED", "SENDING", "SEND_UNCERTAIN"]))
    )
    if busy:
        raise AppError(
            "COLLECTION_IN_FLIGHT", "Resolve approved sends before reconnecting Gmail", 409
        )
    repo = TenantRepository(db, record.agency_id)
    integration = db.scalar(repo.query(Integration).where(Integration.provider == "GMAIL"))
    if not integration:
        integration = Integration(agency_id=record.agency_id)
        db.add(integration)
    integration.status = "CONNECTED"
    integration.external_account_id = profile.json()["emailAddress"]
    integration.encrypted_access_token = encrypt(tokens["access_token"])
    integration.encrypted_refresh_token = encrypt(tokens["refresh_token"])
    integration.token_expires_at = datetime.now(UTC) + timedelta(seconds=tokens["expires_in"])
    db.flush()
    audit(db, record.agency_id, "INTEGRATION_CONNECTED", integration, record.user_id, "USER")
    db.commit()


def disconnect(db, ctx):
    require(ctx, "integrations")
    from app.models.entities import Agency, CollectionTask

    db.scalar(select(Agency).where(Agency.id == ctx.agency_id).with_for_update())
    repo = TenantRepository(db, ctx.agency_id)
    if db.scalar(
        repo.query(CollectionTask).where(
            CollectionTask.status.in_(["APPROVED", "SENDING", "SEND_UNCERTAIN"])
        )
    ):
        raise AppError("COLLECTION_IN_FLIGHT", "Resolve approved sends before disconnecting", 409)
    integration = db.scalar(repo.query(Integration).where(Integration.provider == "GMAIL"))
    if integration:
        # Remove access locally even when Google's revoke endpoint is unavailable.
        token = decrypt(integration.encrypted_refresh_token)
        integration.status = "DISCONNECTED"
        integration.encrypted_access_token = integration.encrypted_refresh_token = ""
        audit(db, ctx.agency_id, "INTEGRATION_DISCONNECTED", integration, ctx.user_id, "USER")
        db.commit()
        try:
            httpx.post("https://oauth2.googleapis.com/revoke", data={"token": token}, timeout=10)
        except httpx.HTTPError:
            pass
