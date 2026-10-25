from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.core.security import require
from app.models.entities import Agency, Brand, Campaign, CollectionTask, Creator, Invoice
from app.repositories.tenant import TenantRepository
from app.schemas.contracts import BrandIn, CampaignIn, CreatorIn, InvoiceIn, InvoiceStatus
from app.services.audit import audit
from app.services.finance import invoice_status, today_for

ENTITIES = {
    "brands": (Brand, BrandIn),
    "creators": (Creator, CreatorIn),
    "campaigns": (Campaign, CampaignIn),
    "invoices": (Invoice, InvoiceIn),
}


class EntityService:
    def __init__(self, db, ctx, kind):
        self.db, self.ctx, self.kind = db, ctx, kind
        self.model, self.schema = ENTITIES[kind]
        self.repo = TenantRepository(db, ctx.agency_id)

    def validate_links(self, data):
        if self.kind in {"campaigns", "invoices"}:
            self.repo.get(Brand, data.brand_id)
        if self.kind == "campaigns":
            self.repo.get(Creator, data.creator_id)
        if self.kind == "invoices":
            campaign = self.repo.get(Campaign, data.campaign_id)
            if campaign.brand_id != data.brand_id or campaign.currency != data.currency:
                raise AppError(
                    "CAMPAIGN_MISMATCH", "Invoice brand and currency must match its campaign", 422
                )

    def save(self, data, entity_id=None):
        require(self.ctx, self.kind)
        self.db.scalar(select(Agency).where(Agency.id == self.ctx.agency_id).with_for_update())
        item = self.repo.get(self.model, entity_id, lock=True) if entity_id else None
        before = self.schema.model_validate(item).model_dump(mode="json") if item else None
        if item:
            merged = self.schema.model_validate(item).model_dump()
            merged.update(data)
            data = self.schema.model_validate(merged)
        else:
            data = self.schema.model_validate(data)
        self.validate_links(data)
        if self.kind == "campaigns" and item:
            invoices = self.db.scalars(
                self.repo.query(Invoice).where(Invoice.campaign_id == item.id)
            ).all()
            if invoices and (item.brand_id != data.brand_id or item.currency != data.currency):
                raise AppError(
                    "CAMPAIGN_IN_USE",
                    "Cannot change brand or currency of an invoiced campaign",
                    409,
                )
        if self.kind == "invoices":
            if item:
                tasks = self.db.scalars(
                    self.repo.query(CollectionTask)
                    .where(CollectionTask.invoice_id == item.id)
                    .with_for_update()
                ).all()
                if item.reconciliation_managed and any(
                    getattr(item, key) != getattr(data, key)
                    for key in ["amount", "currency", "brand_id", "campaign_id", "status"]
                ):
                    raise AppError(
                        "RECONCILIATION_MANAGED",
                        "Reverse or correct allocations through reconciliation before changing financial fields",
                        409,
                    )
                for task in tasks:
                    if task.status in {"APPROVED", "SENDING", "SEND_UNCERTAIN", "DRAFTING"}:
                        raise AppError(
                            "COLLECTION_IN_FLIGHT",
                            "Resolve the in-flight collection before editing this invoice",
                            409,
                        )
                    if task.status == "DRAFTED":
                        task.status = "PENDING"
                        task.draft_revision += 1
                        audit(
                            self.db,
                            self.ctx.agency_id,
                            "COLLECTION_DRAFT_INVALIDATED",
                            task,
                            self.ctx.user_id,
                            "USER",
                        )
            agency = self.db.get(Agency, self.ctx.agency_id)
            data.status = InvoiceStatus(
                invoice_status(data.status, data.due_date, today_for(agency))
            )
        values = data.model_dump()
        if item:
            for key, value in values.items():
                setattr(item, key, value)
        else:
            item = self.model(agency_id=self.ctx.agency_id, **values)
            self.db.add(item)
        try:
            self.db.flush()
            audit(
                self.db,
                self.ctx.agency_id,
                f"{self.model.__name__.upper()}_{'UPDATED' if entity_id else 'CREATED'}",
                item,
                self.ctx.user_id,
                "USER",
                {"before": before, "after": data.model_dump(mode="json")},
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError("CONFLICT", "Duplicate value or invalid relationship", 409) from exc
        return item

    def delete(self, entity_id):
        require(self.ctx, self.kind)
        self.db.scalar(select(Agency).where(Agency.id == self.ctx.agency_id).with_for_update())
        item = self.repo.get(self.model, entity_id, lock=True)
        if self.kind == "invoices" and item.status != "DRAFT":
            raise AppError(
                "FINANCIAL_RECORD_RETAINED", "Void issued invoices to preserve their history", 409
            )
        audit(
            self.db,
            self.ctx.agency_id,
            f"{self.kind.upper()}_DELETED",
            item,
            self.ctx.user_id,
            "USER",
        )
        self.db.delete(item)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError("RESOURCE_IN_USE", "Remove related draft records first", 409) from exc
