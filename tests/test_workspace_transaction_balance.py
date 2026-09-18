"""Workspace transaction reconciliation balances use the complete ledger stream."""
from datetime import datetime, timezone

from test_tx_read_id_resolution import _change, _iso, _make_client, _push, _register_and_token


def test_workspace_transaction_balance_is_ordered_unfiltered_and_amount_based() -> None:
    client = _make_client()
    try:
        app_token = _register_and_token(
            client, "balance@test.com", device_id="balance-app", client_type="app"
        )
        web_token = _register_and_token(
            client, "balance@test.com", device_id="balance-web", client_type="web"
        )
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_id = "lg-balance"
        account_a = "account-a"
        account_b = "account-b"
        day_one = datetime(2026, 1, 1, tzinfo=timezone.utc)
        same_time = datetime(2026, 1, 3, tzinfo=timezone.utc)

        changes = [
            _change(ledger_id, "ledger", ledger_id, {
                "syncId": ledger_id, "ledgerName": "Balance", "currency": "CNY",
            }),
            _change(ledger_id, "account", account_a, {
                "syncId": account_a, "name": "USD account", "type": "cash",
                "currency": "USD", "initialBalance": 100,
            }),
            _change(ledger_id, "account", account_b, {
                "syncId": account_b, "name": "CNY account", "type": "cash",
                "currency": "CNY", "initialBalance": 50,
            }),
            _change(ledger_id, "transaction", "tx-income", {
                "syncId": "tx-income", "type": "income", "amount": 20,
                "happenedAt": _iso(day_one), "txIndex": 1,
                "accountId": account_a, "accountName": "USD account",
            }),
            _change(ledger_id, "transaction", "tx-excluded", {
                "syncId": "tx-excluded", "type": "expense", "amount": 5,
                "happenedAt": _iso(day_one), "txIndex": 2,
                "accountId": account_a, "accountName": "USD account",
                "excludeFromStats": True,
            }),
            _change(ledger_id, "transaction", "tx-transfer", {
                "syncId": "tx-transfer", "type": "transfer", "amount": 30,
                "happenedAt": _iso(day_one), "txIndex": 3,
                "fromAccountId": account_a, "fromAccountName": "USD account",
                "toAccountId": account_b, "toAccountName": "CNY account",
            }),
            _change(ledger_id, "transaction", "tx-usd-expense", {
                "syncId": "tx-usd-expense", "type": "expense", "amount": 12,
                "happenedAt": _iso(day_one.replace(day=2)), "txIndex": 1,
                "accountId": account_a, "accountName": "USD account",
                "currencyCode": "USD", "nativeAmount": 86.4,
            }),
            _change(ledger_id, "transaction", "tx-adjustment", {
                "syncId": "tx-adjustment", "type": "adjustment", "amount": 7,
                "happenedAt": _iso(day_one.replace(day=2)), "txIndex": 2,
                "accountId": account_a, "accountName": "USD account",
            }),
            _change(ledger_id, "transaction", "tx-same-a", {
                "syncId": "tx-same-a", "type": "income", "amount": 2,
                "happenedAt": _iso(same_time), "txIndex": 4,
                "accountId": account_a, "accountName": "USD account",
            }),
            _change(ledger_id, "transaction", "tx-same-z", {
                "syncId": "tx-same-z", "type": "expense", "amount": 1,
                "happenedAt": _iso(same_time), "txIndex": 4,
                "accountId": account_a, "accountName": "USD account",
            }),
        ]
        _push(client, app_hdr, "balance-app", ledger_id, changes)

        disabled = client.get(
            "/api/v1/read/workspace/transactions",
            params={"ledger_id": ledger_id, "limit": 1},
            headers=web_hdr,
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["items"][0]["account_balance_after"] is None

        response = client.get(
            "/api/v1/read/workspace/transactions",
            params={"ledger_id": ledger_id, "include_account_balance": True, "limit": 20},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["id"] for item in items[:2]] == ["tx-same-z", "tx-same-a"]
        by_id = {item["id"]: item for item in items}
        assert by_id["tx-income"]["account_balance_after"] == 120.0
        assert by_id["tx-excluded"]["account_balance_after"] == 115.0
        assert by_id["tx-transfer"]["from_account_balance_after"] == 85.0
        assert by_id["tx-transfer"]["to_account_balance_after"] == 80.0
        assert by_id["tx-usd-expense"]["account_balance_after"] == 73.0
        assert by_id["tx-adjustment"]["account_balance_after"] == 80.0
        assert by_id["tx-same-a"]["account_balance_after"] == 82.0
        assert by_id["tx-same-z"]["account_balance_after"] == 81.0

        filtered_page = client.get(
            "/api/v1/read/workspace/transactions",
            params={
                "ledger_id": ledger_id,
                "tx_type": "expense",
                "include_account_balance": True,
                "limit": 1,
                "offset": 2,
            },
            headers=web_hdr,
        )
        assert filtered_page.status_code == 200, filtered_page.text
        assert filtered_page.json()["items"][0]["id"] == "tx-excluded"
        assert filtered_page.json()["items"][0]["account_balance_after"] == 115.0
    finally:
        client.close()
