from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.entities import Agency, Invoice, Job
from app.services.finance import scan_agency
from app.tests.conftest import draft_task, drain_jobs, records, workspace
from app.workers.tasks import execute


def test_primary_workflow_and_duplicate_send(client, monkeypatch):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    task = draft_task(client, headers)
    assert "USD 10000.00" in task["draft_body"]
    assert task["context_summary"]["intent"] == "PAYMENT_PROMISE"
    assert task["recipient"] == "finance@nike.example"
    response = client.patch(
        f"/api/v1/collections/tasks/{task['id']}/draft",
        headers=headers,
        json={
            "subject": task["draft_subject"],
            "body": task["draft_body"] + "\nThank you.",
            "revision": task["draft_revision"],
        },
    )
    assert response.status_code == 200
    edited = response.json()["data"]
    assert edited["draft_revision"] == task["draft_revision"] + 1
    assert (
        client.post(
            f"/api/v1/collections/tasks/{task['id']}/approve",
            headers=headers,
            json={"revision": task["draft_revision"]},
        ).status_code
        == 409
    )
    sends = []
    from app.integrations.gmail.client import TestGmailClient

    monkeypatch.setattr(
        TestGmailClient,
        "send",
        lambda self, recipient, subject, body, message_id: (
            sends.append((recipient, subject, body)) or "gmail-123"
        ),
    )
    for _ in range(2):
        assert (
            client.post(
                f"/api/v1/collections/tasks/{task['id']}/approve",
                headers=headers,
                json={"revision": edited["draft_revision"]},
            ).status_code
            == 202
        )
    drain_jobs()
    drain_jobs()
    assert len(sends) == 1
    assert sends[0][2].endswith("Thank you.")
    sent = client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"]
    assert sent["status"] == "SENT" and sent["gmail_message_id"] == "gmail-123"
    history = client.get(f"/api/v1/invoices/{invoice['id']}/history", headers=headers).json()[
        "data"
    ]
    actions = [event["action"] for event in history["audit"]]
    for action in [
        "INVOICE_CREATED",
        "COLLECTION_TASK_CREATED",
        "COLLECTION_DRAFT_CREATED",
        "COLLECTION_DRAFT_EDITED",
        "COLLECTION_APPROVED",
        "EMAIL_SEND_INITIATED",
        "EMAIL_SENT",
    ]:
        assert action in actions
    assert (
        actions.index("COLLECTION_APPROVED")
        < actions.index("EMAIL_SEND_INITIATED")
        < actions.index("EMAIL_SENT")
    )
    assert history["invoice"]["amount"] == "10000.00"
    assert history["invoice"]["status"] == "OVERDUE"
    assert any(email["direction"] == "OUTBOUND" for email in history["emails"])


def test_overdue_scan_concurrently_idempotent(client):
    headers = workspace(client)
    records(client, headers)
    agency_id = UUID(headers["X-Agency-ID"])

    def run():
        with SessionLocal() as db:
            return scan_agency(db, db.get(Agency, agency_id))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: run(), range(4)))
    assert sum(results) == 1
    assert len(client.get("/api/v1/collections/tasks", headers=headers).json()["data"]) == 1


def test_reject_prevents_send_and_allows_redraft(client, monkeypatch):
    headers = workspace(client)
    records(client, headers)
    task = draft_task(client, headers)
    assert (
        client.post(f"/api/v1/collections/tasks/{task['id']}/reject", headers=headers).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/collections/tasks/{task['id']}/approve",
            headers=headers,
            json={"revision": task["draft_revision"]},
        ).status_code
        == 409
    )
    assert (
        client.post(f"/api/v1/collections/tasks/{task['id']}/draft", headers=headers).status_code
        == 202
    )
    drain_jobs()
    assert (
        client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"][
            "status"
        ]
        == "DRAFTED"
    )


