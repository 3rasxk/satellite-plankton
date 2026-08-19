"""
Unit tests for the GEE-free river-mouth lookup logic in
`src/rainfall.py` — no Earth Engine session required or contacted.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rainfall import RIVER_MOUTHS, haversine_km, nearest_river_mouth


def test_haversine_km_zero_distance():
    assert haversine_km(13.5, 100.5, 13.5, 100.5) == pytest.approx(0.0)


def test_haversine_km_known_short_distance():
    # ~1 degree of latitude is ~111 km.
    d = haversine_km(13.0, 100.5, 14.0, 100.5)
    assert d == pytest.approx(111.0, rel=0.02)


def test_nearest_river_mouth_exact_match():
    lat, lng = RIVER_MOUTHS["Chao Phraya"]
    result = nearest_river_mouth(lat, lng)
    assert result["name"] == "Chao Phraya"
    assert result["distance_km"] == pytest.approx(0.0, abs=0.1)


def test_nearest_river_mouth_picks_closest_of_four():
    # A point just off Bang Saen (Chonburi) should be closest to Bang Pakong,
    # the easternmost named river mouth.
    result = nearest_river_mouth(13.28, 100.93)
    assert result["name"] == "Bang Pakong"
    assert result["distance_km"] > 0


def test_nearest_river_mouth_returns_all_four_candidates_considered():
    # Sanity: every named mouth is reachable as "nearest" for a point
    # placed exactly on it.
    for name, (lat, lng) in RIVER_MOUTHS.items():
        result = nearest_river_mouth(lat, lng)
        assert result["name"] == name
