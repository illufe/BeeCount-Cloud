"""Filtered transaction summary is calculated before pagination."""
from datetime import datetime, timezone

from test_tx_read_id_resolution import _change, _iso, _make_client, _push, _register_and_token


def test_workspace_transaction_summary_uses_full_filtered_set() -> None:
    client = _make_client()
    try:
        app_token = _register_and_token(
            client, "summary@test.com", device_id="summary-mobile", client_type="app"
        )
        web_token = _register_and_token(
            client, "summary@test.com", device_id="summary-web", client_type="web"
        )
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_id = "lg-summary"
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)

        changes = [
            _change(ledger_id, "ledger", ledger_id, {
                "syncId": ledger_id, "ledgerName": "Summary", "currency": "CNY",
            }),
            _change(ledger_id, "account", "account-cash", {
                "syncId": "account-cash", "name": "现金", "type": "cash", "currency": "CNY",
            }),
            _change(ledger_id, "category", "category-salary", {
                "syncId": "category-salary", "name": "工资", "kind": "income", "level": 1,
            }),
            _change(ledger_id, "tag", "tag-pay", {
                "syncId": "tag-pay", "name": "收入",
            }),
            _change(ledger_id, "transaction", "tx-income", {
                "syncId": "tx-income", "type": "income", "amount": 10,
                "happenedAt": _iso(start), "note": "第一笔收入", "accountName": "现金",
                "accountId": "account-cash", "categoryName": "工资",
                "categoryKind": "income", "categoryId": "category-salary",
                "tags": "收入", "tagIds": ["tag-pay"],
            }),
            _change(ledger_id, "transaction", "tx-income-2", {
                "syncId": "tx-income-2", "type": "income", "amount": 7,
                "happenedAt": _iso(start.replace(day=3)), "note": "第二笔收入",
                "accountName": "现金", "accountId": "account-cash",
                "categoryName": "工资", "categoryKind": "income",
                "categoryId": "category-salary", "tags": "收入", "tagIds": ["tag-pay"],
            }),
            _change(ledger_id, "transaction", "tx-excluded", {
                "syncId": "tx-excluded", "type": "income", "amount": 100,
                "happenedAt": _iso(start.replace(day=4)), "note": "排除统计",
                "accountName": "现金", "accountId": "account-cash",
                "categoryName": "工资", "categoryKind": "income",
                "categoryId": "category-salary", "tags": "收入", "tagIds": ["tag-pay"],
                "excludeFromStats": True,
            }),
        ]
        _push(client, app_hdr, "summary-mobile", ledger_id, changes)

        response = client.get(
            "/api/v1/read/workspace/transactions",
            params={
                "ledger_id": ledger_id,
                "q": "第一笔",
                "tx_type": "income",
                "account_name": "现金",
                "category_sync_id": "category-salary",
                "tag_sync_id": "tag-pay",
                "amount_min": 10,
                "amount_max": 10,
                "date_from": "2026-01-02T00:00:00Z",
                "date_to": "2026-01-03T00:00:00Z",
                "limit": 1,
                "offset": 1,
            },
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 1
        assert body["summary"] == {
            "income_total": 10.0,
            "expense_total": 0.0,
            "balance": 10.0,
        }
    finally:
        client.close()
