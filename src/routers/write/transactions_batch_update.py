"""POST /write/ledgers/{ledger_id}/transactions/batch/update.

The endpoint is intentionally small: it batches the category/note information
updates used by the private reconciliation executor.  Every item is checked
against its expected state before any item is mutated, and the whole request
commits in one database transaction.  SyncChange remains one row per
transaction so existing mobile pull consumers need no protocol change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ... import projection, snapshot_builder
from ...concurrency import lock_ledger_for_materialize
from ...database import get_db
from ...deps import get_current_user
from ...models import (
    AuditLog,
    ReadTxProjection,
    SyncChange,
    SyncPushIdempotency,
    User,
    UserCategoryProjection,
)
from ...snapshot_mutator import update_transaction
from ._shared import (
    _TRANSACTION_WRITE_ROLES,
    _WRITE_RESPONSES,
    _WRITE_SCOPE_DEP,
    _hash_request,
    _load_idempotent_response,
    _payload_with_actor,
    _prepare_write,
    _projection_row_to_tx_dict,
    _utcnow,
)

router = APIRouter()

_ALLOWED_TARGET_FIELDS = {"category", "note"}
_EXPECTED_FIELDS = {
    "category", "category_id", "category_kind", "note", "amount", "tx_type",
    "account_id", "from_account_id", "to_account_id", "happened_at", "date",
    "exclude_from_stats", "exclude_from_budget", "currency_code", "native_amount", "tags",
}


class BatchTxUpdateItem(BaseModel):
    sync_id: str = Field(min_length=1, max_length=255)
    expected_old_state: dict[str, Any] = Field(default_factory=dict)
    target_state: dict[str, Any] = Field(min_length=1)


class BatchTxUpdateRequest(BaseModel):
    base_change_id: int = Field(default=0, ge=0)
    updates: list[BatchTxUpdateItem] = Field(min_length=1, max_length=50)


class BatchTxUpdateFailure(BaseModel):
    sync_id: str
    reason: str
    message: str | None = None


class BatchTxUpdateResponse(BaseModel):
    ledger_id: str
    base_change_id: int
    new_change_id: int
    server_timestamp: datetime
    idempotency_replayed: bool = False
    updated_sync_ids: list[str] = Field(default_factory=list)
    already_applied_sync_ids: list[str] = Field(default_factory=list)
    blocked: list[BatchTxUpdateFailure] = Field(default_factory=list)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _state_value(row: ReadTxProjection, key: str) -> Any:
    values = {
        "category": row.category_name,
        "category_id": row.category_sync_id,
        "category_kind": row.category_kind,
        "note": row.note,
        # The MCP read tool exposes tags as a CSV name string and normalizes a
        # NULL projection value to the empty string.  Keep tags precondition-
        # only; tags are intentionally not an allowed batch target.
        "tags": row.tags_csv or "",
        "amount": row.amount,
        "tx_type": row.tx_type,
        "account_id": row.account_sync_id,
        "from_account_id": row.from_account_sync_id,
        "to_account_id": row.to_account_sync_id,
        "happened_at": _iso(row.happened_at),
        "date": _iso(row.happened_at),
        "exclude_from_stats": bool(row.exclude_from_stats),
        "exclude_from_budget": bool(row.exclude_from_budget),
        "currency_code": row.currency_code,
        "native_amount": row.native_amount,
    }
    return values.get(key)


def _same_value(actual: Any, expected: Any, key: str) -> bool:
    if key in {"happened_at", "date"}:
        if actual is None or expected is None:
            return actual == expected
        try:
            left = str(actual).replace("Z", "+00:00")
            right = str(expected).replace("Z", "+00:00")
            return datetime.fromisoformat(left).astimezone(timezone.utc) == datetime.fromisoformat(right).astimezone(timezone.utc)
        except ValueError:
            return actual == expected
    return actual == expected


def _state_matches(row: ReadTxProjection, state: dict[str, Any]) -> bool:
    return all(_same_value(_state_value(row, key), value, key) for key, value in state.items())


def _replay_response(db: Session, *, user_id: str, device_id: str, key: str) -> BatchTxUpdateResponse | None:
    row = db.scalar(
        select(SyncPushIdempotency).where(
            SyncPushIdempotency.user_id == user_id,
            SyncPushIdempotency.device_id == device_id,
            SyncPushIdempotency.idempotency_key == key,
        )
    )
    if row is None or not row.response_json:
        return None
    return BatchTxUpdateResponse.model_validate(row.response_json)


@router.post(
    "/ledgers/{ledger_id}/transactions/batch/update",
    response_model=BatchTxUpdateResponse,
    responses=_WRITE_RESPONSES,
)
async def update_tx_batch(
    ledger_id: str,
    req: BatchTxUpdateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    device_id: str = Header(default="web-console", alias="X-Device-ID"),
    _scopes: set[str] = Depends(_WRITE_SCOPE_DEP),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchTxUpdateResponse:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key is required for batch transaction updates",
        )
    if len(idempotency_key) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key is too long",
        )
    idempotency_key = idempotency_key.strip()
    payload_for_ide = req.model_dump(mode="json")
    ledger, replay = _prepare_write(
        db=db,
        current_user=current_user,
        ledger_external_id=ledger_id,
        required_roles=_TRANSACTION_WRITE_ROLES,
        idempotency_key=idempotency_key,
        device_id=device_id,
        method=request.method,
        path=request.url.path,
        payload=payload_for_ide,
    )
    if replay:
        stored = _replay_response(
            db, user_id=current_user.id, device_id=device_id, key=str(idempotency_key)
        )
        if stored is not None:
            stored.idempotency_replayed = True  # type: ignore[attr-defined]
            return stored

    sync_ids = [item.sync_id for item in req.updates]
    if len(set(sync_ids)) != len(sync_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="duplicate sync_id in batch")
    for item in req.updates:
        unknown_expected = set(item.expected_old_state) - _EXPECTED_FIELDS
        unknown_target = set(item.target_state) - _ALLOWED_TARGET_FIELDS
        if unknown_expected:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unsupported expected_old_state fields: {sorted(unknown_expected)}",
            )
        if unknown_target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unsupported target_state fields: {sorted(unknown_target)}",
            )
        if "category" in item.target_state and not (
            item.target_state["category"] is None
            or isinstance(item.target_state["category"], str)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_state.category must be a string or null",
            )
        if "note" in item.target_state and not (
            item.target_state["note"] is None
            or isinstance(item.target_state["note"], str)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_state.note must be a string or null",
            )

    def _core() -> tuple[BatchTxUpdateResponse, bool]:
        lock_ledger_for_materialize(db, ledger.id)
        rows = db.scalars(
            select(ReadTxProjection).where(
                ReadTxProjection.ledger_id == ledger.id,
                ReadTxProjection.sync_id.in_(sync_ids),
            )
        ).all()
        by_id = {row.sync_id: row for row in rows}
        blocked: list[BatchTxUpdateFailure] = []
        apply_items: list[tuple[BatchTxUpdateItem, ReadTxProjection]] = []
        already_applied: list[str] = []
        for item in req.updates:
            row = by_id.get(item.sync_id)
            if row is None:
                blocked.append(BatchTxUpdateFailure(sync_id=item.sync_id, reason="not_found"))
                continue
            if _state_matches(row, item.target_state):
                already_applied.append(item.sync_id)
            elif _state_matches(row, item.expected_old_state):
                apply_items.append((item, row))
            else:
                blocked.append(
                    BatchTxUpdateFailure(
                        sync_id=item.sync_id,
                        reason="precondition",
                        message="transaction changed since the approved plan",
                    )
                )
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "BATCH_TX_PRECONDITION_FAILED",
                    "blocked": [failure.model_dump() for failure in blocked],
                },
            )

        category_refs: set[tuple[str, str]] = set()
        for item, row in apply_items:
            category = item.target_state.get("category")
            if isinstance(category, str) and category.strip():
                category_refs.add((category.strip(), row.tx_type))
        category_map: dict[tuple[str, str], str] = {}
        if category_refs:
            names = {name for name, _kind in category_refs}
            kinds = {kind for _name, kind in category_refs}
            category_rows = db.scalars(
                select(UserCategoryProjection).where(
                    UserCategoryProjection.user_id == ledger.user_id,
                    UserCategoryProjection.name.in_(names),
                    UserCategoryProjection.kind.in_(kinds),
                )
            ).all()
            for category_row in category_rows:
                if not category_row.name or not category_row.kind or not category_row.sync_id:
                    continue
                key = (str(category_row.name), str(category_row.kind))
                previous = category_map.get(key)
                if previous is not None and previous != str(category_row.sync_id):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"ambiguous category: {category_row.name}",
                    )
                category_map[key] = str(category_row.sync_id)
            missing = sorted(category_refs - set(category_map))
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"category not found: {missing[0][0]}",
                )

        now = _utcnow()
        updated: list[str] = []
        emitted_change_ids: list[int] = []
        for item, row in apply_items:
            patch: dict[str, Any] = _payload_with_actor({}, current_user, ledger=ledger)
            target = item.target_state
            if "category" in target:
                category = target.get("category")
                if isinstance(category, str) and category.strip():
                    name = category.strip()
                    patch.update({
                        "category_name": name,
                        "category_kind": row.tx_type,
                        "category_id": category_map[(name, row.tx_type)],
                    })
                else:
                    patch.update({"category_name": "", "category_id": ""})
            if "note" in target:
                patch["note"] = target.get("note")
            try:
                next_snapshot = update_transaction(
                    {"items": [_projection_row_to_tx_dict(row)], "count": 1},
                    item.sync_id,
                    patch,
                )
            except (KeyError, PermissionError, ValueError) as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            new_item = next_snapshot["items"][0]
            change_row = SyncChange(
                user_id=ledger.user_id,
                ledger_id=ledger.id,
                entity_type="transaction",
                entity_sync_id=item.sync_id,
                action="upsert",
                payload_json=new_item,
                updated_at=now,
                updated_by_device_id=device_id,
                updated_by_user_id=current_user.id,
            )
            db.add(change_row)
            db.flush()
            emitted_change_ids.append(change_row.change_id)
            projection.upsert_tx(
                db,
                ledger_id=ledger.id,
                user_id=ledger.user_id,
                source_change_id=change_row.change_id,
                payload=new_item,
            )
            updated.append(item.sync_id)

        new_change_id = max(emitted_change_ids) if emitted_change_ids else snapshot_builder.latest_change_id(db, ledger.id)
        db.add(
            AuditLog(
                user_id=current_user.id,
                ledger_id=ledger.id,
                action="web_tx_batch_update",
                metadata_json={
                    "ledgerId": ledger.external_id,
                    "baseChangeId": req.base_change_id,
                    "newChangeId": new_change_id,
                    "updatedCount": len(updated),
                    "updatedIds": updated,
                },
            )
        )
        response = BatchTxUpdateResponse(
            ledger_id=ledger.external_id,
            base_change_id=req.base_change_id,
            new_change_id=new_change_id,
            server_timestamp=now,
            updated_sync_ids=updated,
            already_applied_sync_ids=already_applied,
        )
        request_hash = _hash_request(request.method, request.url.path, payload_for_ide)
        if idempotency_key:
            db.add(
                SyncPushIdempotency(
                    user_id=current_user.id,
                    device_id=device_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    response_json=response.model_dump(mode="json"),
                    created_at=now,
                    expires_at=now + timedelta(hours=24),
                )
            )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if idempotency_key:
                replayed = _load_idempotent_response(
                    db,
                    user_id=current_user.id,
                    device_id=device_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    stored = _replay_response(
                        db, user_id=current_user.id, device_id=device_id, key=str(idempotency_key)
                    )
                    if stored is not None:
                        stored.idempotency_replayed = True  # type: ignore[attr-defined]
                        return stored, True
            raise
        return response, False

    response, _did_replay = await run_in_threadpool(_core)
    if response.updated_sync_ids:
        from ...websocket_manager import broadcast_to_ledger

        await broadcast_to_ledger(
            db=db,
            ws_manager=request.app.state.ws_manager,
            ledger_id=ledger.id,
            payload={
                "type": "sync_change",
                "ledgerId": ledger.external_id,
                "serverCursor": response.new_change_id,
                "serverTimestamp": response.server_timestamp.isoformat(),
            },
        )
    return response
