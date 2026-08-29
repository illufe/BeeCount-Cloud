"""Focused coverage for the bounded transaction information-update batch."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base, get_db
from src.main import app
from src.models import ReadTxProjection, SyncChange


def _setup(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), sessions


def _register(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "batch-update@example.com",
            "password": "123456",
            "client_type": "web",
            "device_name": "pytest-web",
            "platform": "web",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_batch_update_is_atomic_preconditioned_and_idempotent(monkeypatch) -> None:
    client, sessions = _setup(monkeypatch)
    try:
        registration = _register(client)
        token = registration["access_token"]
        headers = {"Authorization": f"Bearer {token}", "X-Device-ID": "pytest"}
        ledger_response = client.post(
            "/api/v1/write/ledgers",
            json={"ledger_name": "Batch", "currency": "CNY"},
            headers=headers,
        )
        assert ledger_response.status_code == 200, ledger_response.text
        ledger = ledger_response.json()["entity_id"]

        category_response = client.post(
            f"/api/v1/write/ledgers/{ledger}/categories",
            json={"base_change_id": 0, "name": "BatchFood", "kind": "expense"},
            headers=headers,
        )
        assert category_response.status_code == 200, category_response.text

        sync_ids = []
        for amount, happened_at in ((12.5, "2026-08-23T00:00:00Z"), (8.5, "2026-08-24T00:00:00Z")):
            tx_response = client.post(
                f"/api/v1/write/ledgers/{ledger}/transactions",
                json={
                    "base_change_id": 0,
                    "tx_type": "expense",
                    "amount": amount,
                    "happened_at": happened_at,
                },
                headers=headers,
            )
            assert tx_response.status_code == 200, tx_response.text
            sync_ids.append(tx_response.json()["entity_id"])
        first_sync_id, second_sync_id = sync_ids

        body = {
            "base_change_id": 0,
            "updates": [
                {
                    "sync_id": first_sync_id,
                    "expected_old_state": {"category": None, "tags": ""},
                    "target_state": {"category": "BatchFood", "note": "batch-1"},
                },
                {
                    "sync_id": second_sync_id,
                    "expected_old_state": {"category": None, "tags": ""},
                    "target_state": {"category": "BatchFood", "note": "batch-2"},
                },
            ],
        }

        # A precondition drift in the second item must prevent the first item
        # from being applied: the request is one atomic transaction.
        conflict_body = {
            **body,
            "updates": [
                body["updates"][0],
                {
                    **body["updates"][1],
                    "expected_old_state": {"category": "Drifted", "tags": ""},
                },
            ],
        }
        with sessions() as db:
            before_conflict_changes = db.scalar(
                select(func.count()).select_from(SyncChange).where(
                    SyncChange.entity_type == "transaction",
                )
            )
        conflict = client.post(
            f"/api/v1/write/ledgers/{ledger}/transactions/batch/update",
            json=conflict_body,
            headers={**headers, "Idempotency-Key": "batch-update-conflict"},
        )
        assert conflict.status_code == 409, conflict.text

        with sessions() as db:
            first_row = db.scalar(
                select(ReadTxProjection).where(ReadTxProjection.sync_id == first_sync_id)
            )
            second_row = db.scalar(
                select(ReadTxProjection).where(ReadTxProjection.sync_id == second_sync_id)
            )
            assert first_row is not None and second_row is not None
            assert first_row.category_name is None
            assert second_row.category_name is None
            assert db.scalar(
                select(func.count()).select_from(SyncChange).where(
                    SyncChange.entity_type == "transaction",
                )
            ) == before_conflict_changes

        first = client.post(
            f"/api/v1/write/ledgers/{ledger}/transactions/batch/update",
            json=body,
            headers={**headers, "Idempotency-Key": "batch-update-1"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["updated_sync_ids"] == [first_sync_id, second_sync_id]

        with sessions() as db:
            first_row = db.scalar(
                select(ReadTxProjection).where(ReadTxProjection.sync_id == first_sync_id)
            )
            second_row = db.scalar(
                select(ReadTxProjection).where(ReadTxProjection.sync_id == second_sync_id)
            )
            assert first_row is not None and second_row is not None
            assert first_row.category_name == "BatchFood"
            assert first_row.category_sync_id
            assert first_row.amount == 12.5
            assert first_row.tx_type == "expense"
            assert first_row.note == "batch-1"
            assert second_row.category_name == "BatchFood"
            assert second_row.category_sync_id == first_row.category_sync_id
            assert second_row.amount == 8.5
            assert second_row.tx_type == "expense"
            assert second_row.note == "batch-2"
            change_counts = {
                sync_id: db.scalar(
                    select(func.count()).select_from(SyncChange).where(
                        SyncChange.entity_type == "transaction",
                        SyncChange.entity_sync_id == sync_id,
                    )
                )
                for sync_id in sync_ids
            }

        replay = client.post(
            f"/api/v1/write/ledgers/{ledger}/transactions/batch/update",
            json=body,
            headers={**headers, "Idempotency-Key": "batch-update-1"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["idempotency_replayed"] is True
        with sessions() as db:
            assert {
                sync_id: db.scalar(
                    select(func.count()).select_from(SyncChange).where(
                        SyncChange.entity_type == "transaction",
                        SyncChange.entity_sync_id == sync_id,
                    )
                )
                for sync_id in sync_ids
            } == change_counts

        invalid = {
            **body,
            "updates": [{
                **body["updates"][0],
                "target_state": {"category": 123},
            }],
        }
        invalid_response = client.post(
            f"/api/v1/write/ledgers/{ledger}/transactions/batch/update",
            json=invalid,
            headers={**headers, "Idempotency-Key": "batch-update-invalid-type"},
        )
        assert invalid_response.status_code == 400, invalid_response.text
        with sessions() as db:
            row = db.scalar(
                select(ReadTxProjection).where(ReadTxProjection.sync_id == first_sync_id)
            )
            assert row is not None
            assert row.category_name == "BatchFood"
            assert row.note == "batch-1"
            assert {
                sync_id: db.scalar(
                    select(func.count()).select_from(SyncChange).where(
                        SyncChange.entity_type == "transaction",
                        SyncChange.entity_sync_id == sync_id,
                    )
                )
                for sync_id in sync_ids
            } == change_counts
    finally:
        app.dependency_overrides.clear()
