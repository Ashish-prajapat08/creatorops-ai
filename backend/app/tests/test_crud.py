from app.tests.conftest import records, workspace


def test_core_entities_crud_and_pagination(client):
    headers = workspace(client)
    brand, creator, campaign, invoice = records(client, headers, status="DRAFT")
    assert client.get("/api/v1/brands?limit=1", headers=headers).json()["meta"]["limit"] == 1
    assert client.get("/api/v1/brands?offset=1", headers=headers).json()["data"] == []
    for kind, row in [("brands", brand), ("creators", creator), ("campaigns", campaign)]:
        assert (
            client.patch(
                f"/api/v1/{kind}/{row['id']}", headers=headers, json={"name": "Updated"}
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/{kind}/{row['id']}", headers=headers).json()["data"]["name"]
            == "Updated"
        )
    assert (
        client.get(f"/api/v1/invoices?brand_id={brand['id']}", headers=headers).json()["data"][0][
            "id"
        ]
        == invoice["id"]
    )
    assert (
        client.get(f"/api/v1/campaigns?creator_id={creator['id']}", headers=headers).json()["data"][
            0
        ]["id"]
        == campaign["id"]
    )
    assert client.delete(f"/api/v1/brands/{brand['id']}", headers=headers).status_code == 409
    for kind, row in [
        ("invoices", invoice),
        ("campaigns", campaign),
        ("creators", creator),
        ("brands", brand),
    ]:
        assert client.delete(f"/api/v1/{kind}/{row['id']}", headers=headers).status_code == 200
        assert client.get(f"/api/v1/{kind}/{row['id']}", headers=headers).status_code == 404
