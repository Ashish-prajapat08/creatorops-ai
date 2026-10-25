from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError


class TenantRepository:
    def __init__(self, db: Session, agency_id: UUID):
        self.db, self.agency_id = db, agency_id

    def query(self, model):
        return select(model).where(model.agency_id == self.agency_id)

    def get(self, model, entity_id: UUID, lock: bool = False):
        query = self.query(model).where(model.id == entity_id)
        if lock:
            query = query.with_for_update()
        item = self.db.scalar(query.execution_options(populate_existing=True))
        if not item:
            raise AppError("NOT_FOUND", "Resource not found in this workspace", 404)
        return item

    def list(self, model, offset=0, limit=50, filters=None):
        query = self.query(model)
        for key, value in (filters or {}).items():
            if not hasattr(model, key):
                raise AppError("INVALID_FILTER", "This filter does not apply to the resource", 422)
            query = query.where(getattr(model, key) == value)
        return list(
            self.db.scalars(
                query.order_by(model.created_at.desc(), model.id).offset(offset).limit(limit)
            )
        )
