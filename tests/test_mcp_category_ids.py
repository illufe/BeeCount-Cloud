"""MCP transaction category-ID propagation on an isolated SQLite database."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.mcp.tools import write_tools
from src.models import (
    Ledger,
    ReadTxProjection,
    User,
    UserAccountProjection,
    UserCategoryProjection,
)
from src.projection import upsert_tx
from src.snapshot_mutator import (
    create_transaction as snapshot_create,
    update_transaction as snapshot_update,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def synthetic(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user = SimpleNamespace(id="user-1", is_admin=False)
    ledger = SimpleNamespace(
        id="ledger-internal", external_id="ledger-1", name="Main", currency="CNY"
    )
    with session_factory() as db:
        db.add(User(id=user.id, email="mcp-category@example.com", password_hash="x"))
        db.add(Ledger(
            id=ledger.id, user_id=user.id, external_id=ledger.external_id,
            name=ledger.name, currency=ledger.currency,
        ))
        db.add_all([
            UserAccountProjection(
                user_id=user.id, sync_id="acc-cash", name="Cash", currency="CNY",
            ),
            UserAccountProjection(
                user_id=user.id, sync_id="acc-bank", name="Bank", currency="CNY",
            ),
            UserCategoryProjection(
                user_id=user.id, sync_id="cat-food", name="Food", kind="expense",
            ),
            UserCategoryProjection(
                user_id=user.id, sync_id="cat-salary", name="Salary", kind="income",
            ),
        ])
        db.commit()

    calls: list[tuple[str, str, dict, dict]] = []
    next_id = 0

    async def fake_self_call(method, path, _user, **kwargs):
        nonlocal next_id
        body = kwargs["json"]
        headers = kwargs.get("headers") or {}
        calls.append((method, path, body, headers))
        if path.endswith("/batch"):
            ids = []
            for _item in body["transactions"]:
                next_id += 1
                ids.append(f"tx-{next_id}")
            return {"created_sync_ids": ids}
        next_id += 1
        return {"entity_id": f"tx-{next_id}"}

    async def no_currency(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(write_tools, "SessionLocal", session_factory)
    monkeypatch.setattr(
        write_tools, "_resolve_write_ledger", lambda *_args, **_kwargs: (ledger, None)
    )
    monkeypatch.setattr(write_tools, "_lookup_account_sync_id", lambda *_args: None)
    monkeypatch.setattr(write_tools, "_account_currency", lambda *_args: "CNY")
    monkeypatch.setattr(
        write_tools, "_is_tag_missing_in_ledger", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(write_tools, "_lookup_tag_sync_ids", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(write_tools, "_build_currency_fields", no_currency)
    monkeypatch.setattr(write_tools, "_self_call", fake_self_call)
    return SimpleNamespace(
        session_factory=session_factory,
        user=user,
        ledger=ledger,
        calls=calls,
    )


def _add_category(env, *, sync_id: str, name: str, kind: str) -> None:
    with env.session_factory() as db:
        db.add(UserCategoryProjection(
            user_id=env.user.id, sync_id=sync_id, name=name, kind=kind,
        ))
        db.commit()


def _materialize(env, payload: dict, sync_id: str, source_change_id: int) -> None:
    snapshot, _generated_id = snapshot_create({}, payload)
    item = snapshot["items"][0]
    item["syncId"] = sync_id
    with env.session_factory() as db:
        upsert_tx(
            db,
            ledger_id=env.ledger.id,
            user_id=env.user.id,
            source_change_id=source_change_id,
            payload=item,
        )
        db.commit()


def _projection_row(env, sync_id: str) -> ReadTxProjection:
    with env.session_factory() as db:
        row = db.scalar(
            select(ReadTxProjection).where(
                ReadTxProjection.ledger_id == env.ledger.id,
                ReadTxProjection.sync_id == sync_id,
            )
        )
        assert row is not None
        return row


def test_single_create_persists_category_id_through_projection(synthetic) -> None:
    result = _run(write_tools.create_transaction(
        synthetic.user,
        amount=12,
        tx_type="expense",
        category="Food",
        happened_at="2026-08-02T00:00:00Z",
        ledger_id=synthetic.ledger.external_id,
    ))
    body = synthetic.calls[0][2]
    assert result["sync_id"] == "tx-1"
    assert body["category_name"] == "Food"
    assert body["category_kind"] == "expense"
    assert body["category_id"] == "cat-food"

    _materialize(synthetic, body, "tx-1", 1)
    row = _projection_row(synthetic, "tx-1")
    assert row.category_sync_id == "cat-food"
    assert row.category_name == "Food"
    assert row.category_kind == "expense"


def test_batch_resolves_each_kind_name_once_and_preserves_fields(synthetic, monkeypatch) -> None:
    original = write_tools._load_category_sync_ids
    lookups: list[set[tuple[str, str]]] = []

    def wrapped(db, user_id, *, refs):
        lookups.append(set(refs))
        return original(db, user_id, refs=refs)

    monkeypatch.setattr(write_tools, "_load_category_sync_ids", wrapped)
    result = _run(write_tools.create_transactions(
        synthetic.user,
        ledger_id=synthetic.ledger.external_id,
        idempotency_key="batch-category-ids",
        transactions=[
            {"amount": 1, "tx_type": "expense", "category": "Food",
             "account_id": "acc-cash", "happened_at": "2026-08-02T00:00:00Z"},
            {"amount": 2, "tx_type": "expense", "category": "Food",
             "account_id": "acc-bank", "happened_at": "2026-08-02T00:01:00Z"},
            {"amount": 3, "tx_type": "income", "category": "Salary",
             "account_id": "acc-bank", "happened_at": "2026-08-02T00:02:00Z"},
        ],
    ))
    assert result["created_count"] == 3
    assert lookups == [{("expense", "Food"), ("income", "Salary")}]

    items = synthetic.calls[0][2]["transactions"]
    assert [(item["category_name"], item["category_kind"], item["category_id"])
            for item in items] == [
        ("Food", "expense", "cat-food"),
        ("Food", "expense", "cat-food"),
        ("Salary", "income", "cat-salary"),
    ]
    for index, item in enumerate(items, start=1):
        _materialize(synthetic, item, f"tx-{index}", index)
    assert _projection_row(synthetic, "tx-1").category_sync_id == "cat-food"
    assert _projection_row(synthetic, "tx-3").category_sync_id == "cat-salary"


def test_batch_transfer_and_uncategorized_do_not_write_category_id(synthetic) -> None:
    result = _run(write_tools.create_transactions(
        synthetic.user,
        ledger_id=synthetic.ledger.external_id,
        idempotency_key="batch-no-category-id",
        transactions=[
            {"amount": 1, "tx_type": "expense", "account_id": "acc-cash",
             "happened_at": "2026-08-02T00:00:00Z"},
            {"amount": 2, "tx_type": "transfer", "category": "Food",
             "from_account_id": "acc-cash", "to_account_id": "acc-bank",
             "happened_at": "2026-08-02T00:01:00Z"},
        ],
    ))
    assert result["created_count"] == 2
    items = synthetic.calls[0][2]["transactions"]
    assert "category_id" not in items[0]
    assert "category_id" not in items[1]
    assert items[1]["category_name"] == "Food"
    assert items[1]["category_kind"] == "transfer"


def test_batch_unknown_wrong_kind_and_ambiguous_categories_reject(synthetic) -> None:
    with pytest.raises(ValueError, match="Unknown categories"):
        _run(write_tools.create_transactions(
            synthetic.user,
            ledger_id=synthetic.ledger.external_id,
            idempotency_key="bad-name",
            transactions=[{"amount": 1, "category": "Missing", "account_id": "acc-cash",
                           "happened_at": "2026-08-02T00:00:00Z"}],
        ))
    with pytest.raises(ValueError, match="Category not found: Food"):
        _run(write_tools.create_transactions(
            synthetic.user,
            ledger_id=synthetic.ledger.external_id,
            idempotency_key="wrong-kind",
            transactions=[{"amount": 1, "tx_type": "income", "category": "Food",
                           "account_id": "acc-cash", "happened_at": "2026-08-02T00:00:00Z"}],
        ))

    _add_category(synthetic, sync_id="cat-food-duplicate", name="Food", kind="expense")
    with pytest.raises(ValueError, match="Ambiguous category: Food"):
        _run(write_tools.create_transactions(
            synthetic.user,
            ledger_id=synthetic.ledger.external_id,
            idempotency_key="ambiguous",
            transactions=[{"amount": 1, "category": "Food", "account_id": "acc-cash",
                           "happened_at": "2026-08-02T00:00:00Z"}],
        ))


def test_update_transaction_forwards_category_id(synthetic) -> None:
    with synthetic.session_factory() as db:
        db.add(ReadTxProjection(
            ledger_id=synthetic.ledger.id,
            sync_id="tx-existing",
            user_id=synthetic.user.id,
            tx_type="expense",
            amount=1,
            happened_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            category_sync_id="cat-food",
            category_name="Food",
            category_kind="expense",
        ))
        db.commit()

    _run(write_tools.update_transaction(
        synthetic.user,
        sync_id="tx-existing",
        ledger_id=synthetic.ledger.external_id,
        category="Food",
    ))
    method, path, body, _headers = synthetic.calls[0]
    assert method == "PATCH"
    assert path.endswith("/transactions/tx-existing")
    assert body["category_name"] == "Food"
    assert body["category_kind"] == "expense"
    assert body["category_id"] == "cat-food"

    _run(write_tools.update_transaction(
        synthetic.user,
        sync_id="tx-existing",
        ledger_id=synthetic.ledger.external_id,
        category="",
    ))
    _method, _path, clear_body, _headers = synthetic.calls[1]
    assert clear_body["category_name"] == ""
    assert clear_body["category_kind"] == "expense"
    assert clear_body["category_id"] == ""

    cleared = snapshot_update(
        {
            "items": [{
                "syncId": "tx-existing",
                "type": "expense",
                "amount": 1,
                "happenedAt": "2026-08-01T00:00:00Z",
                "categoryId": "cat-food",
                "categoryName": "Food",
                "categoryKind": "expense",
            }],
            "count": 1,
        },
        "tx-existing",
        clear_body,
    )
    assert "categoryId" not in cleared["items"][0]
    assert "categoryName" not in cleared["items"][0]


def test_batch_idempotent_replay_materializes_once(synthetic, monkeypatch) -> None:
    seen: dict[str, dict] = {}
    materialized = 0

    async def idempotent_self_call(_method, _path, _user, **kwargs):
        nonlocal materialized
        request_key = kwargs["headers"]["Idempotency-Key"]
        if request_key in seen:
            return seen[request_key]
        response = {"created_sync_ids": ["tx-idempotent"]}
        for item in kwargs["json"]["transactions"]:
            materialized += 1
            _materialize(synthetic, item, "tx-idempotent", materialized)
        seen[request_key] = response
        return response

    monkeypatch.setattr(write_tools, "_self_call", idempotent_self_call)
    args = dict(
        user=synthetic.user,
        ledger_id=synthetic.ledger.external_id,
        idempotency_key="stable-replay-key",
        transactions=[{"amount": 1, "category": "Food", "account_id": "acc-cash",
                       "happened_at": "2026-08-02T00:00:00Z"}],
    )
    first = _run(write_tools.create_transactions(**args))
    second = _run(write_tools.create_transactions(**args))
    assert first["sync_ids"] == second["sync_ids"] == ["tx-idempotent"]
    assert materialized == 1
    with synthetic.session_factory() as db:
        assert db.scalar(select(ReadTxProjection).where(
            ReadTxProjection.sync_id == "tx-idempotent",
        )) is not None
        assert db.query(ReadTxProjection).count() == 1
