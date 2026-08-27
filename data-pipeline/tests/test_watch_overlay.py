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


LEVEL_DEFINITIONS = [
    {
        "code": "elevated",
        "class_code": 1,
        "label_th": "เริ่มผิดปกติ",
        "color": "#34C759",
        "min_z": 1.5,
        "requires_rising_trend": False,
        "requires_sst_above_normal": False,
    },
    {
        "code": "watch",
        "class_code": 2,
        "label_th": "เฝ้าระวัง",
        "color": "#FF9F0A",
        "min_z": 1.5,
        "requires_rising_trend": True,
        "requires_sst_above_normal": False,
    },
    {
        "code": "warning",
        "class_code": 3,
        "label_th": "เตือนภัย",
        "color": "#FF3B30",
        "min_z": 2.0,
        "requires_rising_trend": True,
        "requires_sst_above_normal": True,
    },
]


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


def test_sst_seasonal_windows_use_every_prior_archive_year():
    windows = watch_overlay.sst_seasonal_windows(
        "2005-01-03", archive_start_date="2002-07-04", window_days=7
    )
    assert windows == [
        ("2002-12-27", "2003-01-11"),
        ("2003-12-27", "2004-01-11"),
    ]


def test_parse_site_alerts_omits_normal_masked_and_unknown_levels():
    sampled = [
        {
            "properties": {
                "site_id": "a",
                "name": "A",
                "lat": 13.0,
                "lng": 100.7,
                "level_code": 0,
            }
        },
        {
            "properties": {
                "site_id": "b",
                "name": "B",
                "lat": 13.1,
                "lng": 100.8,
                "level_code": 1,
                "ndci_z": 1.7,
                "ndci_slope_per_day": None,
                "trend_observation_count": 1,
                "latest_acquired_ms": 1785283200000,
                "current_sst": None,
                "seasonal_sst": None,
                "sst_acquired_ms": None,
            }
        },
        {
            "properties": {
                "site_id": "c",
                "name": "C",
                "lat": 13.2,
                "lng": 100.9,
                "level_code": 3,
                "ndci_z": 2.4,
                "ndci_slope_per_day": 0.01,
                "trend_observation_count": 3,
                "latest_acquired_ms": 1785283200000,
                "current_sst": 30.2,
                "seasonal_sst": 29.8,
                "sst_acquired_ms": 1785196800000,
            }
        },
        {
            "properties": {
                "site_id": "d",
                "name": "D",
                "lat": 13.3,
                "lng": 101.0,
            }
        },
    ]
    alerts = watch_overlay._parse_site_alerts(
        sampled, level_definitions=LEVEL_DEFINITIONS
    )
    assert [item["site_id"] for item in alerts] == ["b", "c"]
    assert [item["level"] for item in alerts] == ["elevated", "warning"]
    assert alerts[0]["trend_rising"] is False
    assert alerts[1]["sst_above_normal"] is True
    assert all(item["level"] != "normal" for item in alerts)


def test_parse_site_alerts_restores_masked_support_values_to_none():
    sampled = [
        {
            "properties": {
                "site_id": "a",
                "name": "A",
                "lat": 13.0,
                "lng": 100.7,
                "level_code": 1,
                "ndci_z": 1.7,
                "latest_acquired_ms": 1785283200000,
                "ndci_slope_per_day": watch_overlay.SITE_SAMPLE_NODATA,
                "trend_observation_count": 1,
                "current_sst": watch_overlay.SITE_SAMPLE_NODATA,
                "seasonal_sst": watch_overlay.SITE_SAMPLE_NODATA,
                "sst_acquired_ms": watch_overlay.SITE_SAMPLE_NODATA,
            }
        }
    ]

    alert = watch_overlay._parse_site_alerts(
        sampled, level_definitions=LEVEL_DEFINITIONS
    )[0]

    assert alert["trend_slope_per_day"] is None
    assert alert["current_sst"] is None
    assert alert["seasonal_sst"] is None
    assert alert["sst_date"] is None
    assert alert["trend_rising"] is False
    assert alert["sst_above_normal"] is False


