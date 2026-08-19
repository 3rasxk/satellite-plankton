"""
Unit tests for the GEE-free MODIS time-series parsing and day-of-year
climatology logic in `src/modis.py`, exercised entirely with synthetic
`getRegion`-shaped data — no Earth Engine session required or contacted.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.modis import day_of_year_climatology, parse_get_region_rows


def _ms(date_str: str) -> int:
    # UTC-anchored on purpose: production code (`parse_get_region_rows`)
    # converts the millisecond timestamps GEE returns via
    # `datetime.utcfromtimestamp`, so the synthetic timestamps here must
    # be built the same way regardless of the machine's local timezone.
    from datetime import datetime, timezone

    return int(
        datetime.strptime(date_str, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
        * 1000
    )


def test_parse_get_region_rows_empty():
    assert parse_get_region_rows([], "chlor_a") == []


def test_parse_get_region_rows_basic():
    header = ["id", "longitude", "latitude", "time", "chlor_a"]
    rows = [
        header,
        ["img1", 100.5, 13.5, _ms("2020-01-01"), 2.5],
        ["img2", 100.5, 13.5, _ms("2020-01-02"), None],  # masked/cloud pixel
        ["img3", 100.5, 13.5, _ms("2020-01-03"), 3.1],
    ]
    parsed = parse_get_region_rows(rows, "chlor_a")
    assert parsed == [
        {"date": "2020-01-01", "chlor_a": 2.5},
        {"date": "2020-01-03", "chlor_a": 3.1},
    ]


def test_parse_get_region_rows_dedupes_same_day_by_mean():
    header = ["id", "longitude", "latitude", "time", "chlor_a"]
    rows = [
        header,
        ["img1", 100.5, 13.5, _ms("2020-01-01"), 2.0],
        ["img2", 100.5, 13.5, _ms("2020-01-01"), 4.0],  # overlapping swath, same day
    ]
    parsed = parse_get_region_rows(rows, "chlor_a")
    assert parsed == [{"date": "2020-01-01", "chlor_a": 3.0}]


def test_parse_get_region_rows_sorts_ascending():
    header = ["id", "longitude", "latitude", "time", "chlor_a"]
    rows = [
        header,
        ["img1", 100.5, 13.5, _ms("2020-03-01"), 1.0],
        ["img2", 100.5, 13.5, _ms("2020-01-01"), 2.0],
    ]
    parsed = parse_get_region_rows(rows, "chlor_a")
    assert [r["date"] for r in parsed] == ["2020-01-01", "2020-03-01"]


def test_parse_get_region_rows_missing_column_raises():
    with pytest.raises(ValueError):
        parse_get_region_rows([["id", "longitude", "latitude", "time"]], "chlor_a")


def test_day_of_year_climatology_basic():
    # Same day-of-year (Jan 15) across three years, plus one far-off date.
    series = [
        {"date": "2018-01-15", "chlor_a": 2.0},
        {"date": "2019-01-15", "chlor_a": 4.0},
        {"date": "2020-01-15", "chlor_a": 6.0},
        {"date": "2020-07-01", "chlor_a": 100.0},  # should not match
    ]
    result = day_of_year_climatology(series, "chlor_a", "2021-01-15", window_days=3)
    assert result["n"] == 3
    assert result["mean"] == pytest.approx(4.0)


def test_day_of_year_climatology_wraps_year_boundary():
    # Dec 30 vs Jan 2 are 3 days apart across the year boundary.
    series = [
        {"date": "2019-12-30", "chlor_a": 1.0},
        {"date": "2020-01-02", "chlor_a": 3.0},
    ]
    result = day_of_year_climatology(series, "chlor_a", "2021-01-01", window_days=3)
    assert result["n"] == 2
    assert result["mean"] == pytest.approx(2.0)


def test_day_of_year_climatology_empty_series_returns_none():
    assert day_of_year_climatology([], "chlor_a", "2021-01-01") is None


def test_day_of_year_climatology_no_match_in_window_returns_none():
    series = [{"date": "2019-06-15", "chlor_a": 5.0}]
    result = day_of_year_climatology(series, "chlor_a", "2021-01-01", window_days=2)
    assert result is None
