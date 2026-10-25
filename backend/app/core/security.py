from dataclasses import dataclass
from uuid import UUID

import httpx
import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models.entities import Membership, User

bearer = HTTPBearer(auto_error=False)


def cipher():
    if not settings().encryption_key:
        raise AppError("CONFIGURATION_REQUIRED", "Token encryption is not configured", 503)
    return Fernet(settings().encryption_key.encode())


def encrypt(value: str):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str):
    return cipher().decrypt(value.encode()).decode()


def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AppError("UNAUTHORIZED", "Please sign in", 401)
    cfg = settings()
    if cfg.test_mode:
        try:
            claims = jwt.decode(
                credentials.credentials,
                cfg.test_auth_secret,
                algorithms=["HS256"],
                audience="creatorops-test",
                issuer="creatorops-test",
                options={"require": ["exp", "sub", "email"]},
            )
            return {
                "id": claims["sub"],
                "email": claims["email"],
                "user_metadata": {"name": claims.get("name", "Test user")},
            }
        except jwt.InvalidTokenError as exc:
            raise AppError("UNAUTHORIZED", "Invalid session", 401) from exc
    if not cfg.supabase_url or not cfg.supabase_publishable_key:
        raise AppError("AUTH_NOT_CONFIGURED", "Configure Supabase Auth to sign in", 503)
    try:
        response = httpx.get(
            f"{cfg.supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {credentials.credentials}",
                "apikey": cfg.supabase_publishable_key,
            },
            timeout=10,
        )
        if response.status_code != 200:
            raise AppError("UNAUTHORIZED", "Invalid or expired session", 401)
        data = response.json()
        if not data.get("email_confirmed_at"):
            raise AppError("EMAIL_NOT_VERIFIED", "Verify your email before continuing", 403)
        return data
    except httpx.HTTPError as exc:
        raise AppError(
            "AUTH_UNAVAILABLE", "Authentication is temporarily unavailable", 503
        ) from exc


def current_user(claims: dict = Depends(identity), db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.auth_provider_id == claims["id"]))
    if not user:
        email = claims["email"].lower()
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            if existing.auth_provider_id == claims["id"]:
                return existing
            raise AppError(
                "IDENTITY_CONFLICT", "Contact support to resolve your account identity", 409
            )
        user = User(
            auth_provider_id=claims["id"],
            email=email,
            name=claims.get("user_metadata", {}).get("name", email)[:160],
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            user = db.scalar(select(User).where(User.auth_provider_id == claims["id"]))
            if not user:
                raise AppError(
                    "IDENTITY_CONFLICT", "Contact support to resolve your account identity", 409
                ) from None
    return user


@dataclass(frozen=True)
class Scope:
    agency_id: UUID
    user_id: UUID
    role: str


def scope(
    x_agency_id: UUID = Header(), user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Scope:
    membership = db.scalar(
        select(Membership).where(Membership.agency_id == x_agency_id, Membership.user_id == user.id)
    )
    if not membership:
        raise AppError("FORBIDDEN", "Agency membership required", 403)
    return Scope(x_agency_id, user.id, membership.role)


PERMISSIONS = {
    "email_review": {"OWNER", "ADMIN", "FINANCE", "OPS"},
    "transactions": {"OWNER", "ADMIN"},
    "reconciliation": {"OWNER", "ADMIN", "FINANCE"},
    "brands": {"OWNER", "ADMIN", "FINANCE"},
    "creators": {"OWNER", "ADMIN", "OPS"},
    "campaigns": {"OWNER", "ADMIN", "OPS"},
    "invoices": {"OWNER", "ADMIN", "FINANCE"},
    "draft": {"OWNER", "ADMIN", "FINANCE", "OPS"},
    "approve": {"OWNER", "ADMIN", "FINANCE"},
    "members": {"OWNER", "ADMIN"},
    "integrations": {"OWNER", "ADMIN"},
}


def require(ctx: Scope, permission: str):
    if ctx.role not in PERMISSIONS[permission]:
        raise AppError("FORBIDDEN", "Your role cannot perform this action", 403)


def require_current(db: Session, ctx: Scope, permission: str):
    """Revalidate membership after acquiring the agency mutation lock."""
    membership = db.scalar(
        select(Membership)
        .where(Membership.agency_id == ctx.agency_id, Membership.user_id == ctx.user_id)
        .execution_options(populate_existing=True)
    )
    if not membership or membership.role not in PERMISSIONS[permission]:
        raise AppError("FORBIDDEN", "Your workspace permission was revoked", 403)