def test_paid_invoice_invalidates_draft_and_cannot_send(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    task = draft_task(client, headers)
    assert (
        client.patch(
            f"/api/v1/invoices/{invoice['id']}", headers=headers, json={"status": "PAID"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/collections/tasks/{task['id']}/approve",
            headers=headers,
            json={"revision": task["draft_revision"]},
        ).status_code
        == 409
    )
    assert (
        client.post(f"/api/v1/collections/tasks/{task['id']}/draft", headers=headers).status_code
        == 409
    )
    client.post("/api/v1/collections/scan", headers=headers)
    assert (
        client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"][
            "status"
        ]
        == "COMPLETED"
    )


def test_approved_invoice_blocks_edits_and_reject_cancels_queued_send(client, monkeypatch):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    task = draft_task(client, headers)
    client.post(
        f"/api/v1/collections/tasks/{task['id']}/approve",
        headers=headers,
        json={"revision": task["draft_revision"]},
    )
    assert (
        client.patch(
            f"/api/v1/invoices/{invoice['id']}", headers=headers, json={"amount": "1.00"}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/collections/tasks/{task['id']}/draft",
            headers=headers,
            json={"subject": "Changed", "body": "Changed", "revision": task["draft_revision"]},
        ).status_code
        == 409
    )
    client.post(f"/api/v1/collections/tasks/{task['id']}/reject", headers=headers)
    from app.integrations.gmail.client import TestGmailClient

    monkeypatch.setattr(
        TestGmailClient,
        "send",
        lambda *args: (_ for _ in ()).throw(AssertionError("Must not send")),
    )
    drain_jobs()
    assert (
        client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"][
            "status"
        ]
        == "REJECTED"
    )


def test_uncertain_send_never_retries_and_reconciles(client, monkeypatch):
    headers = workspace(client)
    records(client, headers)
    task = draft_task(client, headers)
    from app.integrations.gmail.client import TestGmailClient

    sends = []

    def uncertain(*args):
        sends.append(1)
        raise AppError("GMAIL_UNAVAILABLE", "Response lost", 503)

    monkeypatch.setattr(TestGmailClient, "send", uncertain)
    client.post(
        f"/api/v1/collections/tasks/{task['id']}/approve",
        headers=headers,
        json={"revision": task["draft_revision"]},
    )
    drain_jobs()
    drain_jobs()
    current = client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"]
    assert current["status"] == "SEND_UNCERTAIN" and len(sends) == 1
    client.post(
        f"/api/v1/collections/tasks/{task['id']}/approve",
        headers=headers,
        json={"revision": task["draft_revision"]},
    )
    drain_jobs()
    assert len(sends) == 1
    client.post(f"/api/v1/collections/tasks/{task['id']}/reconcile", headers=headers)
    drain_jobs()
    assert (
        client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"][
            "status"
        ]
        == "SEND_UNCERTAIN"
    )
    monkeypatch.setattr(TestGmailClient, "find_sent", lambda *args: "confirmed-gmail-id")
    client.post(f"/api/v1/collections/tasks/{task['id']}/reconcile", headers=headers)
    drain_jobs()
    current = client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"]
    assert current["status"] == "SENT" and len(sends) == 1


def test_duplicate_worker_delivery_claimed_once(client, monkeypatch):
    headers = workspace(client)
    records(client, headers)
    task = draft_task(client, headers)
    client.post(
        f"/api/v1/collections/tasks/{task['id']}/approve",
        headers=headers,
        json={"revision": task["draft_revision"]},
    )
    from app.integrations.gmail.client import TestGmailClient

    sends = []
    monkeypatch.setattr(TestGmailClient, "send", lambda *args: sends.append(1) or "gmail-once")
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.kind == "SEND"))
        args = str(job.agency_id), str(job.id)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: execute(*args), range(3)))
    assert len(sends) == 1


def test_stale_send_snapshot_blocked_even_if_database_was_changed(client, monkeypatch):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    task = draft_task(client, headers)
    client.post(
        f"/api/v1/collections/tasks/{task['id']}/approve",
        headers=headers,
        json={"revision": task["draft_revision"]},
    )
    with SessionLocal() as db:
        record = db.get(Invoice, UUID(invoice["id"]))
        record.due_date += timedelta(days=1)
        db.commit()
    drain_jobs()
    current = client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"]
    assert current["status"] == "FAILED" and current["error_code"] == "STALE_APPROVAL"
