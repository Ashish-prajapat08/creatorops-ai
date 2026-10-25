"""Verify V0 -> V1/V2 migration on preserved fixtures in an isolated PostgreSQL schema."""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
url = make_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://creatorops:creatorops@localhost:55432/creatorops_test",
    )
)
if not url.database.endswith("_test"):
    raise RuntimeError("Migration verification requires a dedicated _test database")
schema = "upgrade_check_" + uuid4().hex
engine = create_engine(url)
with engine.begin() as db:
    db.execute(text(f'CREATE SCHEMA "{schema}"'))
scoped_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
env = {
    **os.environ,
    "DATABASE_URL": scoped_url.render_as_string(hide_password=False),
    "ENVIRONMENT": "test",
    "TEST_MODE": "false",
}
scoped = create_engine(scoped_url)


def migrate(target):
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=root / "backend",
        env=env,
        check=True,
    )


try:
    migrate("48c6a780fd22")
    ids = {
        name: uuid4()
        for name in ["agency", "brand", "creator", "campaign", "invoice", "task"]
    }
    common = {"agency": ids["agency"], "created": datetime.now(UTC)}
    rows = [
        (
            "agencies",
            {
                "id": ids["agency"],
                "name": "Preserved agency",
                "slug": "preserved",
                "default_currency": "USD",
                "timezone": "Asia/Kolkata",
            },
        ),
        (
            "brands",
            {
                "id": ids["brand"],
                "agency_id": ids["agency"],
                "name": "Brand",
                "contact_name": "Finance",
                "contact_email": "finance@example.com",
                "payment_terms_days": 30,
                "notes": "",
            },
        ),
        (
            "creators",
            {
                "id": ids["creator"],
                "agency_id": ids["agency"],
                "name": "Creator",
                "email": "creator@example.com",
                "default_payout_percentage": "80.00",
                "notes": "",
            },
        ),
        (
            "campaigns",
            {
                "id": ids["campaign"],
                "agency_id": ids["agency"],
                "brand_id": ids["brand"],
                "creator_id": ids["creator"],
                "name": "Campaign",
                "description": "",
                "deal_value": "100.00",
                "currency": "USD",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "status": "ACTIVE",
            },
        ),
        (
            "invoices",
            {
                "id": ids["invoice"],
                "agency_id": ids["agency"],
                "brand_id": ids["brand"],
                "campaign_id": ids["campaign"],
                "invoice_number": "PRESERVED-001",
                "amount": "100.00",
                "currency": "USD",
                "issue_date": "2026-01-01",
                "due_date": "2026-02-01",
                "status": "OVERDUE",
                "description": "Preserve me",
            },
        ),
        (
            "collection_tasks",
            {
                "id": ids["task"],
                "agency_id": ids["agency"],
                "invoice_id": ids["invoice"],
                "status": "PENDING",
                "priority": "NORMAL",
                "task_type": "PAYMENT_FOLLOW_UP",
                "recommended_action": "Review",
                "draft_revision": 0,
            },
        ),
    ]
    with scoped.begin() as db:
        for table, values in rows:
            values.update(created_at=common["created"], updated_at=common["created"])
            db.execute(
                text(
                    f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(':' + key for key in values)})"
                ),
                values,
            )
    migrate("head")
    with scoped.connect() as db:
        invoice = db.execute(
            text(
                "SELECT invoice_number, amount, reconciliation_managed FROM invoices WHERE id=:id"
            ),
            {"id": ids["invoice"]},
        ).one()
        task = db.execute(
            text("SELECT workflow_key FROM collection_tasks WHERE id=:id"),
            {"id": ids["task"]},
        ).scalar_one()
        assert (
            invoice.invoice_number == "PRESERVED-001"
            and str(invoice.amount) == "100.00"
            and not invoice.reconciliation_managed
        )
        assert task == "OVERDUE"
    print("V0 invoice and collection task preserved through additive V1/V2 migration")
finally:
    scoped.dispose()
    with engine.begin() as db:
        db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()
