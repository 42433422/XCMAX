from __future__ import annotations


def test_account_bootstrap_returns_wallet_auth_and_llm_state(client, auth_headers):
    r = client.get("/api/account/bootstrap", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["ok"] is True
    assert body["user"]["id"]
    assert body["wallet"]["balance"] == 0.0
    assert body["membership"]["tier"] == "free"
    assert body["llm"]["default"]["provider"] == "openai"
    assert isinstance(body["llm"]["providers"], list)
    assert isinstance(body["llm"]["byok_configured_count"], int)


def test_wallet_overview_includes_nested_wallet_shape(client, auth_headers):
    r = client.get("/api/wallet/overview", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["balance"] == 0.0
    assert body["wallet"]["balance"] == 0.0
    assert "transactions" in body
