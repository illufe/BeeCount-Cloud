"""MCP account maintenance tools.

Account writes reuse the existing write router through the same in-process
HTTP path as transaction writes. The MCP scope is intentionally separate from
``mcp:write`` so an account-maintenance PAT cannot write transactions.
"""
from __future__ import annotations

from typing import Any

from ...config import get_settings
from ...database import SessionLocal
from ...models import User
from ...security import SCOPE_WEB_WRITE
from .write_tools import _resolve_write_ledger, _self_call


def _require_id(field: str, value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _resolve_account_ledger(user: User, ledger_id: str):
    ledger_id = _require_id("ledger_id", ledger_id)
    with SessionLocal() as db:
        ledger, status = _resolve_write_ledger(db, user, ledger_id)
    return ledger, status


async def create_account(
    user: User,
    *,
    ledger_id: str,
    name: str,
    account_type: str | None = None,
    currency: str | None = None,
    initial_balance: float = 0.0,
    base_change_id: int = 0,
) -> dict[str, Any]:
    """Create an account in an explicitly selected ledger."""
    ledger_id = _require_id("ledger_id", ledger_id)
    name = _require_id("name", name)
    ledger, status = _resolve_account_ledger(user, ledger_id)
    if status is not None:
        return status
    assert ledger is not None

    body: dict[str, Any] = {
        "base_change_id": base_change_id,
        "name": name,
        "initial_balance": float(initial_balance),
    }
    if account_type is not None:
        body["account_type"] = account_type
    if currency is not None:
        body["currency"] = currency
    path = f"{get_settings().api_prefix}/write/ledgers/{ledger.external_id}/accounts"
    result = await _self_call(
        "POST", path, user, internal_scopes=[SCOPE_WEB_WRITE], json=body
    )
    return {
        "status": "created",
        "ledger_id": ledger.external_id,
        "account_id": result.get("entity_id"),
        "name": name,
        "account_type": account_type,
        "currency": currency,
        "initial_balance": float(initial_balance),
        "_meta": result,
    }


async def update_account(
    user: User,
    *,
    ledger_id: str,
    account_id: str,
    name: str | None = None,
    account_type: str | None = None,
    currency: str | None = None,
    initial_balance: float | None = None,
    base_change_id: int = 0,
) -> dict[str, Any]:
    """Update an account by explicit account id."""
    ledger_id = _require_id("ledger_id", ledger_id)
    account_id = _require_id("account_id", account_id)
    if all(value is None for value in (name, account_type, currency, initial_balance)):
        raise ValueError("at least one account field is required")
    ledger, status = _resolve_account_ledger(user, ledger_id)
    if status is not None:
        return status
    assert ledger is not None

    body: dict[str, Any] = {"base_change_id": base_change_id}
    for key, value in (
        ("name", name),
        ("account_type", account_type),
        ("currency", currency),
        ("initial_balance", initial_balance),
    ):
        if value is not None:
            body[key] = value
    path = f"{get_settings().api_prefix}/write/ledgers/{ledger.external_id}/accounts/{account_id}"
    result = await _self_call(
        "PATCH", path, user, internal_scopes=[SCOPE_WEB_WRITE], json=body
    )
    return {
        "status": "updated",
        "ledger_id": ledger.external_id,
        "account_id": account_id,
        "_meta": result,
    }


async def delete_account(
    user: User,
    *,
    ledger_id: str,
    account_id: str,
    confirm: bool = False,
    base_change_id: int = 0,
) -> dict[str, Any]:
    """Delete an unlinked account after explicit confirmation."""
    ledger_id = _require_id("ledger_id", ledger_id)
    account_id = _require_id("account_id", account_id)
    if not confirm:
        return {
            "status": "confirmation_required",
            "message": "Re-call with confirm=true after the user explicitly approves deletion.",
            "ledger_id": ledger_id,
            "account_id": account_id,
        }
    ledger, status = _resolve_account_ledger(user, ledger_id)
    if status is not None:
        return status
    assert ledger is not None

    path = f"{get_settings().api_prefix}/write/ledgers/{ledger.external_id}/accounts/{account_id}"
    result = await _self_call(
        "DELETE",
        path,
        user,
        internal_scopes=[SCOPE_WEB_WRITE],
        json={"base_change_id": base_change_id},
    )
    return {
        "status": "deleted",
        "ledger_id": ledger.external_id,
        "account_id": account_id,
        "_meta": result,
    }
