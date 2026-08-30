"""GET /workspace/transactions 多值筛选(账户 / 分类)的 OR 语义。

单值向后兼容(1 个参数 → 1 元素列表),多值时同维度内"任一命中"。
"""
from datetime import datetime, timezone

from test_tx_read_id_resolution import _change, _iso, _make_client, _push, _register_and_token


def _seed(client, app_hdr, device_id: str) -> str:
    ledger_id = "lg-multi-filter"
    start = datetime(2026, 2, 1, tzinfo=timezone.utc)
    changes = [
        _change(ledger_id, "ledger", ledger_id, {
            "syncId": ledger_id, "ledgerName": "MultiFilter", "currency": "CNY",
        }),
        _change(ledger_id, "account", "account-cash", {
            "syncId": "account-cash", "name": "现金", "type": "cash", "currency": "CNY",
        }),
        _change(ledger_id, "account", "account-card", {
            "syncId": "account-card", "name": "银行卡", "type": "bank_card", "currency": "CNY",
        }),
        _change(ledger_id, "category", "category-salary", {
            "syncId": "category-salary", "name": "工资", "kind": "income", "level": 1,
        }),
        _change(ledger_id, "category", "category-bonus", {
            "syncId": "category-bonus", "name": "奖金", "kind": "income", "level": 1,
        }),
        _change(ledger_id, "transaction", "tx-1", {
            "syncId": "tx-1", "type": "income", "amount": 10,
            "happenedAt": _iso(start), "note": "a", "accountName": "现金",
            "accountId": "account-cash", "categoryName": "工资",
            "categoryKind": "income", "categoryId": "category-salary",
        }),
        _change(ledger_id, "transaction", "tx-2", {
            "syncId": "tx-2", "type": "income", "amount": 20,
            "happenedAt": _iso(start), "note": "b", "accountName": "银行卡",
            "accountId": "account-card", "categoryName": "奖金",
            "categoryKind": "income", "categoryId": "category-bonus",
        }),
        _change(ledger_id, "transaction", "tx-3", {
            "syncId": "tx-3", "type": "income", "amount": 30,
            "happenedAt": _iso(start), "note": "c", "accountName": "现金",
            "accountId": "account-cash", "categoryName": "奖金",
            "categoryKind": "income", "categoryId": "category-bonus",
        }),
    ]
    _push(client, app_hdr, device_id, ledger_id, changes)
    return ledger_id


def _fetch(client, web_hdr, params):
    resp = client.get("/api/v1/read/workspace/transactions", params=params, headers=web_hdr)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_multi_account_name_or_semantics() -> None:
    client = _make_client()
    try:
        app_token = _register_and_token(client, "multi@test.com", device_id="multi-app", client_type="app")
        web_token = _register_and_token(client, "multi@test.com", device_id="multi-web", client_type="web")
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_id = _seed(client, {"Authorization": f"Bearer {app_token}"}, "multi-app")

        # 单值向后兼容:只筛"现金"
        single = _fetch(client, web_hdr, [("ledger_id", ledger_id), ("account_name", "现金")])
        assert single["total"] == 2
        assert single["summary"]["income_total"] == 40.0

        # 多值任一命中:现金 OR 银行卡 → 全部 3 笔
        multi = _fetch(client, web_hdr, [
            ("ledger_id", ledger_id),
            ("account_name", "现金"),
            ("account_name", "银行卡"),
        ])
        assert multi["total"] == 3
        assert multi["summary"]["income_total"] == 60.0
    finally:
        client.close()


def test_multi_category_sync_id_or_semantics() -> None:
    client = _make_client()
    try:
        app_token = _register_and_token(client, "multi-cat@test.com", device_id="multi-cat-app", client_type="app")
        web_token = _register_and_token(client, "multi-cat@test.com", device_id="multi-cat-web", client_type="web")
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_id = _seed(client, {"Authorization": f"Bearer {app_token}"}, "multi-cat-app")

        # 单值:只筛"工资"
        single = _fetch(client, web_hdr, [("ledger_id", ledger_id), ("category_sync_id", "category-salary")])
        assert single["total"] == 1
        assert single["summary"]["income_total"] == 10.0

        # 多值任一命中:工资 OR 奖金 → 全部 3 笔
        multi = _fetch(client, web_hdr, [
            ("ledger_id", ledger_id),
            ("category_sync_id", "category-salary"),
            ("category_sync_id", "category-bonus"),
        ])
        assert multi["total"] == 3
        assert multi["summary"]["income_total"] == 60.0
    finally:
        client.close()
