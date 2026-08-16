"""MCP read tools 的 happy-path 测试.

只覆盖 read 侧:write tools 走 HTTP self-call(in-process ASGI),那个链路
依赖 main.app 实例 + 真实 router,集成度比较高,留在 e2e 测试覆盖。
"""
from __future__ import annotations

from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base, get_db
from src.main import app
from src.mcp.tools import read_tools
from src.models import User


def _make_client_and_engine(monkeypatch):
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
    # read_tools 直接 `with SessionLocal() as db:` —— 不走 dep tree。
    monkeypatch.setattr(read_tools, "SessionLocal", testing_session)
    return TestClient(app), testing_session


def _register(client: TestClient, email: str = "tools@example.com") -> dict:
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


def _make_ledger(client: TestClient, token: str, name: str = "Main") -> str:
    res = client.post(
        "/api/v1/write/ledgers",
        json={"ledger_name": name, "currency": "CNY"},
        headers={"Authorization": f"Bearer {token}", "X-Device-ID": "d-web"},
    )
    assert res.status_code == 200, res.text
    return res.json()["entity_id"]


def _fetch_user(session_maker, email: str) -> User:
    with session_maker() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        db.expunge(user)
        return user


def test_list_ledgers_returns_user_ledgers(monkeypatch) -> None:
    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="lister@example.com")
        token = u["access_token"]
        _make_ledger(client, token, "Family")
        _make_ledger(client, token, "Personal")
        user = _fetch_user(session_maker, "lister@example.com")

        ledgers = read_tools.list_ledgers(user)
        assert len(ledgers) == 2
        names = {l["name"] for l in ledgers}
        assert names == {"Family", "Personal"}
        for led in ledgers:
            assert led["id"]
            assert led["currency"] == "CNY"
    finally:
        app.dependency_overrides.clear()


def test_get_active_ledger_returns_earliest(monkeypatch) -> None:
    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="active@example.com")
        token = u["access_token"]
        _make_ledger(client, token, "First")
        _make_ledger(client, token, "Second")
        user = _fetch_user(session_maker, "active@example.com")

        active = read_tools.get_active_ledger(user)
        assert active is not None
        assert active["name"] == "First"
    finally:
        app.dependency_overrides.clear()


def test_get_active_ledger_returns_none_for_no_ledger(monkeypatch) -> None:
    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        _register(client, email="empty@example.com")
        user = _fetch_user(session_maker, "empty@example.com")

        active = read_tools.get_active_ledger(user)
        assert active is None
    finally:
        app.dependency_overrides.clear()


def test_list_transactions_empty_ledger(monkeypatch) -> None:
    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="emptytx@example.com")
        token = u["access_token"]
        _make_ledger(client, token, "Empty")
        user = _fetch_user(session_maker, "emptytx@example.com")

        result = read_tools.list_transactions(user, limit=10)
        assert result["total"] == 0
        assert result["items"] == []
        assert result["ledger"] == "Empty"
    finally:
        app.dependency_overrides.clear()


def test_serialize_tx_exposes_ids_currency_native_and_exclude_flags() -> None:
    row = SimpleNamespace(
        sync_id="tx-1", tx_type="expense", amount=2.0,
        happened_at=None, note="n", category_name="Food", account_name="Cash",
        account_sync_id="acc-1", from_account_name=None, from_account_sync_id=None,
        to_account_name=None, to_account_sync_id=None, tags_csv="MCP",
        currency_code="USD", native_amount=15.0,
        exclude_from_stats=True, exclude_from_budget=True,
    )
    result = read_tools._serialize_tx(row, "Food")
    assert result["account_id"] == "acc-1"
    assert result["currency_code"] == "USD"
    assert result["native_amount"] == 15.0
    assert result["exclude_from_stats"] is True
    assert result["exclude_from_budget"] is True


