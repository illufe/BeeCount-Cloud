"""GET /workspace/transactions 多值筛选(账户 / 分类)的 OR 语义。

单值向后兼容(1 个参数 → 1 元素列表),多值时同维度内"任一命中"。
"""
from datetime import datetime, timezone

from test_tx_read_id_resolution import _change, _iso, _make_client, _push, _register_and_token


def _seed(client, app_hdr, device_id: str, with_substring_account: bool = False) -> str:
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
    if with_substring_account:
        changes.extend([
            _change(ledger_id, "account", "account-cash-card", {
                "syncId": "account-cash-card", "name": "现金卡", "type": "cash", "currency": "CNY",
            }),
            _change(ledger_id, "transaction", "tx-4", {
                "syncId": "tx-4", "type": "income", "amount": 40,
                "happenedAt": _iso(start), "note": "d", "accountName": "现金卡",
                "accountId": "account-cash-card", "categoryName": "奖金",
                "categoryKind": "income", "categoryId": "category-bonus",
            }),
        ])
    _push(client, app_hdr, device_id, ledger_id, changes)
    return ledger_id


def _fetch(client, web_hdr, params):
    resp = client.get("/api/v1/read/workspace/transactions", params=params, headers=web_hdr)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _fetch_analytics(client, web_hdr, params):
    resp = client.get("/api/v1/read/workspace/analytics", params=params, headers=web_hdr)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_analytics(client, app_hdr, device_id: str) -> tuple[str, str]:
    ledger_a = "lg-analytics-a"
    ledger_b = "lg-analytics-b"

    def at(month: int, day: int) -> str:
        return _iso(datetime(2026, month, day, tzinfo=timezone.utc))

    _push(client, app_hdr, device_id, ledger_a, [
        _change(ledger_a, "ledger", ledger_a, {
            "syncId": ledger_a, "ledgerName": "Analytics A", "currency": "CNY",
        }),
        _change(ledger_a, "account", "account-a-cash", {
            "syncId": "account-a-cash", "name": "A现金", "type": "cash", "currency": "CNY",
        }),
        _change(ledger_a, "account", "account-a-card", {
            "syncId": "account-a-card", "name": "A银行卡", "type": "bank_card", "currency": "CNY",
        }),
        _change(ledger_a, "account", "account-a-other", {
            "syncId": "account-a-other", "name": "A其他", "type": "cash", "currency": "CNY",
        }),
        _change(ledger_a, "transaction", "tx-a-income", {
            "syncId": "tx-a-income", "type": "income", "amount": 10,
            "happenedAt": at(1, 10), "accountName": "A现金", "accountId": "account-a-cash",
        }),
        _change(ledger_a, "transaction", "tx-a-expense", {
            "syncId": "tx-a-expense", "type": "expense", "amount": 20,
            "happenedAt": at(2, 10), "accountName": "A银行卡", "accountId": "account-a-card",
        }),
        _change(ledger_a, "transaction", "tx-a-out", {
            "syncId": "tx-a-out", "type": "transfer", "amount": 1,
            "happenedAt": at(3, 10), "fromAccountName": "A现金",
            "fromAccountId": "account-a-cash", "toAccountName": "A其他",
            "toAccountId": "account-a-other",
        }),
        _change(ledger_a, "transaction", "tx-a-in", {
            "syncId": "tx-a-in", "type": "transfer", "amount": 2,
            "happenedAt": at(3, 11), "fromAccountName": "A其他",
            "fromAccountId": "account-a-other", "toAccountName": "A银行卡",
            "toAccountId": "account-a-card",
        }),
    ])
    _push(client, app_hdr, device_id, ledger_b, [
        _change(ledger_b, "ledger", ledger_b, {
            "syncId": ledger_b, "ledgerName": "Analytics B", "currency": "CNY",
        }),
        _change(ledger_b, "account", "account-b-cash", {
            "syncId": "account-b-cash", "name": "B现金", "type": "cash", "currency": "CNY",
        }),
        _change(ledger_b, "transaction", "tx-b-income", {
            "syncId": "tx-b-income", "type": "income", "amount": 100,
            "happenedAt": at(1, 10), "accountName": "B现金", "accountId": "account-b-cash",
        }),
    ])
    return ledger_a, ledger_b


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


