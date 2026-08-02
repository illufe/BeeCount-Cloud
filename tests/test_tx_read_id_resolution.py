"""P1.1: read endpoints resolve tx tag/category/account names by id.

Contract: `/read/workspace/transactions` and `/read/ledgers/{id}/transactions`
- If snapshot.items[i].tagIds is a non-empty list, resolve each id against
  snapshot.tags and return CURRENT names. This means entity renames reflect in
  tx listing without any cascade rewrite of snapshot.items.
- If no ids (legacy tx from mobile pre-id-support), fall back to the names
  stored in the tx item.
- If an id is in the list but not found in snapshot.tags (e.g., deleted tag),
  skip it; if all ids fail, fall back to stored names.

Same for accountId / fromAccountId / toAccountId and categoryId.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base, get_db
from src.main import app


def _make_client() -> TestClient:
    # 每个测试用例独立 in-memory SQLite。绝不能用 src.database.engine —— 那是
    # 服务端真实 DB，drop_all 会清掉用户数据。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _register_and_token(client: TestClient, email: str, *, device_id: str, client_type: str) -> str:
    client.post("/api/v1/auth/register", json={"email": email, "password": "Pa$$word1!"})
    r = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "Pa$$word1!",
            "device_id": device_id,
            "client_type": client_type,
            "device_name": f"pytest-{client_type}",
            "platform": "test",
        },
    )
    return r.json()["access_token"]


def _iso(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat()


def _push(client, hdr, device_id, ledger_id, changes):
    r = client.post(
        "/api/v1/sync/push",
        headers=hdr,
        json={"device_id": device_id, "changes": changes},
    )
    assert r.status_code == 200, r.text
    return r


def test_tag_rename_reflects_in_tx_via_id_resolution():
    client = _make_client()
    try:
        app_token = _register_and_token(client, "a@test.com", device_id="mobile-1", client_type="app")
        web_token = _register_and_token(client, "a@test.com", device_id="web-1", client_type="web")
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}

        ledger_id = "lg_1"
        tag_sync_id = "tag-alpha"
        tx_sync_id = "tx-uuid-1"

        _push(
            client, app_hdr, "mobile-1", ledger_id,
            [
                {
                    "ledger_id": ledger_id, "entity_type": "tag", "entity_sync_id": tag_sync_id,
                    "action": "upsert", "updated_at": _iso(),
                    "payload": {"syncId": tag_sync_id, "name": "A"},
                },
                {
                    "ledger_id": ledger_id, "entity_type": "transaction", "entity_sync_id": tx_sync_id,
                    "action": "upsert", "updated_at": _iso(),
                    "payload": {
                        "syncId": tx_sync_id, "type": "expense", "amount": 10,
                        "happenedAt": _iso(), "note": "x",
                        "tags": "A",
                        "tagIds": [tag_sync_id],
                    },
                },
            ],
        )

        r = client.get("/api/v1/read/workspace/transactions", headers=web_hdr)
        assert r.status_code == 200, r.text
        tx = r.json()["items"][0]
        assert tx["tags_list"] == ["A"]

        later = datetime.now(timezone.utc) + timedelta(seconds=2)
        _push(
            client, app_hdr, "mobile-1", ledger_id,
            [
                {
                    "ledger_id": ledger_id, "entity_type": "tag", "entity_sync_id": tag_sync_id,
                    "action": "upsert", "updated_at": _iso(later),
                    "payload": {"syncId": tag_sync_id, "name": "B"},
                },
            ],
        )

        r = client.get("/api/v1/read/workspace/transactions", headers=web_hdr)
        tx = r.json()["items"][0]
        assert tx["tags_list"] == ["B"], f"expected ['B'], got {tx['tags_list']}"
    finally:
        app.dependency_overrides.clear()


def test_account_rename_reflects_in_tx_via_id_resolution():
    client = _make_client()
    try:
        app_token = _register_and_token(client, "b@test.com", device_id="m1", client_type="app")
        web_token = _register_and_token(client, "b@test.com", device_id="w1", client_type="web")
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}

        ledger_id = "lg_b"
        acc_sync_id = "acc-uuid-1"
        tx_sync_id = "tx-b-1"

        _push(client, app_hdr, "m1", ledger_id, [
            {
                "ledger_id": ledger_id, "entity_type": "account", "entity_sync_id": acc_sync_id,
                "action": "upsert", "updated_at": _iso(),
                "payload": {"syncId": acc_sync_id, "name": "招商", "type": "bank_card", "currency": "CNY"},
            },
            {
                "ledger_id": ledger_id, "entity_type": "transaction", "entity_sync_id": tx_sync_id,
                "action": "upsert", "updated_at": _iso(),
                "payload": {
                    "syncId": tx_sync_id, "type": "expense", "amount": 5,
                    "happenedAt": _iso(),
                    "accountName": "招商",
                    "accountId": acc_sync_id,
                },
            },
        ])

        later = datetime.now(timezone.utc) + timedelta(seconds=2)
        _push(client, app_hdr, "m1", ledger_id, [
            {
                "ledger_id": ledger_id, "entity_type": "account", "entity_sync_id": acc_sync_id,
                "action": "upsert", "updated_at": _iso(later),
                "payload": {"syncId": acc_sync_id, "name": "招商银行", "type": "bank_card", "currency": "CNY"},
            },
        ])

        r = client.get("/api/v1/read/workspace/transactions", headers=web_hdr)
        tx = r.json()["items"][0]
        assert tx["account_name"] == "招商银行", f"got {tx['account_name']}"
    finally:
        app.dependency_overrides.clear()


def test_legacy_tx_without_ids_falls_back_to_name():
    client = _make_client()
    try:
        app_token = _register_and_token(client, "c@test.com", device_id="m1", client_type="app")
        web_token = _register_and_token(client, "c@test.com", device_id="w1", client_type="web")
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}

        ledger_id = "lg_c"
        tx_sync_id = "tx-c-1"

        _push(client, app_hdr, "m1", ledger_id, [
            {
                "ledger_id": ledger_id, "entity_type": "transaction", "entity_sync_id": tx_sync_id,
                "action": "upsert", "updated_at": _iso(),
                "payload": {
                    "syncId": tx_sync_id, "type": "expense", "amount": 1,
                    "happenedAt": _iso(),
                    "accountName": "现金",
                    "categoryName": "餐饮", "categoryKind": "expense",
                    "tags": "午餐,外卖",
                },
            },
        ])

        r = client.get("/api/v1/read/workspace/transactions", headers=web_hdr)
        tx = r.json()["items"][0]
        assert tx["account_name"] == "现金"
        assert tx["category_name"] == "餐饮"
        assert tx["tags_list"] == ["午餐", "外卖"]
    finally:
        app.dependency_overrides.clear()


def test_tag_id_not_found_falls_back_to_stored_names():
    client = _make_client()
    try:
        app_token = _register_and_token(client, "d@test.com", device_id="m1", client_type="app")
        web_token = _register_and_token(client, "d@test.com", device_id="w1", client_type="web")
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}

        ledger_id = "lg_d"
        tx_sync_id = "tx-d-1"

        _push(client, app_hdr, "m1", ledger_id, [
            {
                "ledger_id": ledger_id, "entity_type": "transaction", "entity_sync_id": tx_sync_id,
                "action": "upsert", "updated_at": _iso(),
                "payload": {
                    "syncId": tx_sync_id, "type": "expense", "amount": 1,
                    "happenedAt": _iso(),
                    "tags": "历史标签",
                    "tagIds": ["tag-nonexistent"],
                },
            },
        ])

        r = client.get("/api/v1/read/workspace/transactions", headers=web_hdr)
        tx = r.json()["items"][0]
        assert tx["tags_list"] == ["历史标签"], f"got {tx['tags_list']}"
    finally:
        app.dependency_overrides.clear()


def _change(ledger_id: str, entity_type: str, sync_id: str, payload: dict) -> dict:
    return {
        "ledger_id": ledger_id,
        "entity_type": entity_type,
        "entity_sync_id": sync_id,
        "action": "upsert",
        "updated_at": _iso(),
        "payload": payload,
    }


def test_workspace_category_counts_include_legacy_names_without_crossing_kind_or_scope():
    client = _make_client()
    try:
        app_token = _register_and_token(client, "category-counts@test.com", device_id="m1", client_type="app")
        web_token = _register_and_token(client, "category-counts@test.com", device_id="w1", client_type="web")
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}

        ledger_one = "lg-category-counts-1"
        ledger_two = "lg-category-counts-2"
        _push(client, app_hdr, "m1", ledger_one, [
            _change(ledger_one, "ledger", ledger_one, {
                "syncId": ledger_one, "ledgerName": "分类计数一", "currency": "CNY",
            }),
            _change(ledger_two, "ledger", ledger_two, {
                "syncId": ledger_two, "ledgerName": "分类计数二", "currency": "CNY",
            }),
            _change(ledger_one, "category", "cat-breakfast", {
                "syncId": "cat-breakfast", "name": "早餐", "kind": "expense", "level": 2,
            }),
            _change(ledger_one, "category", "cat-cross-expense", {
                "syncId": "cat-cross-expense", "name": "跨类", "kind": "expense", "level": 1,
            }),
            _change(ledger_one, "category", "cat-cross-income", {
                "syncId": "cat-cross-income", "name": "跨类", "kind": "income", "level": 1,
            }),
            _change(ledger_one, "category", "cat-ambiguous-a", {
                "syncId": "cat-ambiguous-a", "name": "同名", "kind": "expense", "level": 1,
            }),
            _change(ledger_one, "category", "cat-ambiguous-b", {
                "syncId": "cat-ambiguous-b", "name": "同名", "kind": "expense", "level": 1,
            }),
            _change(ledger_one, "transaction", "tx-breakfast-exact", {
                "syncId": "tx-breakfast-exact", "type": "expense", "amount": 1,
                "happenedAt": _iso(), "categoryId": "cat-breakfast",
                "categoryName": "早餐", "categoryKind": "expense",
            }),
            _change(ledger_one, "transaction", "tx-breakfast-legacy", {
                "syncId": "tx-breakfast-legacy", "type": "expense", "amount": 2,
                "happenedAt": _iso(), "categoryName": " 早餐 ", "categoryKind": "EXPENSE",
            }),
            _change(ledger_one, "transaction", "tx-cross-expense", {
                "syncId": "tx-cross-expense", "type": "expense", "amount": 3,
                "happenedAt": _iso(), "categoryName": "跨类", "categoryKind": "expense",
            }),
            _change(ledger_one, "transaction", "tx-cross-income", {
                "syncId": "tx-cross-income", "type": "income", "amount": 4,
                "happenedAt": _iso(), "categoryName": "跨类", "categoryKind": "income",
            }),
            _change(ledger_one, "transaction", "tx-ambiguous", {
                "syncId": "tx-ambiguous", "type": "expense", "amount": 5,
                "happenedAt": _iso(), "categoryName": "同名", "categoryKind": "expense",
            }),
            _change(ledger_two, "transaction", "tx-breakfast-other-ledger", {
                "syncId": "tx-breakfast-other-ledger", "type": "expense", "amount": 6,
                "happenedAt": _iso(), "categoryName": "早餐", "categoryKind": "expense",
            }),
        ])

        response = client.get(
            "/api/v1/read/workspace/categories",
            params={"ledger_id": ledger_one},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        rows = {(row["kind"], row["name"]): row["tx_count"] for row in response.json()}
        assert rows[("expense", "早餐")] == 2
        assert rows[("expense", "跨类")] == 1
        assert rows[("income", "跨类")] == 1
        assert rows[("expense", "同名")] == 0

        response = client.get(
            "/api/v1/read/workspace/categories",
            params={"ledger_id": ledger_two},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        rows = {(row["kind"], row["name"]): row["tx_count"] for row in response.json()}
        assert rows[("expense", "早餐")] == 1
    finally:
        app.dependency_overrides.clear()


def test_workspace_category_detail_merges_exact_and_legacy_without_duplicates():
    client = _make_client()
    try:
        app_token = _register_and_token(client, "category-detail@test.com", device_id="m1", client_type="app")
        web_token = _register_and_token(client, "category-detail@test.com", device_id="w1", client_type="web")
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_one = "lg-category-detail-1"
        ledger_two = "lg-category-detail-2"

        _push(client, app_hdr, "m1", ledger_one, [
            _change(ledger_one, "ledger", ledger_one, {
                "syncId": ledger_one, "ledgerName": "分类详情一", "currency": "CNY",
            }),
            _change(ledger_two, "ledger", ledger_two, {
                "syncId": ledger_two, "ledgerName": "分类详情二", "currency": "CNY",
            }),
            _change(ledger_one, "category", "cat-detail", {
                "syncId": "cat-detail", "name": "详情分类", "kind": "expense", "level": 2,
            }),
            _change(ledger_one, "transaction", "tx-detail-exact", {
                "syncId": "tx-detail-exact", "type": "expense", "amount": 1,
                "happenedAt": _iso(), "categoryId": "cat-detail",
                "categoryName": "详情分类", "categoryKind": "expense",
            }),
            _change(ledger_one, "transaction", "tx-detail-legacy", {
                "syncId": "tx-detail-legacy", "type": "expense", "amount": 2,
                "happenedAt": _iso(), "categoryName": "详情分类", "categoryKind": "expense",
            }),
            _change(ledger_two, "transaction", "tx-detail-other-ledger", {
                "syncId": "tx-detail-other-ledger", "type": "expense", "amount": 3,
                "happenedAt": _iso(), "categoryName": "详情分类", "categoryKind": "expense",
            }),
        ])

        response = client.get(
            "/api/v1/read/workspace/transactions",
            params={"ledger_id": ledger_one, "category_sync_id": "cat-detail", "limit": 50},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 2
        assert {row["id"] for row in page["items"]} == {"tx-detail-exact", "tx-detail-legacy"}

        response = client.get(
            "/api/v1/read/workspace/transactions",
            params={"ledger_id": ledger_two, "category_sync_id": "cat-detail", "limit": 50},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 1
        assert [row["id"] for row in page["items"]] == ["tx-detail-other-ledger"]
    finally:
        app.dependency_overrides.clear()


def test_workspace_category_parent_rollup_and_detail_keep_scope_kind_and_ambiguity():
    client = _make_client()
    try:
        app_token = _register_and_token(client, "category-parent@test.com", device_id="m1", client_type="app")
        web_token = _register_and_token(client, "category-parent@test.com", device_id="w1", client_type="web")
        app_hdr = {"Authorization": f"Bearer {app_token}"}
        web_hdr = {"Authorization": f"Bearer {web_token}"}
        ledger_one = "lg-category-parent-1"
        ledger_two = "lg-category-parent-2"

        _push(client, app_hdr, "m1", ledger_one, [
            _change(ledger_one, "ledger", ledger_one, {
                "syncId": ledger_one, "ledgerName": "父分类账本一", "currency": "CNY",
            }),
            _change(ledger_two, "ledger", ledger_two, {
                "syncId": ledger_two, "ledgerName": "父分类账本二", "currency": "CNY",
            }),
            _change(ledger_one, "category", "cat-parent-expense", {
                "syncId": "cat-parent-expense", "name": " 食品 ", "kind": "expense", "level": 1,
            }),
            _change(ledger_one, "category", "cat-child-breakfast", {
                "syncId": "cat-child-breakfast", "name": "早餐", "kind": "expense", "level": 2,
                "parentName": "食品",
            }),
            _change(ledger_one, "category", "cat-child-snack", {
                "syncId": "cat-child-snack", "name": "零食", "kind": "expense", "level": 2,
                "parentName": " 食品 ",
            }),
            _change(ledger_one, "category", "cat-parent-income", {
                "syncId": "cat-parent-income", "name": "食品", "kind": "income", "level": 1,
            }),
            _change(ledger_one, "category", "cat-child-income", {
                "syncId": "cat-child-income", "name": "早餐", "kind": "income", "level": 2,
                "parentName": "食品",
            }),
            _change(ledger_one, "category", "cat-parent-ambiguous-a", {
                "syncId": "cat-parent-ambiguous-a", "name": "歧义", "kind": "expense", "level": 1,
            }),
            _change(ledger_one, "category", "cat-parent-ambiguous-b", {
                "syncId": "cat-parent-ambiguous-b", "name": "歧义", "kind": "expense", "level": 1,
            }),
            _change(ledger_one, "category", "cat-child-ambiguous", {
                "syncId": "cat-child-ambiguous", "name": "孩子", "kind": "expense", "level": 2,
                "parentName": "歧义",
            }),
            _change(ledger_one, "transaction", "tx-parent-exact", {
                "syncId": "tx-parent-exact", "type": "expense", "amount": 1,
                "happenedAt": _iso(), "categoryId": "cat-parent-expense",
                "categoryName": "食品", "categoryKind": "expense",
            }),
            _change(ledger_one, "transaction", "tx-parent-legacy", {
                "syncId": "tx-parent-legacy", "type": "expense", "amount": 2,
                "happenedAt": _iso(), "categoryName": " 食品 ", "categoryKind": "EXPENSE",
            }),
            _change(ledger_one, "transaction", "tx-breakfast-exact", {
                "syncId": "tx-breakfast-exact", "type": "expense", "amount": 3,
                "happenedAt": _iso(), "categoryId": "cat-child-breakfast",
                "categoryName": "早餐", "categoryKind": "expense",
            }),
            _change(ledger_one, "transaction", "tx-snack-legacy", {
                "syncId": "tx-snack-legacy", "type": "expense", "amount": 4,
                "happenedAt": _iso(), "categoryName": " 零食 ", "categoryKind": "EXPENSE",
            }),
            _change(ledger_one, "transaction", "tx-income-cross-kind", {
                "syncId": "tx-income-cross-kind", "type": "income", "amount": 5,
                "happenedAt": _iso(), "categoryName": "早餐", "categoryKind": "income",
            }),
            _change(ledger_one, "transaction", "tx-ambiguous-parent-exact", {
                "syncId": "tx-ambiguous-parent-exact", "type": "expense", "amount": 6,
                "happenedAt": _iso(), "categoryId": "cat-parent-ambiguous-a",
                "categoryName": "歧义", "categoryKind": "expense",
            }),
            _change(ledger_one, "transaction", "tx-ambiguous-child-legacy", {
                "syncId": "tx-ambiguous-child-legacy", "type": "expense", "amount": 7,
                "happenedAt": _iso(), "categoryName": "孩子", "categoryKind": "expense",
            }),
            _change(ledger_two, "transaction", "tx-parent-other-ledger", {
                "syncId": "tx-parent-other-ledger", "type": "expense", "amount": 8,
                "happenedAt": _iso(), "categoryId": "cat-parent-expense",
                "categoryName": "食品", "categoryKind": "expense",
            }),
            _change(ledger_two, "transaction", "tx-child-other-ledger", {
                "syncId": "tx-child-other-ledger", "type": "expense", "amount": 9,
                "happenedAt": _iso(), "categoryName": "零食", "categoryKind": "expense",
            }),
        ])

        response = client.get(
            "/api/v1/read/workspace/categories",
            params={"ledger_id": ledger_one},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        rows = {(row["kind"], row["name"]): row["tx_count"] for row in response.json()}
        assert rows[("expense", "食品")] == 4
        assert rows[("expense", "早餐")] == 1
        assert rows[("expense", "零食")] == 1
        assert rows[("income", "早餐")] == 1
        assert rows[("expense", "孩子")] == 1
        rows_by_id = {row["id"]: row["tx_count"] for row in response.json()}
        assert rows_by_id["cat-parent-ambiguous-a"] == 1
        assert rows_by_id["cat-parent-ambiguous-b"] == 0

        response = client.get(
            "/api/v1/read/workspace/transactions",
            params={"ledger_id": ledger_one, "category_sync_id": "cat-parent-expense", "limit": 50},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 4
        assert {row["id"] for row in page["items"]} == {
            "tx-parent-exact", "tx-parent-legacy", "tx-breakfast-exact", "tx-snack-legacy",
        }

        response = client.get(
            "/api/v1/read/workspace/transactions",
            params={"ledger_id": ledger_one, "category_sync_id": "cat-child-breakfast", "limit": 50},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 1
        assert [row["id"] for row in page["items"]] == ["tx-breakfast-exact"]

        response = client.get(
            "/api/v1/read/workspace/transactions",
            params={"ledger_id": ledger_one, "category_sync_id": "cat-parent-ambiguous-a", "limit": 50},
            headers=web_hdr,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 1
        assert [row["id"] for row in page["items"]] == ["tx-ambiguous-parent-exact"]
    finally:
        app.dependency_overrides.clear()
