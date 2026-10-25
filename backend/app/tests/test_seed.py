from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import User
from app.seed import seed
from app.tests.conftest import workspace


def test_seed_is_idempotent_and_has_realistic_status_mix(client):
    headers = workspace(client)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        agency = seed(db, user)
        seed(db, user)
        headers["X-Agency-ID"] = str(agency.id)
    invoices = client.get("/api/v1/invoices", headers=headers).json()["data"]
    assert len(invoices) == 6
    assert len([i for i in invoices if i["status"] == "PAID"]) == 1
    assert len([i for i in invoices if i["status"] == "SENT"]) == 2
    assert len([i for i in invoices if i["status"] == "OVERDUE"]) == 3
    assert len(client.get("/api/v1/collections/tasks", headers=headers).json()["data"]) == 5