def test_get_transactions_returns_all_matching_with_full_fields(monkeypatch) -> None:
    from datetime import datetime, timezone

    from src.models import Ledger, ReadTxProjection

    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="batch@example.com")
        token = u["access_token"]
        ledger_id = _make_ledger(client, token, "Batch")
        user = _fetch_user(session_maker, "batch@example.com")
        with session_maker() as db:
            led = db.scalar(select(Ledger).where(Ledger.external_id == ledger_id))
            now = datetime.now(timezone.utc)
            for i in range(3):
                db.add(ReadTxProjection(
                    ledger_id=led.id,
                    sync_id=f"tx-{i}",
                    user_id=user.id,
                    tx_type="expense",
                    amount=10.5 + i,
                    happened_at=now,
                    note=f"note-{i}",
                    category_name="Food",
                    account_name="Cash",
                    account_sync_id="acc-1",
                    currency_code="USD",
                    native_amount=71.0 + i,
                    exclude_from_stats=True,
                    exclude_from_budget=False,
                ))
            db.commit()

        out = read_tools.get_transactions(user, ["tx-0", "tx-1", "tx-2"])
        txs = out["transactions"]
        assert len(txs) == 3
        assert {t["sync_id"] for t in txs} == {"tx-0", "tx-1", "tx-2"}
        tx0 = next(t for t in txs if t["sync_id"] == "tx-0")
        assert tx0["tx_type"] == "expense"
        assert tx0["amount"] == 10.5
        assert tx0["happened_at"] is not None
        assert tx0["note"] == "note-0"
        assert tx0["account_id"] == "acc-1"
        assert tx0["currency_code"] == "USD"
        assert tx0["native_amount"] == 71.0
        assert tx0["exclude_from_stats"] is True
        assert tx0["exclude_from_budget"] is False
    finally:
        app.dependency_overrides.clear()


def test_get_transactions_returns_only_matching(monkeypatch) -> None:
    from datetime import datetime, timezone

    from src.models import Ledger, ReadTxProjection

    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="batch-partial@example.com")
        token = u["access_token"]
        ledger_id = _make_ledger(client, token, "BatchPartial")
        user = _fetch_user(session_maker, "batch-partial@example.com")
        with session_maker() as db:
            led = db.scalar(select(Ledger).where(Ledger.external_id == ledger_id))
            now = datetime.now(timezone.utc)
            for i in range(2):
                db.add(ReadTxProjection(
                    ledger_id=led.id,
                    sync_id=f"tx-{i}",
                    user_id=user.id,
                    tx_type="expense",
                    amount=1.0,
                    happened_at=now,
                ))
            db.commit()

        out = read_tools.get_transactions(user, ["tx-0", "missing"])
        txs = out["transactions"]
        assert len(txs) == 1
        assert txs[0]["sync_id"] == "tx-0"
    finally:
        app.dependency_overrides.clear()


def test_get_transactions_rejects_invalid_input(monkeypatch) -> None:
    import pytest

    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="batch-valid@example.com")
        _make_ledger(client, u["access_token"], "BatchValid")
        user = _fetch_user(session_maker, "batch-valid@example.com")

        with pytest.raises(ValueError, match="non-empty list"):
            read_tools.get_transactions(user, [])
        with pytest.raises(ValueError, match="non-empty list"):
            read_tools.get_transactions(user, "not-a-list")
        with pytest.raises(ValueError, match="200-item limit"):
            read_tools.get_transactions(user, [f"tx-{i}" for i in range(201)])
        with pytest.raises(ValueError, match="empty id"):
            read_tools.get_transactions(user, ["tx-0", "   "])
    finally:
        app.dependency_overrides.clear()


def test_get_transactions_isolated_per_user(monkeypatch) -> None:
    from datetime import datetime, timezone

    from src.models import Ledger, ReadTxProjection

    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        a = _register(client, email="batch-a@example.com")
        b = _register(client, email="batch-b@example.com")
        ledger_a = _make_ledger(client, a["access_token"], "LedgerA")
        ledger_b = _make_ledger(client, b["access_token"], "LedgerB")
        user_a = _fetch_user(session_maker, "batch-a@example.com")
        user_b = _fetch_user(session_maker, "batch-b@example.com")
        with session_maker() as db:
            led_a = db.scalar(select(Ledger).where(Ledger.external_id == ledger_a))
            led_b = db.scalar(select(Ledger).where(Ledger.external_id == ledger_b))
            now = datetime.now(timezone.utc)
            db.add(ReadTxProjection(
                ledger_id=led_a.id, sync_id="tx-a", user_id=user_a.id,
                tx_type="expense", amount=1.0, happened_at=now,
            ))
            db.add(ReadTxProjection(
                ledger_id=led_b.id, sync_id="tx-b", user_id=user_b.id,
                tx_type="expense", amount=1.0, happened_at=now,
            ))
            db.commit()

        out_a = read_tools.get_transactions(user_a, ["tx-a", "tx-b"])
        assert {t["sync_id"] for t in out_a["transactions"]} == {"tx-a"}
        out_b = read_tools.get_transactions(user_b, ["tx-a", "tx-b"])
        assert {t["sync_id"] for t in out_b["transactions"]} == {"tx-b"}
    finally:
        app.dependency_overrides.clear()


