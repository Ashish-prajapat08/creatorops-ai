import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sentry_sdk
from openai import APIConnectionError, APIStatusError
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.integrations.gmail.client import utc
from app.models.entities import Agency, CollectionTask, Job
from app.models.operations import EmailAnalysis, EmailSync
from app.repositories.tenant import TenantRepository
from app.services.audit import audit
from app.services.collection_execution import generate_draft, reconcile_send, send_approved
from app.services.email_intelligence import classify_message, scan_promises
from app.services.email_sync import poll_agency, sync_invoice
from app.services.finance import scan_agency
from app.workers.celery_app import celery

logger = logging.getLogger("creatorops")


@celery.task(name="creatorops.scan")
def scan():
    with SessionLocal() as db:
        # Global enumerator only resolves tenants; business queries remain scoped.
        for agency in db.scalars(select(Agency)).all():
            scan_agency(db, agency)
            scan_promises(db, agency)


@celery.task(name="creatorops.dispatch")
def dispatch():
    with SessionLocal() as db:
        now = datetime.now(UTC)
        jobs = db.scalars(
            select(Job)
            .where(Job.status.in_(["PENDING", "QUEUED", "RUNNING"]), Job.available_at <= now)
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for job in jobs:
            if job.status == "RUNNING":
                if not job.started_at or utc(job.started_at) > now - timedelta(minutes=6):
                    continue
                task = None
                if job.kind in {"DRAFT", "SEND", "RECONCILE"}:
                    task = TenantRepository(db, job.agency_id).get(
                        CollectionTask, job.entity_id, lock=True
                    )
                if job.kind == "SEND" and task.status == "SENDING":
                    task.status, task.error_code = "SEND_UNCERTAIN", "WORKER_INTERRUPTED"
                    job.status = "FAILED"
                    audit(db, job.agency_id, "EMAIL_SEND_UNCERTAIN", task)
                    continue
                job.status = "PENDING"
            if job.status == "QUEUED" and utc(job.updated_at) > now - timedelta(seconds=60):
                continue
            execute.delay(str(job.agency_id), str(job.id))
            job.status = "QUEUED"
            job.updated_at = now
        db.commit()


def transient(exc):
    return (
        isinstance(exc, APIConnectionError)
        or (isinstance(exc, APIStatusError) and exc.status_code in {429, 500, 502, 503, 504})
        or (isinstance(exc, AppError) and exc.status == 503 and exc.code != "AI_NOT_CONFIGURED")
    )


@celery.task(name="creatorops.execute")
def execute(agency_id, job_id):
    agency_id, job_id = UUID(agency_id), UUID(job_id)
    with SessionLocal() as db:
        repo = TenantRepository(db, agency_id)
        job = repo.get(Job, job_id, lock=True)
        if job.status not in {"PENDING", "QUEUED"}:
            return
        job.status, job.started_at = "RUNNING", datetime.now(UTC)
        job.attempts += 1
        db.commit()
        try:
            {
                "DRAFT": generate_draft,
                "SEND": send_approved,
                "RECONCILE": reconcile_send,
                "CLASSIFY": classify_message,
                "SYNC_EMAIL": sync_invoice,
            }[job.kind](db, agency_id, job.entity_id)
            job = repo.get(Job, job_id, lock=True)
            job.status = "DONE"
            db.commit()
        except Exception as exc:
            db.rollback()
            sentry_sdk.capture_exception(exc)
            job = repo.get(Job, job_id, lock=True)
            if job.kind == "CLASSIFY":
                task = repo.get(EmailAnalysis, job.entity_id, lock=True)
            elif job.kind == "SYNC_EMAIL":
                task = db.scalar(
                    repo.query(EmailSync)
                    .where(EmailSync.invoice_id == job.entity_id)
                    .with_for_update()
                )
            else:
                task = repo.get(CollectionTask, job.entity_id, lock=True)
            code = exc.code if isinstance(exc, AppError) else "WORKFLOW_FAILED"
            job.error_code = code
            # Once Gmail was invoked, retries can ONLY reconcile, never resend.
            if task.status == "SEND_UNCERTAIN":
                job.status = "FAILED"
            elif transient(exc) and job.attempts < 4:
                job.status, job.available_at = (
                    "PENDING",
                    datetime.now(UTC) + timedelta(seconds=5 * 2**job.attempts),
                )
            else:
                job.status = "FAILED"
                if task.status in {"DRAFTING", "APPROVED", "PROCESSING", "RUNNING"}:
                    task.status, task.error_code = "FAILED", code
                audit(db, agency_id, "WORKFLOW_FAILED", task, details={"code": code})
            db.commit()
            logger.error(
                "workflow_failed",
                extra={
                    "event": "workflow_failed",
                    "agency_id": str(agency_id),
                    "job_id": str(job_id),
                    "code": code,
                },
            )


@celery.task(name="creatorops.poll_email")
def poll_email():
    with SessionLocal() as db:
        for agency in db.scalars(select(Agency)).all():
            poll_agency(db, agency)
