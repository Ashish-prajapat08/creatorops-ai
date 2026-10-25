from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.agents.email_intelligence import EmailModel, TestEmailModel, validate_insight
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import require, require_current
from app.models.entities import Agency, Brand, EmailMessage, EmailThread, Invoice, Job
from app.models.operations import EmailAnalysis, PaymentPromise
from app.repositories.tenant import TenantRepository
from app.services.audit import audit
from app.services.balances import balance
from app.services.finance import create_stage, today_for


def queue_messages(db, agency_id, invoice_id):
    repo = TenantRepository(db, agency_id)
    messages = db.scalars(
        repo.query(EmailMessage)
        .join(
            EmailThread,
            (EmailMessage.thread_id == EmailThread.id) & (EmailThread.agency_id == agency_id),
        )
        .where(EmailThread.invoice_id == invoice_id, EmailMessage.direction == "INBOUND")
    ).all()
    count = 0
    for message in messages:
        if not db.scalar(repo.query(EmailAnalysis).where(EmailAnalysis.message_id == message.id)):
            analysis = EmailAnalysis(
                agency_id=agency_id, message_id=message.id, invoice_id=invoice_id
            )
            db.add(analysis)
            db.flush()
            db.add(Job(agency_id=agency_id, kind="CLASSIFY", entity_id=analysis.id))
            audit(
                db,
                agency_id,
                "EMAIL_CLASSIFICATION_QUEUED",
                analysis,
                details={"message_id": str(message.id)},
            )
            count += 1
    return count


def update_promise(db, repo, analysis, output, accepted):
    promise = db.scalar(repo.query(PaymentPromise).where(PaymentPromise.analysis_id == analysis.id))
    if output["classification"] != "PAYMENT_PROMISED" or analysis.status == "REJECTED":
        if promise:
            promise.status = "REJECTED" if analysis.status == "REJECTED" else "SUPERSEDED"
        return
    if not promise:
        promise = PaymentPromise(
            agency_id=repo.agency_id,
            invoice_id=analysis.invoice_id,
            analysis_id=analysis.id,
            source_message_id=analysis.message_id,
        )
        db.add(promise)
    value = output.get("promised_date")
    from datetime import date

    promise.promised_date = date.fromisoformat(value) if isinstance(value, str) else value
    promise.date_status = output["date_status"]
    promise.status = "CLAIMED" if accepted else "REVIEW_REQUIRED"
    promise.evidence = next(
        (e["quote"] for e in output.get("evidence", []) if e["field"] == "classification"),
        "Reviewed sender claim",
    )
    db.flush()
    audit(
        db,
        repo.agency_id,
        "PAYMENT_PROMISE_RECORDED",
        promise,
        details={
            "source_message_id": str(analysis.message_id),
            "date_status": promise.date_status,
            "promised_date": str(promise.promised_date) if promise.promised_date else None,
            "status": promise.status,
        },
    )


def classify_message(db, agency_id, analysis_id):
    repo = TenantRepository(db, agency_id)
    db.scalar(select(Agency).where(Agency.id == agency_id).with_for_update())
    analysis = repo.get(EmailAnalysis, analysis_id, lock=True)
    if analysis.status not in {"PENDING", "PROCESSING"}:
        db.rollback()
        return
    message = repo.get(EmailMessage, analysis.message_id)
    thread = repo.get(EmailThread, message.thread_id)
    if message.direction != "INBOUND" or thread.invoice_id != analysis.invoice_id:
        raise AppError(
            "INVALID_EMAIL_SOURCE", "Only relevant inbound replies may be classified", 422
        )
    invoice = repo.get(Invoice, analysis.invoice_id)
    revision = analysis.revision
    analysis.status = "PROCESSING"
    db.commit()
    context = {
        "brand_name": repo.get(Brand, invoice.brand_id).name,
        "body": message.body_text,
        "subject": message.subject,
        "invoice_number": invoice.invoice_number,
        "currency": invoice.currency,
    }
    raw = (TestEmailModel() if settings().test_mode else EmailModel()).generate(context)
    insight, reasons = validate_insight(raw, context)
    db.scalar(select(Agency).where(Agency.id == agency_id).with_for_update())
    analysis = repo.get(EmailAnalysis, analysis_id, lock=True)
    if analysis.revision != revision:
        raise AppError("STALE_CLASSIFICATION", "Classification changed during processing", 409)
    if analysis.review_decision:
        reasons.append("REPROCESSED_REQUIRES_REVIEW")
    analysis.model_output = insight.model_dump(mode="json")
    analysis.classification, analysis.confidence = (
        insight.classification,
        Decimal(str(insight.confidence)),
    )
    analysis.model = "TEST" if settings().test_mode else settings().ai_model
    analysis.review_reasons = reasons
    analysis.status, analysis.error_code = ("REVIEW" if reasons else "ACCEPTED"), None
    analysis.revision += 1
    update_promise(db, repo, analysis, analysis.model_output, not reasons)
    audit(
        db,
        agency_id,
        "EMAIL_CLASSIFIED",
        analysis,
        actor_type="AI",
        details={
            "message_id": str(message.id),
            "classification": insight.classification,
            "status": analysis.status,
            "schema_version": analysis.schema_version,
        },
    )
    db.commit()


