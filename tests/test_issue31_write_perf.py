"""issue #31 A1b / A3 回归测试 —— 单笔 create fast-path + 批量 MCP 写工具。

  - A1b: POST /write/ledgers/{id}/transactions 走 _commit_create_tx_fast,
         产出的 tx 可读、sync_change 可 pull(语义与旧的全量 build 路径一致)。
  - A3:  write_tools.create_transactions 批量工具:分块走 /transactions/batch、
         注入 MCP 标签、多账本拒绝瞎猜、未知分类清晰报错。
  (A2 的 threadpool 化由全量 write 测试覆盖 —— 所有 POST/PATCH/DELETE 现在都
   经过 run_in_threadpool。)
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src import _mcp_internal_client, snapshot_builder
from src.database import Base, get_db
from src.main import app
from src.mcp.tools import read_tools, write_tools
from src.models import ReadTxProjection, SyncChange, User


def _make_tag(client: TestClient, token: str, ledger: str, base_change_id: int, name: str) -> str:
    res = client.post(
        f"/api/v1/write/ledgers/{ledger}/tags",
        json={"base_change_id": base_change_id, "name": name},
        headers={"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"},
    )
    assert res.status_code == 200, res.text
    return res.json()["entity_id"]


def _strip_autogen(payload: dict) -> dict:
    """Fast/slow 两条路径产出的 normalized item 只有 syncId 不同,去掉它后应逐字段一致。"""
    out = dict(payload)
    out.pop("syncId", None)
    return out


def _batch_tx_changes(TS, *sync_ids) -> list[dict]:
    with TS() as db:
        rows = db.scalars(
            select(SyncChange).where(
                SyncChange.entity_type == "transaction",
                SyncChange.entity_sync_id.in_(list(sync_ids)),
            )
        ).all()
        return [
            {
                "entity_type": r.entity_type,
                "action": r.action,
                "scope": r.scope,
                "payload_json": _strip_autogen(r.payload_json),
                "updated_by_device_id": r.updated_by_device_id,
                "updated_by_user_id": r.updated_by_user_id,
            }
            for r in rows
        ]


def _batch_tx_projection_rows(TS, *sync_ids) -> list[dict]:
    with TS() as db:
        rows = db.scalars(
            select(ReadTxProjection).where(
                ReadTxProjection.sync_id.in_(list(sync_ids))
            )
        ).all()
        return [
            {
                "tx_type": r.tx_type,
                "amount": r.amount,
                "happened_at": r.happened_at,
                "note": r.note,
                "tags_csv": r.tags_csv,
                "tag_sync_ids_json": r.tag_sync_ids_json,
                "created_by_user_id": r.created_by_user_id,
                "last_edited_by_user_id": r.last_edited_by_user_id,
            }
            for r in rows
        ]


def _make_client_and_engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TS = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(read_tools, "SessionLocal", TS)
    monkeypatch.setattr(write_tools, "SessionLocal", TS)
    return TestClient(app), TS


def _register(client: TestClient, email: str) -> dict:
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "123456",
            "client_type": "web",
            "device_name": "pytest-web",
            "platform": "web",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _make_ledger(client: TestClient, token: str, name: str) -> str:
    res = client.post(
        "/api/v1/write/ledgers",
        json={"ledger_name": name, "currency": "CNY"},
        headers={"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"},
    )
    assert res.status_code == 200, res.text
    return res.json()["entity_id"]


def _fetch_user(TS, email: str) -> User:
    with TS() as db:
        u = db.scalar(select(User).where(User.email == email))
        assert u is not None
        db.expunge(u)
        return u


def _run_async(coro):
    """驱动 async MCP write tool。internal ASGI client 是进程级单例 —— 每次重置,
    绑到本次 asyncio.run 的 loop;跑完再清掉,别泄漏给后续测试。"""
    _mcp_internal_client._client = None
    try:
        return asyncio.run(coro)
    finally:
        _mcp_internal_client._client = None


# --------------------------------------------------------------------------
# A1b — 单笔 create fast-path
# --------------------------------------------------------------------------


def test_a1b_create_fast_path_roundtrip(monkeypatch) -> None:
    client, _TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "a1b@example.com")
        token = u["access_token"]
        led = _make_ledger(client, token, "L")
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"}

        res = client.post(
            f"/api/v1/write/ledgers/{led}/transactions",
            json={
                "base_change_id": 0,
                "tx_type": "expense",
                "amount": 12.5,
                "happened_at": "2026-05-01T00:00:00+00:00",
                "note": "coffee",
            },
            headers=hdr,
        )
        assert res.status_code == 200, res.text
        sync_id = res.json()["entity_id"]
        assert sync_id

        # 读回:fast-path 写的 tx 字段正确
        r2 = client.get(f"/api/v1/read/ledgers/{led}/transactions", headers=hdr)
        assert r2.status_code == 200, r2.text
        rows = [it for it in r2.json() if it["id"] == sync_id]
        assert len(rows) == 1, r2.json()
        assert rows[0]["amount"] == 12.5
        assert rows[0]["note"] == "coffee"
        assert rows[0]["tx_type"] == "expense"
    finally:
        app.dependency_overrides.clear()


def test_a1b_create_fast_path_emits_pullable_change(monkeypatch) -> None:
    client, _TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "a1bpull@example.com")
        token, device = u["access_token"], u["device_id"]
        led = _make_ledger(client, token, "L")
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "other-device"}

        res = client.post(
            f"/api/v1/write/ledgers/{led}/transactions",
            json={"base_change_id": 0, "tx_type": "income", "amount": 9,
                  "happened_at": "2026-05-02T00:00:00+00:00"},
            headers=hdr,
        )
        assert res.status_code == 200, res.text
        sync_id = res.json()["entity_id"]

        # fast-path 必须 emit 一条可增量 pull 的 transaction upsert change
        r = client.get("/api/v1/sync/pull?since=0&limit=500",
                       headers={"Authorization": f"Bearer {token}", "X-Device-ID": device})
        assert r.status_code == 200, r.text
        tx_changes = [
            c for c in r.json()["changes"]
            if c.get("entity_type") == "transaction"
            and c.get("entity_sync_id") == sync_id
            and c.get("action") == "upsert"
        ]
        assert len(tx_changes) == 1, r.json()
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# A3 — 批量 MCP 写工具
# --------------------------------------------------------------------------


def test_a3_batch_endpoint_one_commit(monkeypatch) -> None:
    """A3 的落地端点 /transactions/batch:50 笔一次 commit + A2 threadpool 化后仍
    正确。(create_transactions 这个 MCP 包装器对它的 self-call 走 app-scope token,
    而测试套件 conftest 把 ALLOW_APP_RW_SCOPES 设为 false,self-call 必 403 —— 跟
    test_mcp_tools 只测 read 工具同因;故这里直接用 web token 测端点本体。)"""
    client, _TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "batch@example.com")
        token = u["access_token"]
        led = _make_ledger(client, token, "B")
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"}

        txns = [
            {"tx_type": "expense", "amount": 1.0 + i,
             "happened_at": "2026-05-01T00:00:00+00:00", "tags": ["MCP"]}
            for i in range(50)
        ]
        res = client.post(
            f"/api/v1/write/ledgers/{led}/transactions/batch",
            json={"base_change_id": 0, "transactions": txns, "auto_ai_tag": False},
            headers=hdr,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body["created_sync_ids"]) == 50
        assert body["new_change_id"] > 0  # 单次 commit 的 change_id

        # 全部落库 + MCP tag 实体建出来了
        r = client.get(f"/api/v1/read/ledgers/{led}/transactions?limit=200", headers=hdr)
        assert r.status_code == 200, r.text
        assert len(r.json()) == 50
        tags = client.get(f"/api/v1/read/ledgers/{led}/tags", headers=hdr).json()
        assert any(t["name"] == "MCP" for t in tags), tags
    finally:
        app.dependency_overrides.clear()


def test_a3_bulk_refuses_multi_ledger_without_id(monkeypatch) -> None:
    client, TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "a3multi@example.com")
        token = u["access_token"]
        _make_ledger(client, token, "One")
        _make_ledger(client, token, "Two")
        user = _fetch_user(TS, "a3multi@example.com")

        result = _run_async(
            write_tools.create_transactions(
                user,
                transactions=[{"amount": 5, "tx_type": "expense", "happened_at": "2026-05-01"}],
                ledger_id=None,
                idempotency_key="test-a3-multi-ledger",
            )
        )
        # B5:多账本不指定 → 拒绝瞎猜,返回候选(不写入)
        assert result["status"] == "ledger_required", result
        assert len(result["candidates"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_a3_bulk_unknown_category_errors(monkeypatch) -> None:
    import pytest

    client, TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "a3cat@example.com")
        token = u["access_token"]
        led = _make_ledger(client, token, "L")
        account_res = client.post(
            f"/api/v1/write/ledgers/{led}/accounts",
            headers={"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"},
            json={
                "base_change_id": 0,
                "name": "Cash",
                "account_type": "cash",
                "currency": "CNY",
                "initial_balance": 0,
            },
        )
        assert account_res.status_code == 200, account_res.text
        user = _fetch_user(TS, "a3cat@example.com")

        with pytest.raises(ValueError, match="Unknown categories"):
            _run_async(
                write_tools.create_transactions(
                    user,
                    transactions=[{"amount": 5, "category": "NoSuchCat",
                                   "account_id": account_res.json()["entity_id"],
                                   "happened_at": "2026-05-01"}],
                    ledger_id=led,
                    idempotency_key="test-a3-unknown-category",
                )
            )
    finally:
        app.dependency_overrides.clear()


def test_a3_mcp_batch_forwards_native_amount_and_exclude_flags(monkeypatch) -> None:
    user = SimpleNamespace(id="user-1")
    ledger = SimpleNamespace(id="ledger-internal", external_id="ledger-1", name="L", currency="CNY")
    captured: list[dict] = []

    class DummySession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    async def fake_self_call(_method, _path, _user, **kwargs):
        captured.append(kwargs["json"])
        return {"created_sync_ids": ["tx-1"]}

    monkeypatch.setattr(write_tools, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(write_tools, "_resolve_write_ledger", lambda *_args, **_kwargs: (ledger, None))
    monkeypatch.setattr(write_tools, "_validate_names_exist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(write_tools, "_load_account_details", lambda *_args, **_kwargs: (
        {"acc-1": {"id": "acc-1", "name": "Cash", "currency": "CNY"}}, {}
    ))
    monkeypatch.setattr(write_tools, "_is_tag_missing_in_ledger", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(write_tools, "_self_call", fake_self_call)

    result = _run_async(write_tools.create_transactions(
        user,
        ledger_id="ledger-1",
        idempotency_key="batch-1",
        transactions=[{
            "tx_type": "expense", "amount": 2, "happened_at": "2026-05-01",
            "account_id": "acc-1", "currency": "USD", "native_amount": 15,
            "exclude_from_stats": True, "exclude_from_budget": True,
        }],
    ))
    assert result["created_count"] == 1
    item = captured[0]["transactions"][0]
    assert item["currency_code"] == "USD"
    assert item["native_amount"] == 15.0
    assert item["exclude_from_stats"] is True
    assert item["exclude_from_budget"] is True


def test_a3_batch_request_model_preserves_native_and_exclude_fields() -> None:
    from src.routers.write.transactions_batch import BatchTransactionItem, _build_tx_payload

    item = BatchTransactionItem(
        tx_type="expense", amount=2, happened_at="2026-05-01T00:00:00Z",
        account_id="acc-1", currency_code="USD", native_amount=15,
        exclude_from_stats=True, exclude_from_budget=True,
    )
    payload = _build_tx_payload(
        item=item, auto_tag_names=[], attachment_dict=None,
        actor_user=SimpleNamespace(id="user-1", is_admin=False),
    )
    assert payload["currency_code"] == "USD"
    assert payload["native_amount"] == 15
    assert payload["exclude_from_stats"] is True
    assert payload["exclude_from_budget"] is True


# --------------------------------------------------------------------------
# Batch create fast path(issue #31):跳过全量 snapshot build + 逐笔 deepcopy
# --------------------------------------------------------------------------


def test_batch_fast_vs_slow_equivalence(monkeypatch) -> None:
    """同输入分别走 fast 与 slow 路径,产出的 SyncChange 行 + read_tx_projection 行
    逐字段一致(sync_id / source_change_id 除外)。fast = auto_ai_tag=False 且 tag
    已存在;slow = 带 extra_tag_name(该名字已在批内,tx payload 逐字段等价)。"""
    client, TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "equiv@example.com")
        token = u["access_token"]
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"}
        led_fast = _make_ledger(client, token, "Fast")
        led_slow = _make_ledger(client, token, "Slow")

        # tag 是 user-global(按 ledger.user_id,owner==写者时等价 current_user.id),
        # 在 Fast 账本建一次,Fast/Slow 都能查到。
        _make_tag(client, token, led_fast, 0, "Food")

        txns = [
            {"tx_type": "expense", "amount": 12.5, "happened_at": "2026-05-01T00:00:00+00:00",
             "note": "lunch", "tags": ["Food"]},
            {"tx_type": "income", "amount": 99.0, "happened_at": "2026-05-02T00:00:00+00:00",
             "note": "salary", "tags": ["Food"]},
        ]

        # fast 路径:tag 存在 → 触发 fast path。
        rf = client.post(
            f"/api/v1/write/ledgers/{led_fast}/transactions/batch",
            json={"base_change_id": 0, "transactions": txns, "auto_ai_tag": False},
            headers=hdr,
        )
        assert rf.status_code == 200, rf.text
        fast_ids = rf.json()["created_sync_ids"]
        assert len(fast_ids) == 2

        # slow 路径:extra_tag_name 置为批内已有名 → 触发旧全量 build 路径,但 tx
        # payload(tags/tagIds) 与 fast 逐字段等价。
        rs = client.post(
            f"/api/v1/write/ledgers/{led_slow}/transactions/batch",
            json={"base_change_id": 0, "transactions": txns,
                  "auto_ai_tag": False, "extra_tag_name": "Food"},
            headers=hdr,
        )
        assert rs.status_code == 200, rs.text
        slow_ids = rs.json()["created_sync_ids"]
        assert len(slow_ids) == 2

        # SyncChange 行逐字段一致(仅 syncId / change_id 不同)。
        fast_changes = _batch_tx_changes(TS, *fast_ids)
        slow_changes = _batch_tx_changes(TS, *slow_ids)
        assert sorted(fast_changes, key=lambda d: str(d["payload_json"].get("amount"))) == \
            sorted(slow_changes, key=lambda d: str(d["payload_json"].get("amount")))

        # read_tx_projection 行逐字段一致(仅 sync_id / source_change_id 不同)。
        fast_rows = sorted(_batch_tx_projection_rows(TS, *fast_ids),
                           key=lambda d: str(d["amount"]))
        slow_rows = sorted(_batch_tx_projection_rows(TS, *slow_ids),
                           key=lambda d: str(d["amount"]))
        assert fast_rows == slow_rows

        # 响应结构一致(字段集合相同)。
        assert set(rf.json().keys()) == set(rs.json().keys())
        assert rf.json()["ledger_id"] != rs.json()["ledger_id"]
    finally:
        app.dependency_overrides.clear()


def test_batch_fast_skips_full_build(monkeypatch) -> None:
    """fast path 不触发全量 snapshot_builder.build(记录调用次数 → fast=0);
    slow 路径(auto_ai_tag=True)仍会调用 build(调用次数>0)。"""
    client, _TS = _make_client_and_engine(monkeypatch)
    calls: list = []
    orig_build = snapshot_builder.build

    def _tracking(*a, **k):
        calls.append(1)
        return orig_build(*a, **k)

    try:
        u = _register(client, "nobuild@example.com")
        token = u["access_token"]
        led = _make_ledger(client, token, "F")
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"}
        txns = [
            {"tx_type": "expense", "amount": 1.0 + i,
             "happened_at": "2026-05-01T00:00:00+00:00", "tags": ["MCP"]}
            for i in range(50)
        ]
        # tag 必须先存在并落库(fast 路径所有 tag 都要能在 projection 查到)。
        _make_tag(client, token, led, 0, "MCP")
        monkeypatch.setattr(snapshot_builder, "build", _tracking)

        res = client.post(
            f"/api/v1/write/ledgers/{led}/transactions/batch",
            json={"base_change_id": 0, "transactions": txns, "auto_ai_tag": False},
            headers=hdr,
        )
        assert res.status_code == 200, res.text
        assert len(res.json()["created_sync_ids"]) == 50
        # fast path:build 一次都没被调用。
        assert calls == [], "snapshot_builder.build should NOT be called on fast path"

        # slow 路径(带 auto_ai_tag=True)会调用 build。
        n_before = len(calls)
        res2 = client.post(
            f"/api/v1/write/ledgers/{led}/transactions/batch",
            json={"base_change_id": 0, "transactions": txns[:1], "auto_ai_tag": True},
            headers=hdr,
        )
        assert res2.status_code == 200, res2.text
        assert len(calls) > n_before
    finally:
        app.dependency_overrides.clear()


def test_batch_fast_falls_back_when_tag_missing(monkeypatch) -> None:
    """item 带一个账本里不存在的 tag 名 → 不满足 fast 触发条件 → 走 slow 路径
    (build 被调用、tag 实体被创建)。"""
    client, _TS = _make_client_and_engine(monkeypatch)
    calls: list = []
    orig_build = snapshot_builder.build

    def _wrapped(*a, **k):
        calls.append(1)
        return orig_build(*a, **k)

    monkeypatch.setattr(snapshot_builder, "build", _wrapped)
    try:
        u = _register(client, "fallback@example.com")
        token = u["access_token"]
        led = _make_ledger(client, token, "FB")
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"}
        res = client.post(
            f"/api/v1/write/ledgers/{led}/transactions/batch",
            json={
                "base_change_id": 0,
                "transactions": [{
                    "tx_type": "expense", "amount": 8.0,
                    "happened_at": "2026-05-03T00:00:00+00:00", "tags": ["BrandNew"],
                }],
                "auto_ai_tag": False,
            },
            headers=hdr,
        )
        assert res.status_code == 200, res.text
        # slow 路径:build 被调用 + 新 tag 实体建出来了。
        assert len(calls) == 1
        tags = client.get(f"/api/v1/read/ledgers/{led}/tags", headers=hdr).json()
        assert any(t["name"] == "BrandNew" for t in tags), tags
    finally:
        app.dependency_overrides.clear()


def test_batch_fast_atomicity_on_invalid_item(monkeypatch) -> None:
    """批量中第 2 笔 tx_type 非法 → 400 BATCH_TX_INVALID + failed_index=1,mutator
    阶段(纯内存)就要抛错,sync_changes / read_tx_projection 均 0 新行。"""
    client, TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "atomic@example.com")
        token = u["access_token"]
        led = _make_ledger(client, token, "AT")
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"}
        _make_tag(client, token, led, 0, "Food")  # 满足 fast 触发(所有 tag 存在)

        res = client.post(
            f"/api/v1/write/ledgers/{led}/transactions/batch",
            json={
                "base_change_id": 0,
                "transactions": [
                    {"tx_type": "expense", "amount": 1.0,
                     "happened_at": "2026-05-01T00:00:00+00:00"},
                    {"tx_type": "savings", "amount": 2.0,  # 非法 tx_type → mutator ValueError
                     "happened_at": "2026-05-01T00:00:00+00:00"},
                ],
                "auto_ai_tag": False,
            },
            headers=hdr,
        )
        assert res.status_code == 400, res.text
        body = res.json()
        assert body["error_code"] == "BATCH_TX_INVALID"
        assert body["failed_index"] == 1

        # 未写任何 DB 行。
        with TS() as db:
            n_changes = db.scalar(
                select(func.count(SyncChange.change_id)).where(
                    SyncChange.entity_type == "transaction"
                )
            )
            n_tx = db.scalar(select(func.count(ReadTxProjection.ledger_id)))
            assert n_changes == 0
            assert n_tx == 0
    finally:
        app.dependency_overrides.clear()


def test_batch_fast_idempotent_replay(monkeypatch) -> None:
    """同 Idempotency-Key + 同 payload 第二次请求返回 replay,不重复写行。"""
    client, TS = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, "idfat@example.com")
        token = u["access_token"]
        led = _make_ledger(client, token, "ID")
        hdr = {"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"}
        body = {
            "base_change_id": 0,
            "transactions": [{
                "tx_type": "expense", "amount": 5.0,
                "happened_at": "2026-05-01T00:00:00+00:00",
            }],
            "auto_ai_tag": False,
        }
        hdr_idem = {**hdr, "Idempotency-Key": "key-idem-fast-1"}
        r1 = client.post(f"/api/v1/write/ledgers/{led}/transactions/batch",
                         json=body, headers=hdr_idem)
        assert r1.status_code == 200, r1.text
        ids1 = r1.json()["created_sync_ids"]

        r2 = client.post(f"/api/v1/write/ledgers/{led}/transactions/batch",
                         json=body, headers=hdr_idem)
        assert r2.status_code == 200, r2.text
        ids2 = r2.json()["created_sync_ids"]
        # replay 返回与新请求相同(created_sync_ids 来自 replay 的 response_json)。
        assert ids2 == ids1

        # 行没重复写。
        with TS() as db:
            n_changes = db.scalar(
                select(func.count(SyncChange.change_id)).where(
                    SyncChange.entity_type == "transaction"
                )
            )
            n_tx = db.scalar(select(func.count(ReadTxProjection.ledger_id)))
            assert n_changes == 1
            assert n_tx == 1
    finally:
        app.dependency_overrides.clear()
