from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Scope, current_user, scope
from app.models.entities import User
from app.schemas.contracts import AgencyIn, AgencyOut, Envelope, MemberIn, MemberOut, UserOut
from app.services import workspace

router = APIRouter(tags=["workspace"])


@router.get("/auth/me", response_model=Envelope[UserOut])
def me(user: User = Depends(current_user)):
    return {"data": user}


@router.get("/agencies", response_model=Envelope[list[AgencyOut]])
def agencies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"data": workspace.list_agencies(db, user)}


@router.post("/agencies", response_model=Envelope[AgencyOut], status_code=201)
def create(data: AgencyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"data": workspace.create_agency(db, user, data)}


@router.get("/agencies/members", response_model=Envelope[list[MemberOut]])
def members(ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": workspace.members(db, ctx)}


@router.post("/agencies/members", response_model=Envelope[MemberOut], status_code=201)
def member(data: MemberIn, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    return {"data": workspace.add_member(db, ctx, data)}


@router.delete("/agencies/members/{member_id}", response_model=Envelope[dict])
def remove(member_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
    workspace.remove_member(db, ctx, member_id)
    return {"data": {"deleted": True}}