def test_parse_site_alerts_rejects_non_integral_or_non_finite_class_codes():
    sampled = [
        {
            "properties": {
                "site_id": "valid",
                "name": "Valid",
                "lat": 13.0,
                "lng": 100.7,
                "level_code": 2.0,
            }
        },
        *[
            {
                "properties": {
                    "site_id": f"invalid-{index}",
                    "name": "Invalid",
                    "lat": 13.0,
                    "lng": 100.7,
                    "level_code": value,
                }
            }
            for index, value in enumerate(
                [1.5, float("inf"), float("nan"), True, "3", 4]
            )
        ],
    ]

    alerts = watch_overlay._parse_site_alerts(
        sampled, level_definitions=LEVEL_DEFINITIONS
    )

    assert [alert["site_id"] for alert in alerts] == ["valid"]
    assert [alert["level"] for alert in alerts] == ["watch"]


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


def test_classification_image_applies_exact_escalation_graph(monkeypatch):
    """Fails if non-rising evidence can escalate or support bands are omitted."""
    class FakeCondition:
        def __init__(self, expression):
            self.expression = expression

        def And(self, other):
            return FakeCondition(("And", self.expression, other.expression))

    class FakeBand:
        def __init__(self, name):
            self.name = name
            self.bands = [name]
            self.unmasked_bands = []
            self.where_calls = []
            self.mask = None

        def gte(self, value):
            return FakeCondition(("gte", self.name, value))

        def gt(self, value):
            other_name = value.name if isinstance(value, FakeBand) else value
            return FakeCondition(("gt", self.name, other_name))

        def rename(self, name):
            self.name = name
            self.bands = [name]
            return self

        def updateMask(self, condition):
            self.mask = condition.expression
            return self

        def unmask(self, value):
            assert value == watch_overlay.SITE_SAMPLE_NODATA
            self.unmasked_bands = [self.name]
            return self

        def where(self, condition, value):
            self.where_calls.append((condition.expression, value))
            return self

        def addBands(self, other):
            self.bands.extend(other.bands)
            self.unmasked_bands.extend(other.unmasked_bands)
            return self

        def clip(self, region):
            assert region == "scan-region"
            return self

    class FakeTrend:
        @staticmethod
        def select(name):
            return FakeBand(name)

    fake_ee = type(
        "FakeEE",
        (),
        {
            "Image": type(
                "Image",
                (),
                {"constant": staticmethod(lambda value: FakeBand(f"constant-{value}"))},
            )
        },
    )()
    monkeypatch.setattr(watch_overlay, "ee", fake_ee)

    analysis = watch_overlay._build_classification_image(
        z=FakeBand("ndci_z"),
        latest_acquired_ms=FakeBand("latest_acquired_ms"),
        trend=FakeTrend(),
        current_sst=FakeBand("current_sst"),
        seasonal_sst=FakeBand("seasonal_sst"),
        sst_acquired_ms=FakeBand("sst_acquired_ms"),
        elevated_z=1.5,
        warning_z=2.0,
        min_trend_observations=2,
        region="scan-region",
    )

    rising = (
        "And",
        ("gte", "trend_observation_count", 2),
        ("gt", "ndci_slope_per_day", 0),
    )
    assert analysis.mask == ("gte", "ndci_z", 1.5)
    assert analysis.where_calls == [
        (
            (
                "And",
                ("gte", "ndci_z", 1.5),
                rising,
            ),
            2,
        ),
        (
            (
                "And",
                (
                    "And",
                    ("gte", "ndci_z", 2.0),
                    rising,
                ),
                ("gt", "current_sst", "seasonal_sst"),
            ),
            3,
        ),
    ]
    assert analysis.bands == [
        "level_code",
        "ndci_z",
        "latest_acquired_ms",
        "ndci_slope_per_day",
        "trend_observation_count",
        "current_sst",
        "seasonal_sst",
        "sst_acquired_ms",
    ]
    assert analysis.unmasked_bands == [
        "ndci_z",
        "latest_acquired_ms",
        "ndci_slope_per_day",
        "trend_observation_count",
        "current_sst",
        "seasonal_sst",
        "sst_acquired_ms",
    ]


