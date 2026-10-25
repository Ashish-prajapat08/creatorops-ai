from app.tests.conftest import draft_task, drain_jobs, records, user_headers, workspace


def test_revoked_finance_approval_cannot_send(client, monkeypatch):
    owner = workspace(client)
    records(client, owner)
    task = draft_task(client, owner)
    finance = user_headers("finance@example.com")
    client.get("/api/v1/auth/me", headers=finance)
    member = client.post(
        "/api/v1/agencies/members",
        headers=owner,
        json={"email": "finance@example.com", "role": "FINANCE"},
    ).json()["data"]
    finance["X-Agency-ID"] = owner["X-Agency-ID"]
    assert (
        client.post(
            f"/api/v1/collections/tasks/{task['id']}/approve",
            headers=finance,
            json={"revision": task["draft_revision"]},
        ).status_code
        == 202
    )
    assert (
        client.delete(f"/api/v1/agencies/members/{member['id']}", headers=owner).status_code == 200
    )
    from app.integrations.gmail.client import TestGmailClient

    monkeypatch.setattr(
        TestGmailClient,
        "send",
        lambda *args: (_ for _ in ()).throw(AssertionError("Revoked approval must not send")),
    )
    drain_jobs()
    current = client.get(f"/api/v1/collections/tasks/{task['id']}", headers=owner).json()["data"]
    assert current["status"] == "FAILED" and current["error_code"] == "APPROVAL_REVOKED"
