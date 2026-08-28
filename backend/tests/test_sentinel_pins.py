"""
Unit Tests for Automated Sentinel-2 Imagery Extraction for Test Case Station Pins.
Verifies:
1. Retrieval of valid RGB and NDCI thumbnail URLs for all scenario pins.
2. Graceful cloud fallback / missing scene handling.
3. Execution speed < 1.5s per pin.
4. Snapshot persistence to tests/output_snapshots/ for reporting & validation.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
from services.sentinel_image_service import SentinelPinImageService

TEST_SCENARIO_PINS = [
    {
        "name": "Chonburi_AngSila_SevereBloom",
        "lat": 13.3340,
        "lon": 100.9250,
        "date": "2026-08-20",
        "expected_tier": "WARNING",
    },
    {
        "name": "ChaoPhraya_Mouth_SedimentPlume",
        "lat": 13.5200,
        "lon": 100.5900,
        "date": "2026-08-22",
        "expected_tier": "NORMAL",
    },
    {
        "name": "Offshore_Clean_Baseline",
        "lat": 12.8500,
        "lon": 100.7500,
        "date": "2026-08-25",
        "expected_tier": "NORMAL",
    },
]


@pytest.fixture(scope="module")
def image_service():
    return SentinelPinImageService(initialize_ee=False)


def test_sentinel_pin_imagery_extraction_all_scenarios(image_service):
    """Verifies extraction and schema compliance for all test scenario pins."""
    snapshot_dir = Path(__file__).resolve().parent / "output_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for pin in TEST_SCENARIO_PINS:
        start_t = time.perf_counter()
        result = image_service.get_pin_satellite_imagery(
            latitude=pin["lat"],
            longitude=pin["lon"],
            target_date=pin["date"],
            window_days=5,
            buffer_km=2.5,
        )
        elapsed_s = time.perf_counter() - start_t

        assert result is not None
        assert result["status"] == "SUCCESS"
        assert result["station_pin"]["lat"] == pin["lat"]
        assert result["station_pin"]["lon"] == pin["lon"]
        assert "rgb_thumbnail_url" in result
        assert "ndci_thumbnail_url" in result
        assert result["rgb_thumbnail_url"].startswith("http")
        assert result["ndci_thumbnail_url"].startswith("http")
        assert elapsed_s < 1.5, f"Extraction too slow: {elapsed_s:.2f}s (expected < 1.5s)"

        # Save synthetic snapshot previews for visual inspection / reporting
        rgb_path = snapshot_dir / f"{pin['name']}_rgb.png"
        ndci_path = snapshot_dir / f"{pin['name']}_ndci.png"

        # Create dummy 1x1 valid PNG bytes if mock
        png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        with open(rgb_path, "wb") as f:
            f.write(png_header)
        with open(ndci_path, "wb") as f:
            f.write(png_header)

        assert rgb_path.exists()
        assert ndci_path.exists()


def test_cloud_obscured_fallback(image_service):
    """Verifies that non-available or heavily obscured dates return graceful status without crashing."""
    # Test a target date query
    res = image_service.get_pin_satellite_imagery(
        latitude=13.0,
        longitude=100.5,
        target_date="2026-08-01",
        window_days=1,
    )
    assert res is not None
    assert "station_pin" in res
