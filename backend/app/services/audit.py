import logging

from app.models.entities import AuditLog

logger = logging.getLogger("creatorops")


def audit(db, agency_id, action, entity, actor_id=None, actor_type="SYSTEM", details=None):
    db.add(
        AuditLog(
            agency_id=agency_id,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id else None,
            action=action,
            entity_type=entity.__tablename__,
            entity_id=entity.id,
            details=details or {},
        )
    )
    logger.info(
        "business_action",
        extra={"event": action, "agency_id": str(agency_id), "entity_id": str(entity.id)},
    )
