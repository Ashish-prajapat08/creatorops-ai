import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.core.security import require
from app.models.entities import Agency, Membership, User
from app.repositories.tenant import TenantRepository
from app.services.audit import audit


def list_agencies(db, user):
    rows = db.execute(
        select(Agency, Membership.role)
        .join(Membership, Membership.agency_id == Agency.id)
        .where(Membership.user_id == user.id)
    ).all()
    return [
        {
            **{
                key: getattr(agency, key)
                for key in [
                    "id",
                    "name",
                    "slug",
                    "default_currency",
                    "timezone",
                    "created_at",
                    "updated_at",
                ]
            },
            "role": role,
        }
        for agency, role in rows
    ]


def create_agency(db, user, data):
    slug = re.sub(r"[^a-z0-9]+", "-", data.name.lower()).strip("-")[:130] or "agency"
    agency = Agency(**data.model_dump(), slug=f"{slug}-{uuid.uuid4().hex[:8]}")
    db.add(agency)
    db.flush()
    db.add(Membership(agency_id=agency.id, user_id=user.id, role="OWNER"))
    audit(db, agency.id, "AGENCY_CREATED", agency, user.id, "USER")
    db.commit()
    return next(a for a in list_agencies(db, user) if a["id"] == agency.id)


def members(db, ctx):
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.agency_id == ctx.agency_id)
    ).all()
    return [
        {"id": m.id, "user_id": u.id, "name": u.name, "email": u.email, "role": m.role}
        for m, u in rows
    ]


def add_member(db, ctx, data):
    require(ctx, "members")
    if data.role == "OWNER" and ctx.role != "OWNER":
        raise AppError("FORBIDDEN", "Only an owner can grant ownership", 403)
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    if not user:
        raise AppError("USER_NOT_FOUND", "Ask this person to sign up and access the app first", 404)
    member = Membership(agency_id=ctx.agency_id, user_id=user.id, role=data.role)
    db.add(member)
    try:
        db.flush()
        audit(db, ctx.agency_id, "MEMBER_ADDED", member, ctx.user_id, "USER", {"role": data.role})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("ALREADY_MEMBER", "This user is already a member", 409) from exc
    return next(m for m in members(db, ctx) if m["id"] == member.id)


def remove_member(db, ctx, member_id):
    require(ctx, "members")
    # Agency lock serializes owner changes; an agency must retain an owner.
    db.scalar(select(Agency).where(Agency.id == ctx.agency_id).with_for_update())
    member = TenantRepository(db, ctx.agency_id).get(Membership, member_id, lock=True)
    if member.role == "OWNER":
        if ctx.role != "OWNER":
            raise AppError("FORBIDDEN", "Only owners can remove an owner", 403)
        owners = db.scalars(
            select(Membership).where(
                Membership.agency_id == ctx.agency_id, Membership.role == "OWNER"
            )
        ).all()
        if len(owners) == 1:
            raise AppError("LAST_OWNER", "A workspace must retain an owner", 409)
    audit(db, ctx.agency_id, "MEMBER_REMOVED", member, ctx.user_id, "USER")
    db.delete(member)
    db.commit()