def test_sst_images_use_nearest_pixel_quality_and_mask_empty_climatology(
    monkeypatch,
):
    class FakeExpression:
        def __init__(self, expression):
            self.expression = expression

        def subtract(self, value):
            return FakeExpression(("subtract", self.expression, value))

        def abs(self):
            return FakeExpression(("abs", self.expression))

        def divide(self, value):
            return FakeExpression(("divide", self.expression, value))

        def multiply(self, value):
            return FakeExpression(("multiply", self.expression, value))

        def gte(self, value):
            return FakeExpression(("gte", self.expression, value))

        def add(self, other):
            return FakeExpression(("add", self.expression, other.expression))

        def gt(self, value):
            return FakeExpression(("gt", self.expression, value))

    class FakeImage:
        def __init__(self, name, graph, expression=None):
            self.name = name
            self.graph = graph
            self.expression = expression
            self.properties = {}
            self.mask_expression = None

        def get(self, property_name):
            return FakeExpression(("get", property_name))

        def select(self, name):
            return FakeImage(name, self.graph)

        def rename(self, name):
            self.name = name
            return self

        def mask(self):
            return FakeImage(f"{self.name}-mask", self.graph)

        def gt(self, value):
            return FakeExpression(("gt", self.expression, value))

        def updateMask(self, mask):
            self.mask_expression = mask.expression or mask.name
            return self

        def addBands(self, other):
            self.graph.added_bands.append(other)
            return self

        def clip(self, region):
            assert region == "scan-region"
            return self

        def set(self, name, value):
            self.properties[name] = value
            return self

    class FakeCollection:
        def __init__(self, graph, window=None):
            self.graph = graph
            self.window = window

        def filterBounds(self, region):
            assert region == "scan-region"
            return self

        def filterDate(self, start, end):
            self.graph.filter_dates.append((start, end))
            return FakeCollection(self.graph, (start, end))

        def map(self, function):
            scored = function(FakeImage("source", self.graph))
            return FakeMappedCollection(self.graph, scored)

        @staticmethod
        def size():
            return type("NonEmptySize", (), {"gt": staticmethod(lambda value: True)})()

        def select(self, name):
            assert name == "sst"
            return self

        def merge(self, other):
            return self

        def mean(self):
            return FakeImage("mean", self.graph)

        def count(self):
            return FakeImage(
                "count", self.graph, FakeExpression(("count", "sst")).expression
            )

        def aggregate_max(self, property_name):
            assert property_name == "system:time_start"
            return "newest-sst-ms"

    class FakeMappedCollection:
        def __init__(self, graph, image):
            self.graph = graph
            self.image = image

        def qualityMosaic(self, band):
            self.graph.quality_mosaic_band = band
            return self.image

    class FakeImageFactory:
        def __init__(self, graph):
            self.graph = graph

        def __call__(self, image):
            return image

        def constant(self, value):
            expression = value.expression if isinstance(value, FakeExpression) else value
            image = FakeImage("constant", self.graph, expression)
            if isinstance(expression, tuple) and expression[0] == "add":
                self.graph.quality_image = image
            return image

    graph = type(
        "Graph",
        (),
        {
            "filter_dates": [],
            "added_bands": [],
            "quality_mosaic_band": None,
            "quality_image": None,
        },
    )()
    fake_ee = type(
        "FakeEE",
        (),
        {
            "Image": FakeImageFactory(graph),
            "ImageCollection": staticmethod(
                lambda collection_id: FakeCollection(graph)
                if collection_id == watch_overlay.MODIS_SST_COLLECTION_ID
                else None
            ),
            "Number": staticmethod(lambda value: value),
            "Algorithms": type(
                "Algorithms", (), {"If": staticmethod(lambda condition, true_value, false_value: true_value)}
            ),
        },
    )()
    monkeypatch.setattr(watch_overlay, "ee", fake_ee)

    current, acquired, seasonal, seasonal_count = watch_overlay._build_sst_images(
        "2005-01-03",
        region="scan-region",
        search_window_days=5,
        climatology_window_days=7,
    )

    target_ms = 1_104_710_400_000
    assert graph.filter_dates == [
        ("2004-12-29", "2005-01-09"),
        ("2002-12-27", "2003-01-11"),
        ("2003-12-27", "2004-01-11"),
    ]
    assert graph.quality_mosaic_band == "sst_quality"
    assert graph.quality_image.mask_expression == "current_sst-mask"
    assert graph.quality_image.expression == (
        "add",
        (
            "multiply",
            (
                "divide",
                ("abs", ("subtract", ("get", "system:time_start"), target_ms)),
                86_400_000,
            ),
            -1,
        ),
        ("multiply", ("gte", ("get", "system:time_start"), target_ms), 0.1),
    )
    assert current.name == "current_sst"
    assert current.properties["newest_sst_scene_ms"] == "newest-sst-ms"
    assert acquired.name == "sst_acquired_ms"
    assert seasonal.name == "seasonal_sst"
    assert seasonal.mask_expression == ("gt", ("count", "sst"), 0)
    assert seasonal_count.name == "seasonal_sst_count"