def test_get_ledger_stats_returns_zero_for_fresh_ledger(monkeypatch) -> None:
    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="stats@example.com")
        token = u["access_token"]
        _make_ledger(client, token, "Stats")
        user = _fetch_user(session_maker, "stats@example.com")

        stats = read_tools.get_ledger_stats(user)
        assert stats is not None
        assert stats["ledger"] == "Stats"
        assert stats["transaction_count"] == 0
        # 分类/账户/tag 在创建账本时 ensure_default 可能种,允许 >= 0
        assert stats["category_count"] >= 0
        assert stats["account_count"] >= 0
    finally:
        app.dependency_overrides.clear()


def test_search_empty_query_returns_empty(monkeypatch) -> None:
    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="search@example.com")
        token = u["access_token"]
        _make_ledger(client, token, "S")
        user = _fetch_user(session_maker, "search@example.com")

        # 空 query 直接短路
        out = read_tools.search(user, q="")
        assert out == []
        out = read_tools.search(user, q="   ")
        assert out == []
    finally:
        app.dependency_overrides.clear()


def test_merge_default_tag_dedupes_and_preserves_order() -> None:
    """单元层校验 MCP 默认标签合并逻辑 — 不需要 DB。"""
    from src.mcp.tools.write_tools import _MCP_DEFAULT_TAG, _merge_default_tag

    # LLM 没传 → 只有 MCP
    assert _merge_default_tag(None) == [_MCP_DEFAULT_TAG]
    assert _merge_default_tag([]) == [_MCP_DEFAULT_TAG]

    # LLM 传若干 → MCP 在末尾
    assert _merge_default_tag(["coffee", "work"]) == ["coffee", "work", _MCP_DEFAULT_TAG]

    # LLM 已经传了 MCP → 不重复
    out = _merge_default_tag([_MCP_DEFAULT_TAG, "coffee"])
    assert out == [_MCP_DEFAULT_TAG, "coffee"]

    # 空白 / 空字符串过滤
    assert _merge_default_tag(["  ", "", "x"]) == ["x", _MCP_DEFAULT_TAG]


def test_get_analytics_summary_empty_ledger(monkeypatch) -> None:
    client, session_maker = _make_client_and_engine(monkeypatch)
    try:
        u = _register(client, email="analytics@example.com")
        token = u["access_token"]
        _make_ledger(client, token, "A")
        user = _fetch_user(session_maker, "analytics@example.com")

        summary = read_tools.get_analytics_summary(user, scope="month")
        assert summary["ledger"] == "A"
        assert summary["income"] == 0
        assert summary["expense"] == 0
        assert summary["balance"] == 0
        assert summary["transaction_count"] == 0
        assert summary["top_categories"] == []
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# v30 交易级多币种:MCP 记账折算 helper(_build_currency_fields)
# ---------------------------------------------------------------------------


def test_mcp_currency_fields_base_currency_no_fields(monkeypatch) -> None:
    """交易币种==账本本位币 → 不产生两字段(server 落 NULL,统计 COALESCE 回退)。"""
    import asyncio
    from src.mcp.tools import write_tools

    client, sm = _make_client_and_engine(monkeypatch)
    monkeypatch.setattr(write_tools, "SessionLocal", sm)
    try:
        reg = _register(client)
        user = _fetch_user(sm, "tools@example.com")
        fields = asyncio.run(write_tools._build_currency_fields(
            user, ledger_base="CNY", account_currency="CNY",
            currency_arg=None, amount=100.0,
        ))
        assert fields == {}
    finally:
        app.dependency_overrides.clear()