def test_analytics_account_sync_id_matches_direct_and_transfer_endpoints() -> None:
    client = _make_client()
    try:
        app_token = _register_and_token(client, "analytics-filter@test.com", device_id="analytics-filter-app", client_type="app")
        web_token = _register_and_token(client, "analytics-filter@test.com", device_id="analytics-filter-web", client_type="web")
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_id, _ = _seed_analytics(
            client,
            {"Authorization": f"Bearer {app_token}"},
            "analytics-filter-app",
        )
        base = [
            ("scope", "year"),
            ("period", "2026"),
            ("ledger_id", ledger_id),
            ("natural_month", "true"),
        ]

        # No account filter keeps the complete ledger totals unchanged.
        unfiltered = _fetch_analytics(client, web_hdr, base)
        assert unfiltered["summary"]["transaction_count"] == 4
        assert unfiltered["summary"]["income_total"] == 10.0
        assert unfiltered["summary"]["expense_total"] == 20.0
        assert unfiltered["summary"]["balance"] == -10.0
        unfiltered_series = {item["bucket"]: item for item in unfiltered["series"]}
        assert unfiltered_series["2026-01"]["income"] == 10.0
        assert unfiltered_series["2026-02"]["expense"] == 20.0

        # The selected account may be the direct account or the transfer source.
        cash = _fetch_analytics(client, web_hdr, base + [("account_sync_id", "account-a-cash")])
        assert cash["summary"]["transaction_count"] == 2
        assert cash["summary"]["income_total"] == 10.0
        assert cash["summary"]["expense_total"] == 0.0

        # The selected account may also be the transfer destination.
        card = _fetch_analytics(client, web_hdr, base + [("account_sync_id", "account-a-card")])
        assert card["summary"]["transaction_count"] == 2
        assert card["summary"]["income_total"] == 0.0
        assert card["summary"]["expense_total"] == 20.0

        # Repeated account_sync_id parameters retain OR semantics.
        multi = _fetch_analytics(client, web_hdr, base + [
            ("account_sync_id", "account-a-cash"),
            ("account_sync_id", "account-a-card"),
        ])
        assert multi["summary"]["transaction_count"] == 4
        assert multi["summary"]["income_total"] == 10.0
        assert multi["summary"]["expense_total"] == 20.0
    finally:
        client.close()


def test_analytics_account_sync_id_respects_ledger_scope() -> None:
    client = _make_client()
    try:
        app_token = _register_and_token(client, "analytics-ledger@test.com", device_id="analytics-ledger-app", client_type="app")
        web_token = _register_and_token(client, "analytics-ledger@test.com", device_id="analytics-ledger-web", client_type="web")
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_a, ledger_b = _seed_analytics(
            client,
            {"Authorization": f"Bearer {app_token}"},
            "analytics-ledger-app",
        )
        params = [
            ("scope", "year"),
            ("period", "2026"),
            ("ledger_id", ledger_b),
            ("natural_month", "true"),
        ]
        ledger_b_rows = _fetch_analytics(client, web_hdr, params)
        assert ledger_b_rows["summary"]["transaction_count"] == 1
        assert ledger_b_rows["summary"]["income_total"] == 100.0

        # An account from another ledger cannot cross the requested ledger boundary.
        foreign_account = _fetch_analytics(client, web_hdr, params + [
            ("account_sync_id", "account-a-cash"),
        ])
        assert foreign_account["summary"]["transaction_count"] == 0
        assert foreign_account["summary"]["income_total"] == 0.0
        assert foreign_account["summary"]["expense_total"] == 0.0
        assert foreign_account["summary"]["balance"] == 0.0
        assert foreign_account["series"] == []
        assert ledger_a != ledger_b
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


def test_account_sync_id_is_exact_for_substring_account_names() -> None:
    client = _make_client()
    try:
        app_token = _register_and_token(client, "multi-account-id@test.com", device_id="multi-account-id-app", client_type="app")
        web_token = _register_and_token(client, "multi-account-id@test.com", device_id="multi-account-id-web", client_type="web")
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_id = _seed(
            client,
            {"Authorization": f"Bearer {app_token}"},
            "multi-account-id-app",
            with_substring_account=True,
        )

        # account_sync_id 必须按 ID 精确命中,不能把“现金”当作 account_name 的子串查询。
        exact = _fetch(client, web_hdr, [
            ("ledger_id", ledger_id),
            ("account_sync_id", "account-cash"),
        ])
        assert exact["total"] == 2
        assert exact["summary"]["income_total"] == 40.0

        # 重复参数仍是同维度 OR,可同时选择两个账户。
        multi = _fetch(client, web_hdr, [
            ("ledger_id", ledger_id),
            ("account_sync_id", "account-cash"),
            ("account_sync_id", "account-cash-card"),
        ])
        assert multi["total"] == 3
        assert multi["summary"]["income_total"] == 80.0
    finally:
        client.close()
