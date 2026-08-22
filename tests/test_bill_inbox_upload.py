from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config import get_settings
from src.database import Base, get_db
from src.main import app
from src.models import Ledger, LedgerMember, UserAccountProjection
from src.routers.bill_inbox import _commit_ready_upload


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


def _seed_second_scope(session_factory, owner_id: str) -> None:
    session = session_factory()
    try:
        session.add(
            Ledger(
                id="ledger-db-id-2",
                user_id=owner_id,
                external_id="ledger-2",
                name="Second",
                currency="CNY",
            )
        )
        session.add(LedgerMember(ledger_id="ledger-db-id-2", user_id=owner_id, role="owner"))
        session.add(UserAccountProjection(user_id=owner_id, sync_id="account-2", name="Second bank"))
        session.commit()
    finally:
        session.close()


def _upload(
    client: TestClient,
    token: str,
    filename: str,
    payload: bytes,
    *,
    ledger_id: str = "ledger-1",
    account_id: str = "account-1",
):
    return client.post(
        "/api/v1/bill-inbox/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"ledger_id": ledger_id, "account_id": account_id},
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


def test_sequential_duplicate_returns_existing_ingest_without_new_ready_entry(bill_harness):
    client, session_factory, root = bill_harness
    owner = _register(client, "owner-duplicate@example.com")
    _seed_ledger(session_factory, owner["user"]["id"])
    payload = b"%PDF-1.7\nduplicate"

    first = _upload(client, owner["access_token"], "statement.pdf", payload)
    second = _upload(client, owner["access_token"], "renamed.pdf", payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "ready"
    assert second.json()["status"] == "duplicate"
    assert second.json()["ingest_id"] == first.json()["ingest_id"]
    assert len(_ready_entries(root)) == 1
    assert not list((root / ".staging").iterdir())


def test_duplicate_fingerprint_is_scoped_to_ledger_and_account(bill_harness):
    client, session_factory, root = bill_harness
    owner = _register(client, "owner-scope@example.com")
    _seed_ledger(session_factory, owner["user"]["id"])
    _seed_second_scope(session_factory, owner["user"]["id"])
    payload = b"%PDF-1.7\nscoped"

    first = _upload(client, owner["access_token"], "statement.pdf", payload)
    other_account = _upload(
        client,
        owner["access_token"],
        "statement.pdf",
        payload,
        account_id="account-2",
    )
    other_ledger = _upload(
        client,
        owner["access_token"],
        "statement.pdf",
        payload,
        ledger_id="ledger-2",
        account_id="account-2",
    )

    assert first.json()["status"] == "ready"
    assert other_account.json()["status"] == "ready"
    assert other_ledger.json()["status"] == "ready"
    assert len(_ready_entries(root)) == 3


def test_malformed_manifest_is_ignored_during_duplicate_scan(bill_harness):
    client, session_factory, root = bill_harness
    owner = _register(client, "owner-malformed@example.com")
    _seed_ledger(session_factory, owner["user"]["id"])
    malformed = root / "ready" / "malformed"
    malformed.mkdir(parents=True)
    (malformed / "manifest.json").write_text("{not-json", encoding="utf-8")

    response = _upload(client, owner["access_token"], "statement.pdf", b"%PDF")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
    assert len(_ready_entries(root)) == 2


def test_concurrent_identical_commits_create_one_ready_entry(bill_harness):
    _, _, root = bill_harness
    (root / ".staging").mkdir(parents=True)
    (root / "ready").mkdir(parents=True)

    def stage(ingest_id: str) -> tuple[Path, Path]:
        staging = root / ".staging" / ingest_id
        staging.mkdir()
        (staging / "source.pdf").write_bytes(b"same")
        (staging / "manifest.json").write_text(
            json.dumps(
                {
                    "ingest_id": ingest_id,
                    "ledger_id": "ledger-1",
                    "account_id": "account-1",
                    "sha256": "a" * 64,
                }
            ),
            encoding="utf-8",
        )
        return staging, root / "ready" / ingest_id

    staged = [stage("ingest-a"), stage("ingest-b")]

    def commit(paths: tuple[Path, Path]) -> str | None:
        staging, ready = paths
        return _commit_ready_upload(
            root,
            staging_dir=staging,
            ready_dir=ready,
            ledger_id="ledger-1",
            account_id="account-1",
            sha256="a" * 64,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, staged))

    assert sum(result is None for result in results) == 1
    assert sum(result is not None for result in results) == 1
    assert len(_ready_entries(root)) == 1


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
