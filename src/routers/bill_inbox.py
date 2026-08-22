from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user, require_any_scopes
from ..ledger_access import ROLE_EDITOR, ROLE_OWNER, get_accessible_ledger_by_external_id
from ..models import Ledger, User, UserAccountProjection
from ..security import SCOPE_APP_WRITE, SCOPE_WEB_WRITE

router = APIRouter()
_WRITE_SCOPE_DEP = require_any_scopes(SCOPE_APP_WRITE, SCOPE_WEB_WRITE)
_ALLOWED_SUFFIXES = {".pdf", ".csv", ".tsv", ".xlsx"}
_CHUNK_BYTES = 1024 * 1024


class BillInboxUploadOut(BaseModel):
    status: str
    ingest_id: str
    ledger_id: str
    account_id: str
    original_filename: str
    content_type: str
    size: int
    sha256: str
    uploaded_at: datetime


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _safe_original_filename(raw: str | None) -> str:
    value = Path(raw or "").name.strip()
    return (value[:255] or "statement")


def _resolve_account(
    db: Session,
    *,
    ledger_id: str,
    account_id: str,
    current_user: User,
) -> Ledger:
    if not ledger_id.strip() or not account_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ledger and account are required")
    row = get_accessible_ledger_by_external_id(
        db,
        user_id=current_user.id,
        ledger_external_id=ledger_id,
        roles={ROLE_OWNER, ROLE_EDITOR},
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ledger not found")
    ledger, _role = row
    account = db.scalar(
        select(UserAccountProjection).where(
            UserAccountProjection.user_id == ledger.user_id,
            UserAccountProjection.sync_id == account_id,
        )
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return ledger


@router.post("/upload", response_model=BillInboxUploadOut)
async def upload_bill(
    ledger_id: str = Form(...),
    account_id: str = Form(...),
    file: UploadFile = File(...),
    _scopes: set[str] = Depends(_WRITE_SCOPE_DEP),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BillInboxUploadOut:
    ledger = _resolve_account(
        db,
        ledger_id=ledger_id,
        account_id=account_id,
        current_user=current_user,
    )
    original_filename = _safe_original_filename(file.filename)
    suffix = Path(original_filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported bill format; use PDF, CSV, TSV, or XLSX",
        )

    settings = get_settings()
    root = Path(settings.bill_inbox_dir).expanduser()
    staging_root = root / ".staging"
    ready_root = root / "ready"
    ingest_id = uuid4().hex
    staging_dir = staging_root / ingest_id
    ready_dir = ready_root / ingest_id
    committed = False
    uploaded_at = datetime.now(timezone.utc)
    content_type = file.content_type or "application/octet-stream"
    storage_name = f"source-{ingest_id}{suffix}"
    source_path = staging_dir / storage_name

    try:
        staging_root.mkdir(parents=True, exist_ok=True)
        ready_root.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir()
        digest = hashlib.sha256()
        size = 0
        with source_path.open("wb") as target:
            while True:
                chunk = await file.read(_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.attachment_max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Bill upload too large",
                    )
                digest.update(chunk)
                target.write(chunk)
            if size == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Bill file is empty",
                )
            target.flush()
            os.fsync(target.fileno())

        manifest = {
            "ingest_id": ingest_id,
            "ledger_id": ledger.external_id,
            "account_id": account_id,
            "uploader_user_id": current_user.id,
            "original_filename": original_filename,
            "content_type": content_type,
            "size": size,
            "sha256": digest.hexdigest(),
            "uploaded_at": uploaded_at.isoformat(),
            "storage_name": storage_name,
        }
        manifest_path = staging_dir / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as target:
            json.dump(manifest, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        _fsync_directory(staging_dir)
        os.replace(staging_dir, ready_dir)
        _fsync_directory(ready_root)
        committed = True
    finally:
        if not committed:
            shutil.rmtree(staging_dir, ignore_errors=True)
            shutil.rmtree(ready_dir, ignore_errors=True)

    return BillInboxUploadOut(
        status="ready",
        ingest_id=ingest_id,
        ledger_id=ledger.external_id,
        account_id=account_id,
        original_filename=original_filename,
        content_type=content_type,
        size=size,
        sha256=digest.hexdigest(),
        uploaded_at=uploaded_at,
    )
