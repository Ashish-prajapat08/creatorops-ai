import sentry_sdk

from app.core.config import settings


def redact_event(event, hint):
    """Request payloads, query strings, email bodies and credentials never enter Sentry."""
    event.pop("request", None)
    event.pop("user", None)
    event.pop("breadcrumbs", None)
    exception = event.get("exception", {})
    for value in exception.get("values", []):
        value["value"] = "Exception details redacted; correlate by request/job ID"
        for frame in value.get("stacktrace", {}).get("frames", []):
            frame.pop("vars", None)
    return event


def initialize():
    cfg = settings()
    if cfg.sentry_dsn:
        sentry_sdk.init(
            dsn=cfg.sentry_dsn,
            environment=cfg.environment,
            send_default_pii=False,
            max_request_body_size="never",
            include_local_variables=False,
            before_send=redact_event,
        )
