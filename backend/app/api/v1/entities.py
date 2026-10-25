from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import create_model
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Scope, scope
from app.schemas.contracts import BrandOut, CampaignOut, CreatorOut, Envelope, InvoiceOut
from app.services.entities import ENTITIES, EntityService


def entity_router(kind, output):
    model, input_schema = ENTITIES[kind]
    patch_schema = create_model(
        f"{input_schema.__name__}Patch",
        __config__=input_schema.model_config,
        **{
            name: (
                Annotated[field.annotation | None, *field.metadata]
                if field.metadata
                else field.annotation | None,
                None,
            )
            for name, field in input_schema.model_fields.items()
        },
    )
    router = APIRouter(prefix=f"/{kind}", tags=[kind])

    def listing(
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        brand_id: UUID | None = None,
        creator_id: UUID | None = None,
        campaign_id: UUID | None = None,
        ctx: Scope = Depends(scope),
        db: Session = Depends(get_db),
    ):
        filters = {
            key: value
            for key, value in {
                "brand_id": brand_id,
                "creator_id": creator_id,
                "campaign_id": campaign_id,
            }.items()
            if value is not None
        }
        items = EntityService(db, ctx, kind).repo.list(model, offset, limit, filters)
        return {
            "data": items,
            "meta": {"offset": offset, "limit": limit, "has_more": len(items) == limit},
        }

    def create(data: input_schema, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
        return {"data": EntityService(db, ctx, kind).save(data.model_dump())}

    def get(entity_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
        return {"data": EntityService(db, ctx, kind).repo.get(model, entity_id)}

    def update(
        entity_id: UUID,
        data: patch_schema,
        ctx: Scope = Depends(scope),
        db: Session = Depends(get_db),
    ):
        return {
            "data": EntityService(db, ctx, kind).save(
                data.model_dump(exclude_unset=True), entity_id
            )
        }

    def delete(entity_id: UUID, ctx: Scope = Depends(scope), db: Session = Depends(get_db)):
        EntityService(db, ctx, kind).delete(entity_id)
        return {"data": {"deleted": True}}

    router.add_api_route("", listing, methods=["GET"], response_model=Envelope[list[output]])
    router.add_api_route(
        "", create, methods=["POST"], response_model=Envelope[output], status_code=201
    )
    router.add_api_route("/{entity_id}", get, methods=["GET"], response_model=Envelope[output])
    router.add_api_route("/{entity_id}", update, methods=["PATCH"], response_model=Envelope[output])
    router.add_api_route("/{entity_id}", delete, methods=["DELETE"], response_model=Envelope[dict])
    return router


routers = [
    entity_router(kind, out)
    for kind, out in [
        ("brands", BrandOut),
        ("creators", CreatorOut),
        ("campaigns", CampaignOut),
        ("invoices", InvoiceOut),
    ]
]
