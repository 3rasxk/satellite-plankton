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


class OperationGraph:
    def __init__(self):
        self.selected = []
        self.operations = []
        self.combined_with_connected_water = False
        self.final_mask = None


class FakeMaskValue:
    def __init__(self, graph, name, expression=None):
        self.graph = graph
        self.name = name
        self.expression = name if expression is None else expression

    def eq(self, value):
        self.graph.operations.append(("eq", self.name, value))
        return FakeMaskValue(self.graph, self.name, ("eq", self.expression, value))

    def bitwiseAnd(self, value):
        self.graph.operations.append(("bitwiseAnd", self.name, value))
        return FakeMaskValue(
            self.graph, self.name, ("bitwiseAnd", self.expression, value)
        )

    def And(self, other):
        expression = ("And", self.expression, other.expression)
        result = FakeMaskValue(self.graph, "combined-mask", expression)
        self.graph.combined_with_connected_water = "connected-water" in str(expression)
        self.graph.final_mask = result
        return result

    def mask(self):
        return self

    def reduce(self, reducer):
        assert reducer == "minimum"
        return FakeMaskValue(self.graph, "source-valid")


class FakeMaskImage:
    def __init__(self, graph, bands):
        self.graph = graph
        self.bands = bands

    def select(self, bands):
        if isinstance(bands, str):
            self.graph.selected.append(bands)
            return FakeMaskValue(self.graph, bands)
        assert bands == ["B2", "B3", "B4", "B5", "B6"]
        return FakeMaskValue(self.graph, "source-bands")


class FakeDailyImage:
    def __init__(self, graph, name):
        self.graph = graph
        self.name = name

    def median(self):
        self.graph.operations.append(("median", self.name))
        return FakeDailyImage(self.graph, "daily-ndci")

    def rename(self, name):
        self.graph.operations.append(("rename", self.name, name))
        self.name = name
        return self

    def toFloat(self):
        self.graph.operations.append(("toFloat", self.name))
        return self

    def mask(self):
        return FakeDailyImage(self.graph, f"{self.name}-mask")

    def updateMask(self, mask):
        self.graph.operations.append(("updateMask", self.name, mask.name))
        return self

    def addBands(self, other):
        self.graph.operations.append(("addBands", self.name, other.name))
        return self

    def set(self, name, value):
        self.graph.operations.append(("set", name, value))
        return self


class FakeDailyCollection:
    def __init__(self, graph):
        self.graph = graph

    def filterDate(self, start, end):
        self.graph.operations.append(("filterDate", start, end))
        return self

    def select(self, bands):
        self.graph.selected.append(bands)
        return FakeDailyImage(self.graph, "ndci")

    def size(self):
        return type("FakeSize", (), {"gt": staticmethod(lambda value: True)})()


class FakeDailyImageFactory:
    def __init__(self, graph):
        self.graph = graph

    def __call__(self, image):
        return image

    def constant(self, value):
        return FakeDailyImage(self.graph, str(value))


class FakeTrendCount(FakeDailyImage):
    def gte(self, value):
        self.graph.operations.append(("gte", self.name, value))
        return FakeDailyImage(self.graph, "count-mask")


class FakeTrendImage(FakeDailyImage):
    def count(self):
        self.graph.operations.append(("count", self.name))
        return FakeTrendCount(self.graph, "trend_observation_count")

    def reduce(self, reducer):
        self.graph.operations.append(("reduce", self.name, reducer))
        return FakeTrendImage(self.graph, "linear-fit")

    def select(self, band):
        assert band == "scale"
        return FakeTrendImage(self.graph, "scale")

    def updateMask(self, mask):
        self.graph.operations.append(("updateMask", self.name, mask.name))
        return self


class FakeTrendCollection:
    def __init__(self, graph):
        self.graph = graph

    def select(self, bands):
        self.graph.selected.append(bands)
        return FakeTrendImage(self.graph, "ndci" if bands == "ndci" else "fit-input")


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


def test_usable_water_mask_requires_scl_water_and_clear_qa60(monkeypatch):
    """Fails if the Sentinel water, cloud, or source-validity mask is bypassed."""
    graph = OperationGraph()
    image = FakeMaskImage(graph, {"SCL": 6, "QA60": 0})
    fake_ee = type("FakeEE", (), {"Reducer": type("Reducer", (), {"min": staticmethod(lambda: "minimum")})})()
    monkeypatch.setattr(watch_overlay, "ee", fake_ee)

    result = watch_overlay._usable_water_pixel_mask(
        image, FakeMaskValue(graph, "connected-water")
    )

    assert graph.selected == ["SCL", "QA60"]
    assert ("eq", "SCL", 6) in graph.operations
    assert ("bitwiseAnd", "QA60", 1 << 10) in graph.operations
    assert ("bitwiseAnd", "QA60", 1 << 11) in graph.operations
    assert graph.combined_with_connected_water
    assert result is graph.final_mask
    assert result.expression == (
        "And",
        (
            "And",
            (
                "And",
                "connected-water",
                ("eq", "SCL", 6),
            ),
            (
                "And",
                ("eq", ("bitwiseAnd", "QA60", 1 << 10), 0),
                ("eq", ("bitwiseAnd", "QA60", 1 << 11), 0),
            ),
        ),
        "source-valid",
    )


