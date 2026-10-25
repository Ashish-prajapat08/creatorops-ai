from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.entities import Agency, CollectionTask, EmailMessage, Job
from app.models.operations import PaymentPromise
from app.services.email_intelligence import scan_promises
from app.services.finance import today_for
from app.tests.conftest import drain_jobs, records, workspace
from app.tests.test_email_intelligence import sync_reply


def test_due_soon_and_overdue_are_separate_idempotent_stages(client):
    headers = workspace(client)
    with SessionLocal() as db:
        today = today_for(db.get(Agency, UUID(headers["X-Agency-ID"])))
    _, _, _, invoice = records(client, headers, due=today + timedelta(days=2))
    for _ in range(2):
        client.post("/api/v1/collections/scan", headers=headers)
    rows = client.get("/api/v1/collections/tasks", headers=headers).json()["data"]
    assert len(rows) == 1 and rows[0]["workflow_key"] == "DUE_SOON"
    assert (
        client.post(f"/api/v1/collections/tasks/{rows[0]['id']}/draft", headers=headers).status_code
        == 202
    )
    drain_jobs()
    row = client.get(f"/api/v1/collections/tasks/{rows[0]['id']}", headers=headers).json()["data"]
    assert row["status"] == "DRAFTED"
    assert (
        client.patch(
            f"/api/v1/invoices/{invoice['id']}",
            headers=headers,
            json={"due_date": (today - timedelta(days=1)).isoformat()},
        ).status_code
        == 200
    )
    for _ in range(2):
        client.post("/api/v1/collections/scan", headers=headers)
    rows = client.get("/api/v1/collections/tasks", headers=headers).json()["data"]
    assert {r["workflow_key"]: r["status"] for r in rows} == {
        "DUE_SOON": "COMPLETED",
        "OVERDUE": "PENDING",
    }


def test_classification_transient_retry_and_permanent_failure(client, monkeypatch):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    client.post(f"/api/v1/invoices/{invoice['id']}/sync-email", headers=headers)
    drain_jobs()
    from app.agents.email_intelligence import TestEmailModel

    original = TestEmailModel.generate
    attempts = []

    def flaky(self, context):
        attempts.append(1)
        if len(attempts) == 1:
            raise AppError("GMAIL_UNAVAILABLE", "Transient upstream outage", 503)
        return original(self, context)

    monkeypatch.setattr(TestEmailModel, "generate", flaky)
    drain_jobs()
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.kind == "CLASSIFY"))
        assert job.status == "PENDING" and job.attempts == 1
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    drain_jobs()
    row = client.get("/api/v1/email-intelligence", headers=headers).json()["data"][0]
    assert row["status"] == "REVIEW" and len(attempts) == 2

    def malformed(self, context):
        return {"classification": "MARK_PAID"}

    monkeypatch.setattr(TestEmailModel, "generate", malformed)
    client.post(f"/api/v1/email-intelligence/{row['id']}/reprocess", headers=headers)
    drain_jobs()
    row = client.get(f"/api/v1/email-intelligence/{row['id']}", headers=headers).json()["data"]
    assert row["status"] == "FAILED"


def test_outbound_and_irrelevant_messages_are_not_classified(client, monkeypatch):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    from app.integrations.gmail.client import TestGmailClient

    original = TestGmailClient.context

    def unrelated(self, inv, brand, after=None):
        message = original(self, inv, brand)[0]
        return [
            {**message, "direction": "OUTBOUND"},
            {**message, "message_id": "irrelevant", "subject": "Different invoice INV-OTHER"},
        ]

    monkeypatch.setattr(TestGmailClient, "context", unrelated)
    client.post(f"/api/v1/invoices/{invoice['id']}/sync-email", headers=headers)
    drain_jobs()
    assert client.get("/api/v1/email-intelligence", headers=headers).json()["data"] == []
    status = client.get("/api/v1/email-sync", headers=headers).json()["data"][0]
    assert status["last_success_at"] and status["checkpoint_at"]


def test_missing_date_persisted_and_rejected_promise_cannot_trigger_followup(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    row = sync_reply(client, headers, invoice)
    with SessionLocal() as db:
        message = db.get(EmailMessage, UUID(row["message_id"]))
        message.body_text = "We will pay after internal approval."
        db.commit()
    client.post(f"/api/v1/email-intelligence/{row['id']}/reprocess", headers=headers)
    drain_jobs()
    row = client.get(f"/api/v1/email-intelligence/{row['id']}", headers=headers).json()["data"]
    assert row["model_output"]["date_status"] == "MISSING"
    result = client.post(
        f"/api/v1/email-intelligence/{row['id']}/review",
        headers=headers,
        json={
            "revision": row["revision"],
            "decision": "REJECT",
            "reason": "This was not an actionable payment promise",
        },
    )
    assert result.status_code == 200
    with SessionLocal() as db:
        agency = db.get(Agency, UUID(headers["X-Agency-ID"]))
        scan_promises(db, agency)
        promise = db.scalar(select(PaymentPromise))
        assert promise.status == "REJECTED"
        assert (
            db.scalar(
                select(CollectionTask).where(CollectionTask.workflow_key.like("PROMISE_MISSED:%"))
            )
            is None
        )