def test_empty_current_sst_uses_masked_evidence_without_warning_escalation(
    monkeypatch,
):
    """Fails if an empty current SST collection produces no bands or a warning."""
    class FakeImage:
        def __init__(self, name, *, fully_masked=False, value=None):
            self.name = name
            self.fully_masked = fully_masked
            self.value = value
            self.properties = {}
            self.bands = [name]

        def select(self, name):
            if self.name == "no-current-sst-bands":
                raise AssertionError("empty current SST mosaic must not be selected")
            return FakeImage(name, fully_masked=self.fully_masked)

        def rename(self, name):
            self.name = name
            self.bands = [name]
            return self

        def updateMask(self, mask):
            self.fully_masked = self.fully_masked or mask.fully_masked or mask.value == 0
            return self

        def addBands(self, other):
            self.bands.extend(other.bands)
            return self

        def clip(self, region):
            assert region == "scan-region"
            return self

        def set(self, name, value):
            self.properties[name] = value
            return self

        def mask(self):
            return FakeImage(f"{self.name}-mask", fully_masked=self.fully_masked)

        def gt(self, value):
            return FakeImage("seasonal-count-mask")

    class EmptyCurrentSst:
        @staticmethod
        def size():
            return type("EmptySize", (), {"gt": staticmethod(lambda value: False)})()

        @staticmethod
        def map(function):
            return type(
                "NoBandMosaic",
                (), {
                    "qualityMosaic": staticmethod(
                        lambda band: FakeImage("no-current-sst-bands")
                    )
                },
            )()

        @staticmethod
        def aggregate_max(property_name):
            assert property_name == "system:time_start"
            return None

    class SeasonalSst:
        @staticmethod
        def select(name):
            assert name == "sst"
            return SeasonalSst()

        @staticmethod
        def merge(other):
            return SeasonalSst()

        @staticmethod
        def count():
            return FakeImage("seasonal_sst_count")

        @staticmethod
        def mean():
            return FakeImage("seasonal_sst")

    class Source:
        def __init__(self):
            self.filter_count = 0

        @staticmethod
        def filterBounds(region):
            assert region == "scan-region"
            return source

        def filterDate(self, start, end):
            self.filter_count += 1
            return EmptyCurrentSst() if self.filter_count == 1 else SeasonalSst()

    source = Source()
    fake_ee = type(
        "FakeEE",
        (),
        {
            "Image": type(
                "Image",
                (),
                {
                    "__call__": staticmethod(lambda image: image),
                    "constant": staticmethod(
                        lambda value: FakeImage("constant", value=value)
                    ),
                },
            )(),
            "ImageCollection": staticmethod(
                lambda collection_id: source
                if collection_id == watch_overlay.MODIS_SST_COLLECTION_ID
                else None
            ),
            "Number": staticmethod(lambda value: value),
            "Algorithms": type(
                "Algorithms", (), {"If": staticmethod(lambda condition, true_value, false_value: false_value)}
            ),
        },
    )()
    monkeypatch.setattr(watch_overlay, "ee", fake_ee)

    current_sst, sst_acquired_ms, _seasonal_sst, _seasonal_count = (
        watch_overlay._build_sst_images(
            "2005-01-03",
            region="scan-region",
            search_window_days=5,
            climatology_window_days=7,
        )
    )

    assert current_sst.name == "current_sst"
    assert current_sst.fully_masked
    assert current_sst.properties["newest_sst_scene_ms"] is None
    assert sst_acquired_ms.name == "sst_acquired_ms"
    assert sst_acquired_ms.fully_masked

    from src.watch_rules import LEVEL_WATCH, classify_levels

    levels = classify_levels(
        z=[2.2],
        slope_per_day=[0.01],
        trend_observations=[2],
        current_sst=[np.nan],
        seasonal_sst=[29.8],
        elevated_z=1.5,
        warning_z=2.0,
        min_trend_observations=2,
    )
    assert levels.tolist() == [LEVEL_WATCH]


