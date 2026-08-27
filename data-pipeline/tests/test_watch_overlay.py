"""Unit tests for watch-overlay temporal, anomaly, and tile primitives."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import watch_overlay
from src.watch_overlay import (
    _build_source_collections,
    build_ndci_watch_overlay,
    compute_watch_mask,
    seasonal_windows,
)


def test_seasonal_windows_use_five_prior_years_and_inclusive_plus_minus_15_days():
    assert seasonal_windows("2026-08-27", baseline_years=5, window_days=15) == [
        ("2025-08-12", "2025-09-12"),
        ("2024-08-12", "2024-09-12"),
        ("2023-08-12", "2023-09-12"),
        ("2022-08-12", "2022-09-12"),
        ("2021-08-12", "2021-09-12"),
    ]


def test_seasonal_windows_cross_calendar_years_and_clamp_leap_day():
    assert seasonal_windows("2026-01-05", baseline_years=1, window_days=15) == [
        ("2024-12-21", "2025-01-21")
    ]
    assert seasonal_windows("2024-02-29", baseline_years=1, window_days=15) == [
        ("2023-02-13", "2023-03-16")
    ]


def test_compute_watch_mask_keeps_only_valid_z_at_or_above_threshold():
    mask = compute_watch_mask(
        latest=[0.40, 0.40, 0.40, 0.40, np.nan],
        seasonal_mean=[0.10, 0.10, 0.10, 0.10, 0.10],
        seasonal_std=[0.20, 0.20, 0.0, 0.20, 0.20],
        observation_count=[5, 5, 8, 4, 8],
        threshold_z=1.5,
        min_observations=5,
    )
    assert mask.tolist() == [True, True, False, False, False]


class FakeCollection:
    def __init__(self, windows):
        self.windows = windows

    def merge(self, other):
        return FakeCollection(self.windows + other.windows)


def test_current_and_baseline_use_identical_masked_ndci_builder():
    """Fails if current or any baseline bypasses the shared preprocessing path."""
    calls = []

    def fake_builder(start, end, *, region, water_mask, output_scale_m):
        calls.append((start, end, region, water_mask, output_scale_m))
        return FakeCollection([(start, end)])

    current, baseline = _build_source_collections(
        current_window=("2026-07-29", "2026-08-28"),
        baseline_windows=[("2025-08-12", "2025-09-12"), ("2024-08-12", "2024-09-12")],
        region="scan-region",
        water_mask="connected-water",
        output_scale_m=10,
        collection_builder=fake_builder,
    )

    assert current.windows == [("2026-07-29", "2026-08-28")]
    assert baseline.windows == [("2025-08-12", "2025-09-12"), ("2024-08-12", "2024-09-12")]
    assert all(call[2:] == ("scan-region", "connected-water", 10) for call in calls)


def test_gulf_connectivity_cost_and_seed_share_the_jrc_water_grid(monkeypatch):
    """Fails if cumulative cost can fall back to a default-grid raster."""
    class FakeImage:
        def __init__(self, name, graph):
            self.name = name
            self.graph = graph
            self.self_masked = False
            self.reprojected_to = None

        def select(self, band):
            assert band == "occurrence"
            return self

        def clip(self, region):
            assert region == "scan-region"
            return self

        def gte(self, threshold):
            assert threshold == 50.0
            return FakeImage("persistent-water", self.graph)

        def byte(self):
            return self

        def paint(self, features, value):
            assert features == [("feature", (100.0, 13.0))]
            assert value == 1
            return self

        def selfMask(self):
            self.self_masked = True
            return self

        def projection(self):
            return f"{self.name}-projection"

        def reproject(self, *, crs):
            self.reprojected_to = crs
            return self

        def cumulativeCost(self, *, source, maxDistance, geodeticDistance):
            self.graph.cumulative_cost = {
                "cost": self,
                "source": source,
                "max_distance": maxDistance,
                "geodetic_distance": geodeticDistance,
            }
            return FakeImage("reached", self.graph)

        def mask(self):
            return self

        def updateMask(self, mask):
            return self

        def rename(self, name):
            assert name == "gulf_connected_water"
            return self

    class FakeImageFactory:
        def __init__(self, graph):
            self.graph = graph

        def __call__(self, value):
            return FakeImage("occurrence" if isinstance(value, str) else "seed", self.graph)

        def constant(self, value):
            return FakeImage("constant", self.graph)

    class FakeEE:
        def __init__(self):
            self.cumulative_cost = None
            self.Image = FakeImageFactory(self)
            self.Geometry = type(
                "Geometry", (), {"Point": staticmethod(lambda coordinates: tuple(coordinates))}
            )

        @staticmethod
        def Feature(geometry):
            return ("feature", geometry)

        @staticmethod
        def FeatureCollection(features):
            return features

    fake_ee = FakeEE()
    monkeypatch.setattr(watch_overlay, "ee", fake_ee)

    watch_overlay._build_gulf_connected_water_mask(
        "scan-region",
        water_occurrence_pct=50.0,
        gulf_seed_points=[[13.0, 100.0]],
    )

    assert fake_ee.cumulative_cost["cost"].name == "persistent-water"
    assert fake_ee.cumulative_cost["cost"].self_masked
    assert fake_ee.cumulative_cost["source"].reprojected_to == "persistent-water-projection"


def test_watch_tile_metadata_reports_grid_resolution_water_mask_and_caveat(monkeypatch):
    """Fails if the returned tile contract misstates its scientific limits."""
    class FakeValue:
        def __init__(self, value):
            self.value = value

        def getInfo(self):
            return self.value

    class FakeCurrent:
        def size(self):
            return FakeValue(1)

        def aggregate_max(self, property_name):
            assert property_name == "system:time_start"
            return FakeValue(1_785_369_600_000)

    class FakeStyled:
        def getMapId(self, visualization):
            assert visualization == {}
            return {
                "mapid": "watch-map-id",
                "tile_fetcher": type("TileFetcher", (), {"url_format": "https://tiles/{z}/{x}/{y}"})(),
            }

    monkeypatch.setattr(watch_overlay, "initialize_ee", lambda: None)
    monkeypatch.setattr(watch_overlay, "upper_gulf_scan_ee_polygon", lambda: "scan-region")
    monkeypatch.setattr(
        watch_overlay, "_build_gulf_connected_water_mask", lambda *args, **kwargs: "water-mask"
    )
    monkeypatch.setattr(
        watch_overlay,
        "_build_source_collections",
        lambda **kwargs: (FakeCurrent(), "baseline-collection"),
    )
    monkeypatch.setattr(watch_overlay, "_build_watch_image", lambda **kwargs: FakeStyled())

    result = build_ndci_watch_overlay(
        "2026-08-27",
        threshold_z=2.0,
        latest_window_days=30,
        baseline_years=5,
        seasonal_window_days=15,
        min_baseline_observations=3,
        water_occurrence_pct=50.0,
        gulf_seed_points=[[13.0, 100.0]],
        output_scale_m=10,
        effective_resolution_m=20,
        color="#ff00aa",
    )

    assert result["output_grid_m"] == 10
    assert result["effective_resolution_m"] == 20
    assert result["water_mask"] == "gulf_connected_historical_surface_water"
    assert "not" in result["caveat"].lower()
    assert "bloom" in result["caveat"].lower()
    assert result["color"] == "#ff00aa"
