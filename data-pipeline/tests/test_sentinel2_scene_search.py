"""Exercise the real scene-selection walk with synthetic Earth Engine replies.

Only remote collection/image operations are doubled. The window bounds,
the newest-first ordering, cloud rejection, water-pixel rejection, the
"never a scene acquired after the requested day" rule and the
single-round-trip batching all stay in production code.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src import imagery, sentinel2


def scene_catalog(monkeypatch, scenes):
    """Install a fake Earth Engine holding `scenes`.

    Each scene is (id, ISO acquisition timestamp, buffer cloud fraction,
    surviving water pixels). Rows outside the resolved window are dropped
    by the fake `filterDate` exactly as GEE would drop them, so a test can
    assert on what the window admitted rather than on what it was asked
    for. Returns (calls, bounds): `calls["getInfo"]` counts network round
    trips, `bounds` records each (start, end) filterDate pair.
    """
    calls = {"getInfo": 0}
    bounds = []

    def row_for(image_id):
        return next(row for row in scenes if row[0] == image_id)

    def epoch_ms(iso_timestamp):
        return datetime.fromisoformat(iso_timestamp).replace(
            tzinfo=timezone.utc
        ).timestamp() * 1000

    class Image:
        def __init__(self, image_id=None):
            if isinstance(image_id, Image):
                self.image_id = image_id.image_id
            elif image_id:
                self.image_id = image_id.rsplit("/", 1)[-1]
            else:
                self.image_id = None

        def select(self, *_args):
            return self

        def updateMask(self, *_args):
            return self

        def addBands(self, *_args):
            return self

        def And(self, *_args):
            return self

        def Not(self):
            return self

        def get(self, property_name):
            row = row_for(self.image_id)
            return row[0] if property_name == "system:index" else epoch_ms(row[1])

        def reduceRegion(self, **_kwargs):
            _, _, cloud, water_pixels = row_for(self.image_id)
            stats = {"cloud_flag_mean": cloud, "cloud_flag_count": 10}
            for band in sentinel2.BANDS:
                stats[f"{band}_mean"] = 100.0 if water_pixels else None
                stats[f"{band}_count"] = water_pixels
            return stats

    class Feature:
        def __init__(self, _geometry, properties):
            self.properties = dict(properties)

        def set(self, extra):
            self.properties.update(extra)
            return self

    class FeatureCollection:
        def __init__(self, features):
            self.features = features

        def getInfo(self):
            calls["getInfo"] += 1
            return {"features": [{"properties": f.properties} for f in self.features]}

    class Collection:
        rows = ()

        def filterBounds(self, _region):
            return self

        def filterDate(self, start, end):
            bounds.append((start, end))
            self.rows = [row for row in scenes if start <= row[1][:10] < end]
            return self

        def sort(self, _property):
            self.rows.sort(key=lambda row: row[1])
            return self

        def map(self, fn):
            return [fn(Image(row[0])) for row in self.rows]

    reducer = SimpleNamespace(combine=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sentinel2, "initialize_ee", lambda: None)
    monkeypatch.setattr(sentinel2, "_water_mask_image", lambda: Image())
    monkeypatch.setattr(sentinel2, "_cloud_flag_image", lambda _image: Image())
    monkeypatch.setattr(sentinel2, "ee", SimpleNamespace(
        Image=Image,
        Feature=Feature,
        FeatureCollection=FeatureCollection,
        ImageCollection=lambda _asset: Collection(),
        Geometry=SimpleNamespace(Point=lambda _coords: SimpleNamespace(buffer=lambda _r: None)),
        Reducer=SimpleNamespace(mean=lambda: reducer, count=lambda: None),
    ))
    return calls, bounds


# --------------------------------------------------------------------------
# The selection rule: newest usable acquisition on or before the requested
# day, never one after it, however much closer in time that one would be.
# --------------------------------------------------------------------------


def test_newest_usable_past_scene_wins_over_a_closer_future_one(monkeypatch):
    calls, bounds = scene_catalog(monkeypatch, [
        ("too-old", "2026-08-16T03:00:00", 0.0, 10),
        ("older-clear", "2026-08-20T03:00:00", 0.0, 10),
        ("newest-clear", "2026-08-25T03:00:00", 0.0, 10),
        ("recent-cloud", "2026-09-02T03:00:00", 1.0, 10),
        ("future-clear", "2026-09-07T03:00:00", 0.0, 10),
    ])
    result = sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06", max_scene_age_days=20)

    # 2026-09-07 is one day from the target and perfectly clear; it is
    # still never used, while a 12-day-old scene is.
    assert result["actual_date"] == "2026-08-25"
    assert result["B2"] == 100.0
    assert bounds == [("2026-08-17", "2026-09-07")]


def test_the_walk_back_costs_one_round_trip_however_deep_it_goes(monkeypatch):
    """The batched statistics query is the reason a long ceiling is
    affordable: nine cloud rejections must not mean nine getInfo calls."""
    calls, _ = scene_catalog(monkeypatch, [
        (f"cloudy-{day}", f"2026-09-{day:02d}T03:00:00", 1.0, 10)
        for day in range(1, 6)
    ] + [("clear", "2026-08-20T03:00:00", 0.0, 10)])

    result = sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06", max_scene_age_days=20)

    assert result["actual_date"] == "2026-08-20"
    assert calls["getInfo"] == 1


def test_a_scene_exactly_at_the_ceiling_is_still_usable(monkeypatch):
    scene_catalog(monkeypatch, [("boundary", "2026-08-17T03:00:00", 0.0, 10)])
    result = sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06", max_scene_age_days=20)
    assert result["actual_date"] == "2026-08-17"


def test_past_the_ceiling_and_the_future_cannot_fill_a_gap(monkeypatch):
    calls, _ = scene_catalog(monkeypatch, [
        ("one-day-too-old", "2026-08-16T03:00:00", 0.0, 10),
        ("future", "2026-09-07T03:00:00", 0.0, 10),
    ])
    with pytest.raises(sentinel2.NoCloudFreeImageryError):
        sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06", max_scene_age_days=20)


def test_the_requested_day_itself_resolves_to_its_latest_acquisition(monkeypatch):
    scene_catalog(monkeypatch, [
        ("early", "2026-09-06T02:00:00", 0.0, 10),
        ("late", "2026-09-06T04:00:00", 0.0, 10),
    ])
    result = sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06", max_scene_age_days=20)
    assert result["actual_date"] == "2026-09-06"


def test_a_clear_scene_with_no_surviving_water_pixels_keeps_the_walk_going(monkeypatch):
    """Cloud is not the only reason to reject a candidate: a clear scene
    whose buffer is entirely land under the water mask is skipped too,
    and the next older usable scene answers instead."""
    scene_catalog(monkeypatch, [
        ("clear-but-dry", "2026-09-05T03:00:00", 0.0, 0),
        ("clear-and-wet", "2026-08-30T03:00:00", 0.0, 10),
    ])
    result = sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06", max_scene_age_days=20)
    assert result["actual_date"] == "2026-08-30"


def test_an_all_land_buffer_still_reports_no_water_pixels(monkeypatch):
    scene_catalog(monkeypatch, [("clear-but-dry", "2026-09-05T03:00:00", 0.0, 0)])
    with pytest.raises(sentinel2.NoWaterPixelsError):
        sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06", max_scene_age_days=20)


# --------------------------------------------------------------------------
# The ceiling is configuration, and it is the only thing configurable
# about scene choice.
# --------------------------------------------------------------------------


def test_the_default_ceiling_is_used_when_the_caller_names_none(monkeypatch):
    monkeypatch.delenv(sentinel2.MAX_SCENE_AGE_ENV_VAR, raising=False)
    _, bounds = scene_catalog(monkeypatch, [("clear", "2026-09-06T03:00:00", 0.0, 10)])
    sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06")
    assert sentinel2.DEFAULT_MAX_SCENE_AGE_DAYS == 60
    assert bounds == [("2026-07-08", "2026-09-07")]


def test_the_env_override_moves_the_ceiling(monkeypatch):
    monkeypatch.setenv(sentinel2.MAX_SCENE_AGE_ENV_VAR, "5")
    _, bounds = scene_catalog(monkeypatch, [("clear", "2026-09-06T03:00:00", 0.0, 10)])
    sentinel2.get_sentinel2_bands(13, 100.5, "2026-09-06")
    assert bounds == [("2026-09-01", "2026-09-07")]


@pytest.mark.parametrize("bad_value", ["", "   ", "not-a-number", "0", "-5"])
def test_an_unusable_env_value_falls_back_instead_of_crashing_the_pipeline(monkeypatch, bad_value):
    monkeypatch.setenv(sentinel2.MAX_SCENE_AGE_ENV_VAR, bad_value)
    assert sentinel2.default_max_scene_age_days() == sentinel2.DEFAULT_MAX_SCENE_AGE_DAYS


# --------------------------------------------------------------------------
# Same-scene guarantee (imagery.py's module docstring): the picture beside
# a number must come from the same resolved scene, which is only true
# while both paths call the one resolver.
# --------------------------------------------------------------------------


def test_the_image_path_resolves_through_the_same_function_as_the_numbers():
    assert imagery._resolve_sentinel2_scene is sentinel2._resolve_sentinel2_scene
