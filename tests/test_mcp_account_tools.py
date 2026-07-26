"""Account MCP tools: CRUD path, confirmation, and narrow scope."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base, get_db
from src.main import app
from src.mcp import server
from src.mcp.tools import account_tools, read_tools
from src.models import Ledger, ReadTxProjection, User
from src.security import SCOPE_MCP_ACCOUNT_WRITE, SCOPE_MCP_WRITE


def _bootstrap(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(account_tools, "SessionLocal", Session)
    monkeypatch.setattr(read_tools, "SessionLocal", Session)
    return Session


def _register(client: TestClient) -> dict:
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "account-tools@example.com",
            "password": "123456",
            "client_type": "web",
            "device_name": "pytest-web",
            "platform": "web",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _create_ledger(client: TestClient, token: str) -> str:
    res = client.post(
        "/api/v1/write/ledgers",
        headers={"Authorization": f"Bearer {token}", "X-Device-ID": "pytest-web"},
        json={"ledger_name": "Accounts", "currency": "CNY"},
    )
    assert res.status_code == 200, res.text
    return res.json()["entity_id"]


def _user(Session) -> User:
    with Session() as db:
        user = db.scalar(select(User).where(User.email == "account-tools@example.com"))
        assert user is not None
        db.expunge(user)
        return user


def test_account_tools_crud_and_delete_confirmation(monkeypatch) -> None:
    Session = _bootstrap(monkeypatch)
    client = TestClient(app)
    try:
        auth = _register(client)
        ledger_id = _create_ledger(client, auth["access_token"])
        user = _user(Session)

        created = asyncio.run(
            account_tools.create_account(
                user,
                ledger_id=ledger_id,
                name="Cash",
                account_type="cash",
                currency="CNY",
            )
        )
        assert created["status"] == "created"
        assert created["hidden"] is False
        account_id = created["account_id"]
        assert account_id.startswith("acc_")

        updated = asyncio.run(
            account_tools.update_account(
                user, ledger_id=ledger_id, account_id=account_id, name="Cash Updated"
            )
        )
        assert updated["status"] == "updated"
        account_rows = read_tools.list_accounts(user)
        assert {row["name"] for row in account_rows} == {"Cash Updated"}
        assert account_rows[0]["id"] == account_id
        assert account_rows[0]["source_change_id"] >= 1
        assert account_rows[0]["hidden"] is False

        hidden = asyncio.run(
            account_tools.update_account(
                user, ledger_id=ledger_id, account_id=account_id, hidden=True
            )
        )
        assert hidden["status"] == "updated"
        assert read_tools.list_accounts(user)[0]["hidden"] is True
        asyncio.run(
            account_tools.update_account(
                user, ledger_id=ledger_id, account_id=account_id, hidden=False
            )
        )
        assert read_tools.list_accounts(user)[0]["hidden"] is False

        with Session() as db:
            ledger = db.scalar(select(Ledger).where(Ledger.external_id == ledger_id))
            assert ledger is not None
            db.add(ReadTxProjection(
                ledger_id=ledger.id,
                sync_id="tx_mcp_account_stats",
                user_id=user.id,
                tx_type="income",
                amount=5.0,
                happened_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                account_sync_id=account_id,
            ))
            db.commit()
        stats = read_tools.list_accounts(user)[0]
        assert stats["balance"] == 5.0
        assert stats["transaction_count"] == 1
        assert stats["last_transaction_at"].startswith("2026-07-01T00:00:00")
        assert read_tools.list_accounts(user, account_id=account_id)[0]["id"] == account_id
        assert read_tools.list_accounts(user, account_id="missing") == []

        pending = asyncio.run(
            account_tools.delete_account(
                user, ledger_id=ledger_id, account_id=account_id
            )
        )
        assert pending["status"] == "confirmation_required"
        assert read_tools.list_accounts(user)[0]["name"] == "Cash Updated"

        deleted = asyncio.run(
            account_tools.delete_account(
                user, ledger_id=ledger_id, account_id=account_id, confirm=True
            )
        )
        assert deleted["status"] == "deleted"
        assert read_tools.list_accounts(user) == []
    finally:
        app.dependency_overrides.clear()


def test_account_scope_is_separate_from_transaction_scope(monkeypatch) -> None:
    request = SimpleNamespace(
        scope={
            "bc_mcp_user": User(
                id=str(uuid4()),
                email="scope@example.com",
                password_hash="x",
                is_admin=False,
                is_enabled=True,
                created_at=datetime.now(timezone.utc),
            ),
            "bc_mcp_scopes": {SCOPE_MCP_WRITE},
        }
    )
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))

    async def invoke() -> None:
        with monkeypatch.context() as patch:
            patch.setattr(server, "_write_call_log", lambda **_kwargs: None)
            with pytest.raises(PermissionError, match="mcp:account_write"):
                await server.create_account(ctx, ledger_id="L1", name="Cash")

            request.scope["bc_mcp_scopes"] = {SCOPE_MCP_ACCOUNT_WRITE}
            with pytest.raises(PermissionError, match="mcp:write"):
                await server.create_transaction(ctx, amount=1)

    asyncio.run(invoke())
