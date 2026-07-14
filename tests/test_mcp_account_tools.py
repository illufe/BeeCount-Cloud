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
from src.models import User
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
        account_id = created["account_id"]
        assert account_id.startswith("acc_")

        updated = asyncio.run(
            account_tools.update_account(
                user, ledger_id=ledger_id, account_id=account_id, name="Cash Updated"
            )
        )
        assert updated["status"] == "updated"
        assert {row["name"] for row in read_tools.list_accounts(user)} == {"Cash Updated"}

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