def review(db, ctx, analysis_id, data):
    require(ctx, "email_review")
    repo = TenantRepository(db, ctx.agency_id)
    db.scalar(select(Agency).where(Agency.id == ctx.agency_id).with_for_update())
    require_current(db, ctx, "email_review")
    analysis = repo.get(EmailAnalysis, analysis_id, lock=True)
    if analysis.revision != data.revision or analysis.status not in {
        "REVIEW",
        "ACCEPTED",
        "REJECTED",
    }:
        raise AppError("STALE_REVIEW", "Reload the current classification before reviewing", 409)
    output = dict(analysis.model_output or {})
    if not output:
        raise AppError("CLASSIFICATION_REQUIRED", "Process this email before review", 409)
    if data.classification:
        output["classification"] = data.classification
    if data.date_status is not None:
        output["date_status"] = data.date_status
        output["promised_date"] = data.promised_date.isoformat() if data.promised_date else None
    if data.promised_date is not None and data.date_status != "EXPLICIT":
        raise AppError(
            "DATE_REVIEW_REQUIRED", "A corrected date requires an explicit human date decision", 422
        )
    if output["date_status"] == "EXPLICIT" and not output.get("promised_date"):
        raise AppError("DATE_REQUIRED", "Supply the reviewed date", 422)
    analysis.status = "ACCEPTED" if data.decision == "ACCEPT" else "REJECTED"
    analysis.classification = output["classification"]
    analysis.reviewed_by, analysis.reviewed_at = ctx.user_id, datetime.now(UTC)
    analysis.review_decision = {**data.model_dump(mode="json"), "effective_output": output}
    analysis.revision += 1
    update_promise(db, repo, analysis, output, data.decision == "ACCEPT")
    audit(
        db,
        ctx.agency_id,
        "EMAIL_REVIEWED",
        analysis,
        ctx.user_id,
        "USER",
        {
            "decision": data.decision,
            "reason": data.reason,
            "classification": output["classification"],
            "revision": analysis.revision,
        },
    )
    db.commit()
    return analysis


def reprocess(db, ctx, analysis_id):
    require(ctx, "email_review")
    repo = TenantRepository(db, ctx.agency_id)
    db.scalar(select(Agency).where(Agency.id == ctx.agency_id).with_for_update())
    require_current(db, ctx, "email_review")
    analysis = repo.get(EmailAnalysis, analysis_id, lock=True)
    if analysis.status in {"PENDING", "PROCESSING"}:
        raise AppError("PROCESSING_IN_FLIGHT", "This message is already queued or processing", 409)
    analysis.status, analysis.error_code = "PENDING", None
    analysis.revision += 1
    promise = db.scalar(repo.query(PaymentPromise).where(PaymentPromise.analysis_id == analysis.id))
    if promise:
        promise.status = "REVIEW_REQUIRED"
    db.add(Job(agency_id=ctx.agency_id, kind="CLASSIFY", entity_id=analysis.id))
    audit(db, ctx.agency_id, "EMAIL_REPROCESS_REQUESTED", analysis, ctx.user_id, "USER")
    db.commit()
    return analysis


def scan_promises(db, agency):
    db.scalar(select(Agency).where(Agency.id == agency.id).with_for_update())
    repo, today = TenantRepository(db, agency.id), today_for(agency)
    for promise in db.scalars(
        repo.query(PaymentPromise).where(
            PaymentPromise.status.in_(["CLAIMED", "MISSED", "SETTLED"])
        )
    ).all():
        invoice = repo.get(Invoice, promise.invoice_id)
        if Decimal(balance(db, invoice)["outstanding_balance"]) == 0:
            if promise.status != "SETTLED":
                promise.status = "SETTLED"
                audit(db, agency.id, "PAYMENT_PROMISE_SETTLED", promise)
        elif (
            promise.promised_date
            and promise.promised_date < today
            and invoice.status not in {"DRAFT", "VOID", "PAID"}
        ):
            if promise.status != "MISSED":
                promise.status = "MISSED"
                audit(db, agency.id, "PAYMENT_PROMISE_MISSED", promise)
            create_stage(
                db,
                agency.id,
                invoice.id,
                f"PROMISE_MISSED:{promise.id}",
                "Review the missed payment promise and prepare a human-approved follow-up",
            )
    db.commit()
