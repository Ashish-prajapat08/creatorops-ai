import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record):
        fields = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key in [
            "event",
            "agency_id",
            "entity_id",
            "request_id",
            "job_id",
            "code",
            "status",
            "duration_ms",
        ]:
            if hasattr(record, key):
                fields[key] = getattr(record, key)
        return json.dumps(fields)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("creatorops")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
