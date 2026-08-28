"""
Unit tests for Alert Service Latency, In-Memory Caching, and Lightweight Payload Schema.
Verifies:
1. Latency Check: < 150ms on cache hit.
2. Lightweight payload schema compliance.
3. Cache invalidation on clear_cache().
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
import pytest

from src.main import app
from src.services.cache_service import clear_cache, get_cached, set_cached


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_cache_service_crud_and_ttl():
    """Verifies basic cache set, get, and expiration."""
    clear_cache()
    assert get_cached("test_key") is None

    set_cached("test_key", {"status": "ok"}, ttl_seconds=1)
    assert get_cached("test_key") == {"status": "ok"}

    time.sleep(1.1)
    assert get_cached("test_key") is None


def test_alerts_endpoint_schema_and_lightweight_payload(client):
    """Verifies /api/alerts returns correct lightweight schema with active stations."""
    clear_cache()
    response = client.get("/api/alerts")
    assert response.status_code == 200

    data = response.json()
    assert "updated_at" in data
    assert "total_active_alerts" in data
    assert "highest_risk_tier" in data
    assert "stations" in data
    assert isinstance(data["stations"], list)

    for st in data["stations"]:
        assert "site_id" in st
        assert "name" in st
        assert "risk_tier" in st
        assert "confidence" in st
        assert "coordinates" in st
        assert len(st["coordinates"]) == 2


def test_alerts_endpoint_latency_benchmark(client):
    """
    Latency Verification:
    1st call warms cache, subsequent calls must complete in < 150ms (typically < 10ms).
    """
    # Warmup / initial cache population
    client.get("/api/alerts")

    # Benchmark 20 iterations
    latencies = []
    for _ in range(20):
        start = time.perf_counter()
        resp = client.get("/api/alerts")
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert resp.status_code == 200
        latencies.append(elapsed_ms)

    avg_latency = sum(latencies) / len(latencies)
    print(f"\n[ALERTS API LATENCY] Average cached response latency: {avg_latency:.2f} ms")
    assert avg_latency < 150.0, f"Expected < 150ms, got {avg_latency:.2f} ms"
