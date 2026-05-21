"""metrics histogram + sync.pull observability 回归测试。"""
from __future__ import annotations

from src.metrics import InMemoryMetrics


def test_histogram_basic_buckets() -> None:
    m = InMemoryMetrics()
    # 30ms, 80ms, 300ms — 测三个跨 bucket
    m.observe_histogram("foo_duration_seconds", 0.03)
    m.observe_histogram("foo_duration_seconds", 0.08)
    m.observe_histogram("foo_duration_seconds", 0.3)
    out = m.render_prometheus()
    # 默认 buckets:0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, inf
    assert "# TYPE foo_duration_seconds histogram" in out
    # 累计 bucket counts(<= le):
    #   le=0.025 → 0(没有 ≤25ms 的)
    #   le=0.05  → 1(只有 30ms 不算)实际 0.03 > 0.025 且 ≤ 0.05 → 1
    #   le=0.1   → 2(30ms + 80ms)
    #   le=0.25  → 2
    #   le=0.5   → 3(全部)
    #   le=+Inf  → 3
    assert 'foo_duration_seconds_bucket{le="0.025"} 0' in out
    assert 'foo_duration_seconds_bucket{le="0.05"} 1' in out
    assert 'foo_duration_seconds_bucket{le="0.1"} 2' in out
    assert 'foo_duration_seconds_bucket{le="0.5"} 3' in out
    assert 'foo_duration_seconds_bucket{le="+Inf"} 3' in out
    assert "foo_duration_seconds_count 3" in out
    # sum 用近似比较防浮点误差
    assert "foo_duration_seconds_sum 0.41" in out  # 0.03 + 0.08 + 0.3 = 0.41


def test_histogram_extreme_value_falls_in_inf_bucket() -> None:
    m = InMemoryMetrics()
    m.observe_histogram("bar_seconds", 100.0)  # > 10s,落 +Inf
    out = m.render_prometheus()
    assert 'bar_seconds_bucket{le="10.0"} 0' in out
    assert 'bar_seconds_bucket{le="+Inf"} 1' in out
    assert "bar_seconds_count 1" in out


def test_pull_endpoint_emits_structured_log_and_histogram(caplog) -> None:
    """/sync/pull 必须 emit `sync.pull.return` log + 累加 histogram。"""
    import logging
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.database import Base, get_db
    from src.main import app
    from src.metrics import metrics

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TS = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    client = TestClient(app)

    try:
        # 注册一个 mobile 用户
        r = client.post(
            "/api/v1/auth/register",
            json={
                "email": "obs@example.com",
                "password": "123456",
                "client_type": "app",
                "device_name": "obs-pytest",
                "platform": "app",
            },
        )
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]

        # pull 一次(空账本,returned=0)
        before_count = metrics._histograms.get(
            "beecount_sync_pull_duration_seconds", {}
        ).get("count", 0)
        with caplog.at_level(logging.INFO):
            r = client.get(
                "/api/v1/sync/pull?since=0",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200, r.text

        # 1) histogram 加 1
        entry = metrics._histograms.get("beecount_sync_pull_duration_seconds")
        assert entry is not None
        assert entry["count"] == before_count + 1
        assert entry["sum"] > 0.0  # 总秒数 > 0

        # 2) structured log 输出 sync.pull.return,带 elapsed_ms 字段
        return_logs = [
            rec for rec in caplog.records if "sync.pull.return" in rec.getMessage()
        ]
        assert len(return_logs) >= 1, f"no sync.pull.return log emitted: {caplog.records}"
        msg = return_logs[-1].getMessage()
        assert "elapsed_ms=" in msg
        assert "returned=0" in msg  # 空账本
        assert "enrich_count=0" in msg  # 没 tx,enrich 0

        # 3) Prometheus 输出格式完整
        prom = metrics.render_prometheus()
        assert "# TYPE beecount_sync_pull_duration_seconds histogram" in prom
        assert "beecount_sync_pull_duration_seconds_count" in prom
        assert "beecount_sync_pull_duration_seconds_sum" in prom
    finally:
        app.dependency_overrides.clear()