def test_trend_window_is_fourteen_calendar_days_ending_on_target():
    assert watch_overlay.trend_window("2026-08-27", 14) == (
        "2026-08-14",
        "2026-08-28",
    )


def test_daily_medians_and_trend_fit_use_observed_days_only(monkeypatch):
    """Fails if same-day scenes, count gating, or elapsed-day linear fit is bypassed."""
    graph = OperationGraph()
    daily_ee = type(
        "FakeEE",
        (),
        {
            "Image": type("Image", (), {"constant": staticmethod(lambda value: FakeDailyImage(graph, str(value)))}),
            "ImageCollection": type(
                "ImageCollection", (), {"fromImages": staticmethod(lambda images: images)}
            ),
            "Reducer": type("Reducer", (), {"linearFit": staticmethod(lambda: "linear-fit")}),
            "Algorithms": type(
                "Algorithms", (), {"If": staticmethod(lambda condition, true_value, false_value: true_value)}
            ),
        },
    )()
    daily_ee.Image = FakeDailyImageFactory(graph)
    monkeypatch.setattr(watch_overlay, "ee", daily_ee)

    daily_images = watch_overlay._daily_ndci_collection(
        FakeDailyCollection(graph), "2026-08-14", "2026-08-16"
    )
    trend = watch_overlay._build_trend_image(
        FakeTrendCollection(graph), min_observations=2
    )

    assert [(op[1], op[2]) for op in graph.operations if op[0] == "filterDate"] == [
        ("2026-08-14", "2026-08-15"),
        ("2026-08-15", "2026-08-16"),
    ]
    assert len([op for op in graph.operations if op[0] == "median"]) == 2
    assert graph.selected[-2:] == ["ndci", ["elapsed_days", "ndci"]]
    assert ("reduce", "fit-input", "linear-fit") in graph.operations
    assert ("gte", "trend_observation_count", 2) in graph.operations
    assert daily_images
    assert trend.name == "ndci_slope_per_day"


def test_empty_daily_ndci_is_masked_before_trend_count(monkeypatch):
    """Fails if an empty UTC date can contribute elapsed days or trend count."""
    graph = type("Graph", (), {"trend_counts": []})()

    class FakeImage:
        def __init__(self, name, *, value=None, fully_masked=False):
            self.name = name
            self.value = value
            self.fully_masked = fully_masked
            self.bands = []

        def rename(self, name):
            self.name = name
            return self

        def updateMask(self, mask):
            self.fully_masked = mask.fully_masked or mask.value == 0
            return self

        def mask(self):
            return FakeImage(f"{self.name}-mask", fully_masked=self.fully_masked)

        def toFloat(self):
            return self

        def addBands(self, other):
            self.bands.append(other)
            return self

        def set(self, name, value):
            return self

        def count(self):
            graph.trend_counts.append(
                sum(not image.fully_masked for image in graph.daily_images)
            )
            return FakeImage("trend_observation_count", value=graph.trend_counts[-1])

        def gte(self, value):
            return FakeImage("count-mask")

        def reduce(self, reducer):
            assert reducer == "linear-fit"
            return FakeImage("linear-fit")

        def select(self, band):
            assert band == "scale"
            return FakeImage("scale")

    class EmptyDaily:
        def size(self):
            return type("EmptySize", (), {"gt": staticmethod(lambda value: False)})()

        def select(self, band):
            assert band == "ndci"
            return type(
                "EmptyNDCI",
                (), {"median": staticmethod(lambda: FakeImage("empty-median"))},
            )()

    class EmptyCollection:
        def filterDate(self, start, end):
            return EmptyDaily()

    class TrendCollection:
        def select(self, bands):
            if bands == "ndci":
                return FakeImage("ndci")
            assert bands == ["elapsed_days", "ndci"]
            return FakeImage("fit-input")

    class ImageFactory:
        def __call__(self, image):
            return image

        @staticmethod
        def constant(value):
            return FakeImage("constant", value=value)

    class ImageCollectionFactory:
        @staticmethod
        def fromImages(images):
            graph.daily_images = images
            return TrendCollection()

    fake_ee = type(
        "FakeEE",
        (),
        {
            "Image": ImageFactory(),
            "ImageCollection": ImageCollectionFactory(),
            "Algorithms": type(
                "Algorithms", (), {"If": staticmethod(lambda condition, true_value, false_value: false_value)}
            ),
            "Reducer": type("Reducer", (), {"linearFit": staticmethod(lambda: "linear-fit")}),
        },
    )()
    monkeypatch.setattr(watch_overlay, "ee", fake_ee)

    daily_collection = watch_overlay._daily_ndci_collection(
        EmptyCollection(), "2026-08-14", "2026-08-15"
    )
    watch_overlay._build_trend_image(daily_collection, min_observations=2)

    empty_day = graph.daily_images[0]
    assert empty_day.name == "ndci"
    assert empty_day.fully_masked
    assert empty_day.bands[0].name == "elapsed_days"
    assert empty_day.bands[0].fully_masked
    assert graph.trend_counts == [0]


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
