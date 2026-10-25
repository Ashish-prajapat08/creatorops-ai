import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import SessionLocal
from app.tests.conftest import records, workspace


def test_audit_is_append_only_at_database_level(client):
    headers = workspace(client)
    records(client, headers)
    for operation in ["UPDATE audit_logs SET action='TAMPERED'", "DELETE FROM audit_logs"]:
        with SessionLocal() as db, pytest.raises(DBAPIError):
            db.execute(text(operation))
            db.commit()


def test_financial_edit_history_keeps_previous_truth(client):
    headers = workspace(client)
    _, _, _, invoice = records(client, headers)
    assert (
        client.patch(
            f"/api/v1/invoices/{invoice['id']}", headers=headers, json={"amount": "12000.00"}
        ).status_code
        == 200
    )
    events = client.get(f"/api/v1/invoices/{invoice['id']}/history", headers=headers).json()[
        "data"
    ]["audit"]
    edit = next(event for event in events if event["action"] == "INVOICE_UPDATED")
    assert edit["details"]["before"]["amount"] == "10000.00"
    assert edit["details"]["after"]["amount"] == "12000.00"