def test_mcp_currency_fields_foreign_auto_rate(monkeypatch) -> None:
    """外币无 override、走自动源:1 CNY = 0.14 USD(fetcher base→quote) →
    12 USD 折 CNY = 12 / 0.14 ≈ 85.7(方向:quote 金额折 base 要除)。"""
    import asyncio
    from src.mcp.tools import write_tools
    from src.services.exchange_rate import fetcher as rate_fetcher

    client, sm = _make_client_and_engine(monkeypatch)
    monkeypatch.setattr(write_tools, "SessionLocal", sm)

    class _Row:
        payload_json = {"USD": 0.14, "JPY": 20.0}

    async def fake_get_rates(db, base):
        assert base == "CNY"
        return _Row(), False

    monkeypatch.setattr(rate_fetcher, "get_rates", fake_get_rates)
    try:
        _register(client)
        user = _fetch_user(sm, "tools@example.com")
        fields = asyncio.run(write_tools._build_currency_fields(
            user, ledger_base="CNY", account_currency="USD",
            currency_arg=None, amount=12.0,
        ))
        assert fields["currency_code"] == "USD"
        assert abs(fields["native_amount"] - 12.0 / 0.14) < 1e-6
    finally:
        app.dependency_overrides.clear()


def test_mcp_currency_fields_missing_rate_falls_back_to_amount(monkeypatch) -> None:
    """外币且拉不到汇率 → native=amount(1:1),currency_code 仍落
    (Web 改主币种重算 / App L11 横幅可捞回,绝不丢币种)。"""
    import asyncio
    from src.mcp.tools import write_tools
    from src.services.exchange_rate import fetcher as rate_fetcher

    client, sm = _make_client_and_engine(monkeypatch)
    monkeypatch.setattr(write_tools, "SessionLocal", sm)

    async def boom(db, base):
        raise RuntimeError("rate source down")

    monkeypatch.setattr(rate_fetcher, "get_rates", boom)
    try:
        _register(client)
        user = _fetch_user(sm, "tools@example.com")
        fields = asyncio.run(write_tools._build_currency_fields(
            user, ledger_base="CNY", account_currency="THB",
            currency_arg=None, amount=500.0,
        ))
        assert fields["currency_code"] == "THB"
        assert fields["native_amount"] == 500.0
    finally:
        app.dependency_overrides.clear()


def test_mcp_update_transaction_binds_ledger_and_forwards_xau(monkeypatch) -> None:
    import asyncio
    from datetime import datetime, timezone

    from src.mcp.tools import write_tools
    from src.models import Ledger, ReadTxProjection

    client, sm = _make_client_and_engine(monkeypatch)
    monkeypatch.setattr(write_tools, "SessionLocal", sm)
    try:
        reg = _register(client, email="update-xau@example.com")
        first_ledger = _make_ledger(client, reg["access_token"], "Gold")
        other_ledger = _make_ledger(client, reg["access_token"], "Other")
        user = _fetch_user(sm, "update-xau@example.com")
        with sm() as db:
            ledger = db.scalar(select(Ledger).where(Ledger.external_id == first_ledger))
            assert ledger is not None
            db.add(ReadTxProjection(
                ledger_id=ledger.id,
                sync_id="tx-xau",
                user_id=user.id,
                tx_type="expense",
                amount=2.5,
                happened_at=datetime.now(timezone.utc),
            ))
            db.commit()

        calls: list[tuple[str, str, dict]] = []

        async def fake_self_call(method, path, _user, **kwargs):
            calls.append((method, path, kwargs["json"]))
            return {"entity_id": "tx-xau"}

        monkeypatch.setattr(write_tools, "_self_call", fake_self_call)
        try:
            asyncio.run(write_tools.update_transaction(
                user,
                sync_id="tx-xau",
                ledger_id=other_ledger,
                currency_code="XAU",
                native_amount=77.758692,
            ))
        except ValueError as exc:
            assert "does not match" in str(exc)
        else:
            raise AssertionError("cross-ledger update unexpectedly reached self-call")
        assert calls == []

        asyncio.run(write_tools.update_transaction(
            user,
            sync_id="tx-xau",
            ledger_id=f" {first_ledger} ",
            amount=2.5,
            currency_code=" xau ",
            native_amount=77.758692,
        ))
        assert calls == [(
            "PATCH",
            f"/api/v1/write/ledgers/{first_ledger}/transactions/tx-xau",
            {
                "base_change_id": 0,
                "amount": 2.5,
                "currency_code": "XAU",
                "native_amount": 77.758692,
            },
        )]
    finally:
        app.dependency_overrides.clear()
