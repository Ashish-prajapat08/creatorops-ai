import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://creatorops:creatorops@localhost:55432/creatorops_test"
)
os.environ["ENVIRONMENT"] = "test"
os.environ["TEST_MODE"] = "true"
os.environ.setdefault("TEST_AUTH_SECRET", "test-only-signing-secret-at-least-32-characters")

import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from app.core.config import settings  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.entities import Job  # noqa: E402
from app.workers.tasks import execute  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    if not engine.url.database.endswith("_test"):
        raise RuntimeError("Tests require a dedicated database ending in _test")
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE " + ",".join(f'"{table}"' for table in Base.metadata.tables) + " CASCADE"
            )
        )
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def user_headers(email="owner@example.com", name="Agency Owner"):
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "email": email,
            "name": name,
            "aud": "creatorops-test",
            "iss": "creatorops-test",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings().test_auth_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def workspace(client, email="owner@example.com"):
    headers = user_headers(email)
    response = client.post(
        "/api/v1/agencies",
        headers=headers,
        json={"name": "Acme Creator Management", "timezone": "Asia/Kolkata"},
    )
    assert response.status_code == 201, response.text
    headers["X-Agency-ID"] = response.json()["data"]["id"]
    return headers


def records(
    client, headers, number="INV-1001", amount="10000.00", currency="USD", due=None, status="SENT"
):
    today = datetime.now(UTC).date()
    brand = client.post(
        "/api/v1/brands",
        headers=headers,
        json={"name": "Nike", "contact_email": "finance@nike.example"},
    ).json()["data"]
    creator = client.post(
        "/api/v1/creators",
        headers=headers,
        json={"name": "Rahul Sharma", "email": "rahul@example.com"},
    ).json()["data"]
    campaign_response = client.post(
        "/api/v1/campaigns",
        headers=headers,
        json={
            "name": "Nike Summer Campaign",
            "brand_id": brand["id"],
            "creator_id": creator["id"],
            "deal_value": amount,
            "currency": currency,
            "start_date": (today - timedelta(days=40)).isoformat(),
            "end_date": today.isoformat(),
        },
    )
    assert campaign_response.status_code == 201, campaign_response.text
    campaign = campaign_response.json()["data"]
    response = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "invoice_number": number,
            "brand_id": brand["id"],
            "campaign_id": campaign["id"],
            "amount": amount,
            "currency": currency,
            "issue_date": (today - timedelta(days=30)).isoformat(),
            "due_date": (due or today - timedelta(days=9)).isoformat(),
            "status": status,
        },
    )
    assert response.status_code == 201, response.text
    return brand, creator, campaign, response.json()["data"]


def draft_task(client, headers):
    response = client.post("/api/v1/collections/scan", headers=headers)
    assert response.status_code == 200, response.text
    task = client.get("/api/v1/collections/tasks", headers=headers).json()["data"][0]
    response = client.post(f"/api/v1/collections/tasks/{task['id']}/draft", headers=headers)
    assert response.status_code == 202, response.text
    drain_jobs()
    task = client.get(f"/api/v1/collections/tasks/{task['id']}", headers=headers).json()["data"]
    assert task["status"] == "DRAFTED", task
    return task


def drain_jobs():
    from sqlalchemy import select

    with SessionLocal() as db:
        jobs = db.scalars(select(Job).where(Job.status.in_(["PENDING", "QUEUED"]))).all()
        ids = [(str(job.agency_id), str(job.id)) for job in jobs]
    for agency_id, job_id in ids:
        execute(agency_id, job_id)