def test_sample_site_alerts_uses_final_analysis_image_at_twenty_metres(monkeypatch):
    class FakeSample:
        @staticmethod
        def getInfo():
            return {
                "features": [
                    {
                        "properties": {
                            "_site_order": 0,
                            "site_id": "a",
                            "name": "A",
                            "lat": 13.0,
                            "lng": 100.7,
                            "level_code": 1,
                        }
                    }
                ]
            }

    class FakeAnalysis:
        def __init__(self):
            self.sample_call = None

        def sampleRegions(self, **kwargs):
            self.sample_call = kwargs
            return FakeSample()

    fake_ee = type(
        "FakeEE",
        (),
        {
            "Geometry": type(
                "Geometry",
                (),
                {"Point": staticmethod(lambda coordinates: tuple(coordinates))},
            ),
            "Feature": staticmethod(lambda geometry, properties: (geometry, properties)),
            "FeatureCollection": staticmethod(lambda features: features),
        },
    )()
    monkeypatch.setattr(watch_overlay, "ee", fake_ee)
    analysis = FakeAnalysis()

    alerts = watch_overlay._sample_site_alerts(
        analysis,
        monitoring_sites=[
            {"site_id": "a", "name": "A", "lat": 13.0, "lng": 100.7}
        ],
        level_definitions=LEVEL_DEFINITIONS,
        scale_m=20,
    )

    assert analysis.sample_call == {
        "collection": [
            (
                (100.7, 13.0),
                {
                    "_site_order": 0,
                    "site_id": "a",
                    "name": "A",
                    "lat": 13.0,
                    "lng": 100.7,
                },
            )
        ],
        "scale": 20,
        "geometries": False,
    }
    assert [alert["site_id"] for alert in alerts] == ["a"]


