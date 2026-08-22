from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config import get_settings
from src.database import Base, get_db
from src.main import app
from src.models import Ledger, LedgerMember, UserAccountProjection


@pytest.fixture()
def bill_harness(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    settings = get_settings()
    monkeypatch.setattr(settings, "bill_inbox_dir", str(tmp_path / "bill-inbox"))
    monkeypatch.setattr(settings, "attachment_max_upload_bytes", 64)
    client = TestClient(app)
    try:
        yield client, session_factory, tmp_path / "bill-inbox"
    finally:
        client.close()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def _register(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Pa$$word1!",
            "client_type": "web",
            "device_id": f"device-{email}",
            "device_name": "pytest",
            "platform": "test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_ledger(session_factory, owner_id: str, *, member_id: str | None = None, role: str = "owner") -> None:
    ledger = Ledger(
        id="ledger-db-id",
        user_id=owner_id,
        external_id="ledger-1",
        name="Main",
        currency="CNY",
    )
    session = session_factory()
    try:
        session.add(ledger)
        session.add(LedgerMember(ledger_id=ledger.id, user_id=owner_id, role="owner"))
        if member_id:
            session.add(LedgerMember(ledger_id=ledger.id, user_id=member_id, role=role))
        session.add(UserAccountProjection(user_id=owner_id, sync_id="account-1", name="Bank"))
        session.commit()
    finally:
        session.close()


def _upload(client: TestClient, token: str, filename: str, payload: bytes):
    return client.post(
        "/api/v1/bill-inbox/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"ledger_id": "ledger-1", "account_id": "account-1"},
        files={"file": (filename, payload, "application/pdf")},
    )


def _ready_entries(root):
    ready = root / "ready"
    return list(ready.iterdir()) if ready.exists() else []


def test_upload_writes_durable_ready_artifact_and_manifest(bill_harness):
    client, session_factory, root = bill_harness
    owner = _register(client, "owner-bill@example.com")
    _seed_ledger(session_factory, owner["user"]["id"])

    response = _upload(client, owner["access_token"], "statement.pdf", b"%PDF-1.7\nstatement")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    ingest_dir = root / "ready" / body["ingest_id"]
    assert ingest_dir.is_dir()
    manifest = json.loads((ingest_dir / "manifest.json").read_text(encoding="utf-8"))
    source = ingest_dir / manifest["storage_name"]
    assert source.read_bytes() == b"%PDF-1.7\nstatement"
    assert manifest["ingest_id"] == body["ingest_id"]
    assert manifest["ledger_id"] == "ledger-1"
    assert manifest["account_id"] == "account-1"
    assert manifest["uploader_user_id"] == owner["user"]["id"]
    assert manifest["original_filename"] == "statement.pdf"
    assert manifest["size"] == len(b"%PDF-1.7\nstatement")
    assert manifest["sha256"] == body["sha256"]
    assert not list((root / ".staging").iterdir())


def test_upload_rejects_invalid_account_and_viewer_without_ready_artifact(bill_harness):
    client, session_factory, root = bill_harness
    owner = _register(client, "owner-reject@example.com")
    viewer = _register(client, "viewer-reject@example.com")
    editor = _register(client, "editor-accept@example.com")
    _seed_ledger(session_factory, owner["user"]["id"], member_id=viewer["user"]["id"], role="viewer")
    session = session_factory()
    try:
        session.add(LedgerMember(ledger_id="ledger-db-id", user_id=editor["user"]["id"], role="editor"))
        session.commit()
    finally:
        session.close()

    invalid_account = client.post(
        "/api/v1/bill-inbox/upload",
        headers={"Authorization": f"Bearer {owner['access_token']}"},
        data={"ledger_id": "ledger-1", "account_id": "missing"},
        files={"file": ("statement.pdf", b"%PDF", "application/pdf")},
    )
    viewer_upload = _upload(client, viewer["access_token"], "statement.pdf", b"%PDF")
    editor_upload = _upload(client, editor["access_token"], "editor.pdf", b"%PDF")

    assert invalid_account.status_code == 404
    assert viewer_upload.status_code == 404
    assert editor_upload.status_code == 200, editor_upload.text
    assert len(_ready_entries(root)) == 1


def test_upload_rejects_unsupported_and_oversized_without_ready_artifact(bill_harness):
    client, session_factory, root = bill_harness
    owner = _register(client, "owner-invalid@example.com")
    _seed_ledger(session_factory, owner["user"]["id"])

    unsupported = _upload(client, owner["access_token"], "statement.exe", b"not a bill")
    oversized = _upload(client, owner["access_token"], "statement.pdf", b"x" * 65)

    assert unsupported.status_code == 400
    assert oversized.status_code == 413
    assert _ready_entries(root) == []
    staging = root / ".staging"
    assert not staging.exists() or not list(staging.iterdir())