def test_watch_tile_metadata_reports_three_tiers_and_source_contract(monkeypatch):
    """Fails if the returned tile contract omits v2 evidence or legacy fields."""
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

        @staticmethod
        def qualityMosaic(band):
            assert band == "acquired_ms"
            return type(
                "Latest",
                (),
                {"select": staticmethod(lambda name: f"latest-{name}")},
            )()

    class FakeSST:
        @staticmethod
        def get(property_name):
            assert property_name == "newest_sst_scene_ms"
            return FakeValue(1_785_283_200_000)

    class FakeAnalysis:
        def __init__(self):
            self.visualization = None

        def select(self, name):
            assert name == "level_code"
            return self

        def visualize(self, **visualization):
            self.visualization = visualization
            return self

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
    monkeypatch.setattr(
        watch_overlay,
        "_build_current_anomaly",
        lambda **kwargs: ("z-image", "latest-acquired-image"),
    )
    monkeypatch.setattr(
        watch_overlay,
        "_build_masked_ndci_collection",
        lambda *args, **kwargs: "trend-source",
    )
    monkeypatch.setattr(
        watch_overlay,
        "_daily_ndci_collection",
        lambda *args, **kwargs: "daily-trend-source",
    )
    monkeypatch.setattr(
        watch_overlay, "_build_trend_image", lambda *args, **kwargs: "trend-image"
    )
    monkeypatch.setattr(
        watch_overlay,
        "_build_sst_images",
        lambda *args, **kwargs: (
            FakeSST(),
            "sst-acquired-image",
            "seasonal-sst-image",
            "seasonal-sst-count-image",
        ),
    )
    analysis = FakeAnalysis()
    monkeypatch.setattr(
        watch_overlay, "_build_classification_image", lambda **kwargs: analysis
    )
    sample_calls = []
    monkeypatch.setattr(
        watch_overlay,
        "_sample_site_alerts",
        lambda image, **kwargs: sample_calls.append((image, kwargs))
        or [{"level": "elevated"}],
    )

    result = build_ndci_watch_overlay(
        "2026-08-27",
        threshold_z=1.5,
        warning_threshold_z=2.0,
        latest_window_days=30,
        baseline_years=5,
        seasonal_window_days=15,
        min_baseline_observations=3,
        trend_window_days=14,
        min_trend_observations=2,
        sst_search_window_days=5,
        sst_climatology_window_days=15,
        sst_resolution_m=4638,
        water_occurrence_pct=50.0,
        gulf_seed_points=[[13.0, 100.0]],
        output_scale_m=10,
        effective_resolution_m=20,
        level_colors={
            "elevated": "#34C759",
            "watch": "#FF9F0A",
            "warning": "#FF3B30",
        },
        monitoring_sites=[
            {"site_id": "a", "name": "A", "lat": 13.0, "lng": 100.7}
        ],
    )

    assert result["threshold_z"] == 1.5
    assert result["color"] == "#FF9F0A"
    assert result["analysis_metadata"]["version"] == 2
    assert [
        level["code"] for level in result["analysis_metadata"]["levels"]
    ] == ["elevated", "watch", "warning"]
    assert result["analysis_metadata"]["resolutions"] == {
        "output_grid_m": 10,
        "ndci_m": 20,
        "trend_m": 20,
        "sst_m": 4638,
    }
    assert all(
        alert["level"] != "normal"
        for alert in result["analysis_metadata"]["site_alerts"]
    )
    assert result["output_grid_m"] == 10
    assert result["effective_resolution_m"] == 20
    assert result["water_mask"] == "gulf_connected_historical_surface_water"
    assert "not" in result["caveat"].lower()
    assert "bloom" in result["caveat"].lower()
    assert analysis.visualization == {
        "min": 1,
        "max": 3,
        "palette": ["34C759", "FF9F0A", "FF3B30"],
    }
    assert sample_calls == [
        (
            analysis,
            {
                "monitoring_sites": [
                    {
                        "site_id": "a",
                        "name": "A",
                        "lat": 13.0,
                        "lng": 100.7,
                    }
                ],
                "level_definitions": result["analysis_metadata"]["levels"],
                "scale_m": 20,
            },
        )
    ]
