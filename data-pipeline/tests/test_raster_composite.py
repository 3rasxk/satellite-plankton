"""Exercise the real raster composite/download path with a synthetic
Earth Engine that computes actual numpy arrays.

Only the remote collection/image operations are doubled. The window
bounds, the mask-then-arithmetic order, the mosaic's most-recent-wins
rule and both date guards all stay in production code. The date tests
below are sensitive because the double coarsens by looking up
`raster.RASTER_BAND_REDUCERS`: flip the constant and the double really
does average the timestamps, and the guards really do reject the result.

READ THIS BEFORE TRUSTING A GREEN RUN
-------------------------------------
This suite cannot tell you how real Earth Engine resamples, and it is
not evidence that the GEE read behaves as `raster.py` describes.

The double is the only thing here that consults `RASTER_BAND_REDUCERS`.
Real GEE never sees that dict -- no reducer is communicated to it, and
`getDownloadURL(scale=...)` resamples with nearest neighbour, taking one
native pixel per cell rather than averaging (measured 2026-09-07: a
200 m cell read 0.00000000 where its 400 native pixels averaged
0.01839816). The double was written to implement the policy the module
wanted, so for a while it agreed with a docstring that was wrong about
production, and every test here passed throughout.

The consequence for anyone changing this code: a claim about what GEE
does can only be checked with a live call. A claim about what
`summarize_raster_cells` does -- which is where the reducers genuinely
apply -- is checkable here.
"""

import io
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from src import raster, sentinel2

NATIVE_SCALE_M = 10
NATIVE_SHAPE = (4, 4)

# Native-resolution coordinate grids the double's `pixelLonLat` serves.
LON_GRID = 100.0 + 0.002 * np.arange(NATIVE_SHAPE[1], dtype=np.float64)[None, :] * np.ones(
    (NATIVE_SHAPE[0], 1)
)
LAT_GRID = 13.0 + 0.002 * np.arange(NATIVE_SHAPE[0], dtype=np.float64)[:, None] * np.ones(
    (1, NATIVE_SHAPE[1])
)

POLYGON = ((13.0, 100.0), (13.0, 100.1), (13.1, 100.1), (13.1, 100.0))

ALL_WATER = np.ones(NATIVE_SHAPE)
NO_CLOUD = np.zeros(NATIVE_SHAPE)

# Scene B is cloudy at the 1s. Chosen so two of the four coarse cells mix
# both acquisitions -- which is the only arrangement in which averaging
# the date band produces a timestamp belonging to neither scene.
MIXED_CLOUD = np.array([
    [1, 1, 0, 0],
    [1, 0, 0, 0],
    [1, 1, 0, 1],
    [1, 1, 0, 0],
], dtype=float)


def epoch_ms(iso_timestamp: str) -> int:
    return int(
        datetime.fromisoformat(iso_timestamp).replace(tzinfo=timezone.utc).timestamp() * 1000
    )


class FakeImage:
    """A tiny raster: band name -> float64 array (NaN = masked) or scalar."""

    def __init__(self, bands=None, dtypes=None, properties=None, ops=None):
        self.bands = dict(bands or {})
        self.dtypes = dict(dtypes or {})
        self.properties = dict(properties or {})
        self.ops = ops if ops is not None else []

    # -- helpers ----------------------------------------------------------
    def _single(self):
        return np.broadcast_to(
            np.asarray(next(iter(self.bands.values())), dtype=np.float64), NATIVE_SHAPE
        )

    def _record(self, op):
        self.ops.append((op, tuple(self.bands)))

    def _derive(self, bands, dtypes=None):
        return FakeImage(bands, dtypes or self.dtypes, self.properties, self.ops)

    def _binary(self, other, fn, op_name):
        self._record(op_name)
        name = next(iter(self.bands))
        with np.errstate(divide="ignore", invalid="ignore"):
            values = fn(self._single(), other._single())
        return self._derive({name: values}, {name: self.dtypes.get(name, np.float64)})

    # -- ee.Image surface -------------------------------------------------
    def select(self, names):
        names = [names] if isinstance(names, str) else list(names)
        return self._derive(
            {name: self.bands[name] for name in names},
            {name: self.dtypes.get(name, np.float64) for name in names},
        )

    def updateMask(self, other):
        self._record("updateMask")
        keep = np.isfinite(other._single()) & (other._single() != 0)
        bands = {}
        for name, value in self.bands.items():
            values = np.array(
                np.broadcast_to(np.asarray(value, dtype=np.float64), NATIVE_SHAPE)
            )
            bands[name] = np.where(keep, values, np.nan)
        return self._derive(bands)

    def selfMask(self):
        self._record("selfMask")
        return self.updateMask(self)

    def mask(self):
        return self._derive({"mask": np.isfinite(self._single()).astype(np.float64)})

    def Not(self):
        self._record("Not")
        return self._derive({next(iter(self.bands)): 1.0 - self._single()})

    def normalizedDifference(self, names):
        self._record("normalizedDifference")
        first = np.asarray(self.bands[names[0]], dtype=np.float64)
        second = np.asarray(self.bands[names[1]], dtype=np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            values = (first - second) / (first + second)
        # Earth Engine masks normalizedDifference where either input is
        # negative.  The double must reproduce that contract so mask-alignment
        # regressions are visible offline.
        values = np.where((first >= 0) & (second >= 0), values, np.nan)
        return self._derive({"nd": values}, {"nd": self.dtypes.get(names[0], np.float64)})

    def divide(self, other):
        return self._binary(other, lambda a, b: a / b, "divide")

    def subtract(self, other):
        return self._binary(other, lambda a, b: a - b, "subtract")

    def multiply(self, other):
        return self._binary(other, lambda a, b: a * b, "multiply")

    def rename(self, name):
        old = next(iter(self.bands))
        return self._derive(
            {name: self.bands[old]}, {name: self.dtypes.get(old, np.float64)}
        )

    def addBands(self, other):
        return self._derive(
            {**self.bands, **other.bands}, {**self.dtypes, **other.dtypes}
        )

    def toFloat(self):
        return self._derive(self.bands, {name: np.float32 for name in self.bands})

    def toDouble(self):
        return self._derive(self.bands, {name: np.float64 for name in self.bands})

    def get(self, property_name):
        return self.properties[property_name]

    def getDownloadURL(self, params):
        self.ops.append(("getDownloadURL", tuple(self.bands)))
        _PENDING_DOWNLOADS.append((self, params))
        return "https://earthengine.example/fake.npy"


# getDownloadURL hands the image to the patched _fetch_npy_bytes below,
# the same handover a signed GEE URL performs in production.
_PENDING_DOWNLOADS: list = []


def _coarsen(values, factor, reducer_name):
    """Aggregate a native grid to `factor`-sized blocks with the named
    reducer -- the double's stand-in for GEE's implicit pyramiding, and
    deliberately driven by `raster.RASTER_BAND_REDUCERS`."""
    reduce_fn = raster.NUMPY_BAND_REDUCERS[reducer_name]
    rows, cols = values.shape
    out = np.zeros((rows // factor, cols // factor), dtype=np.float64)
    for row in range(rows // factor):
        for col in range(cols // factor):
            block = values[
                row * factor:(row + 1) * factor, col * factor:(col + 1) * factor
            ].ravel()
            block = block[np.isfinite(block)]
            out[row, col] = np.nan if block.size == 0 else reduce_fn(block)
    return out


def install_fake_ee(monkeypatch, scenes, water_mask=ALL_WATER, date_dtype=None):
    """Install a synthetic Earth Engine holding `scenes`.

    Each scene is (id, ISO acquisition timestamp, cloud-flag grid, band
    values). `water_mask` is the shared 0/1 water layer. `date_dtype`
    forces the transferred date band's dtype, for the narrowing guard.
    Returns a recorder: `bounds` holds each filterDate pair, `ops` the
    ordered image operations, `downloads` the transferred grids.
    """
    _PENDING_DOWNLOADS.clear()
    recorder = {"bounds": [], "ops": [], "downloads": []}

    by_id = {scene[0]: scene for scene in scenes}

    def scene_image(scene):
        scene_id, iso, _cloud, values = scene
        bands = {
            band: np.array(
                np.broadcast_to(np.asarray(value, dtype=np.float64), NATIVE_SHAPE)
            )
            for band, value in values.items()
        }
        return FakeImage(
            bands,
            {band: np.float64 for band in bands},
            {"system:index": scene_id, "system:time_start": epoch_ms(iso)},
            recorder["ops"],
        )

    class Collection:
        def __init__(self):
            self.rows = list(scenes)

        def filterBounds(self, _region):
            return self

        def filterDate(self, start, end):
            recorder["bounds"].append((start, end))
            self.rows = [row for row in self.rows if start <= row[1][:10] < end]
            return self

        def sort(self, _property):
            self.rows.sort(key=lambda row: row[1])
            return self

        def aggregate_array(self, prop):
            if prop == "system:index":
                return [row[0] for row in self.rows]
            return [epoch_ms(row[1]) for row in self.rows]

        def map(self, fn):
            return Mapped([fn(scene_image(row)) for row in self.rows])

    class Mapped:
        def __init__(self, images):
            self.images = images

        def mosaic(self):
            """Last unmasked value wins, per band, per pixel -- exactly
            what makes an ascending time sort mean most-recent-wins."""
            merged = {}
            dtypes = {}
            for image in self.images:
                for name, value in image.bands.items():
                    values = np.broadcast_to(
                        np.asarray(value, dtype=np.float64), NATIVE_SHAPE
                    )
                    if name not in merged:
                        merged[name] = np.full(NATIVE_SHAPE, np.nan)
                    merged[name] = np.where(np.isfinite(values), values, merged[name])
                    dtypes[name] = image.dtypes.get(name, np.float64)
            return FakeImage(merged, dtypes, {}, recorder["ops"])

    def fake_cloud_flag(image, _classes=None):
        _, _, cloud, _ = by_id[image.properties["system:index"]]
        return FakeImage({sentinel2.CLOUD_FLAG_BAND: np.asarray(cloud, dtype=np.float64)},
                         ops=recorder["ops"])

    def fake_water_mask(_pct=None):
        return FakeImage({sentinel2.WATER_MASK_BAND: np.asarray(water_mask, dtype=np.float64)},
                         ops=recorder["ops"])

    def fake_fetch(_url, _timeout=None):
        image, params = _PENDING_DOWNLOADS.pop()
        factor = int(params["scale"]) // NATIVE_SCALE_M
        fields = []
        columns = {}
        for name, value in image.bands.items():
            values = np.broadcast_to(np.asarray(value, dtype=np.float64), NATIVE_SHAPE)
            reducer = raster.RASTER_BAND_REDUCERS.get(name, "mean")
            coarse = _coarsen(values, factor, reducer)
            dtype = image.dtypes.get(name, np.float64)
            if name == raster.RASTER_DATE_BAND and date_dtype is not None:
                dtype = date_dtype
            fields.append((name, dtype))
            columns[name] = coarse
        grid = np.zeros(next(iter(columns.values())).shape, dtype=np.dtype(fields))
        for name, coarse in columns.items():
            grid[name] = np.nan_to_num(coarse, nan=0.0)
        recorder["downloads"].append(grid)
        buffer = io.BytesIO()
        np.save(buffer, grid)
        return buffer.getvalue()

    def image_factory(obj=None):
        return obj if isinstance(obj, FakeImage) else FakeImage(ops=recorder["ops"])

    image_factory.constant = lambda value: FakeImage(
        {"constant": float(value)}, {"constant": np.float64}, {}, recorder["ops"]
    )
    image_factory.pixelLonLat = lambda: FakeImage(
        {raster.LONGITUDE_BAND: LON_GRID, raster.LATITUDE_BAND: LAT_GRID},
        {raster.LONGITUDE_BAND: np.float64, raster.LATITUDE_BAND: np.float64},
        {},
        recorder["ops"],
    )

    class FakeDictionary:
        def __init__(self, mapping):
            self.mapping = mapping

        def getInfo(self):
            return {key: list(value) for key, value in self.mapping.items()}

    class FakeGeometry:
        @staticmethod
        def Polygon(ring):
            return {"type": "Polygon", "coordinates": ring}

    monkeypatch.setattr(raster, "initialize_ee", lambda: None)
    monkeypatch.setattr(raster, "_water_mask_image", fake_water_mask)
    monkeypatch.setattr(raster, "_cloud_flag_image", fake_cloud_flag)
    monkeypatch.setattr(raster, "_fetch_npy_bytes", fake_fetch)
    monkeypatch.setattr(raster, "ee", SimpleNamespace(
        Image=image_factory,
        Dictionary=FakeDictionary,
        Geometry=FakeGeometry,
        Number=lambda value: value,
        ImageCollection=lambda _asset: Collection(),
    ))
    return recorder


BANDS_CLEAR = {"B2": 300.0, "B3": 400.0, "B4": 500.0, "B5": 700.0, "B6": 800.0}
BANDS_BRIGHT = {"B2": 350.0, "B3": 420.0, "B4": 520.0, "B5": 900.0, "B6": 850.0}

OLD_ISO = "2026-08-25T03:30:00"
NEW_ISO = "2026-09-04T03:30:00"
OLD_MS = epoch_ms(OLD_ISO)
NEW_MS = epoch_ms(NEW_ISO)


def two_acquisition_composite(monkeypatch, **kwargs):
    """The standard fixture: an older clear pass and a newer one that is
    cloudy over part of the same ground."""
    recorder = install_fake_ee(monkeypatch, [
        ("older", OLD_ISO, NO_CLOUD, BANDS_CLEAR),
        ("newer", NEW_ISO, MIXED_CLOUD, BANDS_BRIGHT),
    ], **kwargs)
    composite = raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)
    return recorder, composite


# --------------------------------------------------------------------------
# The property that matters most: a cell's date names a pass that flew.
# --------------------------------------------------------------------------


def test_every_cell_date_is_one_of_the_source_acquisitions(monkeypatch):
    """PROPERTY. Two acquisitions go in; every date that comes out is one
    of those two, per cell, with nothing in between.

    Two of the four coarse cells here draw pixels from BOTH scenes, so
    this is not vacuous: averaging that pair would yield
    (3*OLD + NEW)/4 -- a timestamp neither satellite pass has, sitting
    plausibly between two real ones. Selecting cannot invent a value;
    averaging cannot avoid it.
    """
    _, composite = two_acquisition_composite(monkeypatch)
    arrays = raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)

    dates = set(arrays[raster.RASTER_DATE_BAND].tolist())
    assert dates <= {OLD_MS, NEW_MS}, (
        f"cell dates {sorted(dates)} include a timestamp no scene supplied; "
        f"the composite's acquisitions are {sorted({OLD_MS, NEW_MS})}"
    )
    # Both really are present, so the mosaic mixed the two scenes and the
    # assertion above had something to be wrong about.
    assert dates == {OLD_MS, NEW_MS}
    assert arrays["cell_count"] == 4


def test_averaging_the_date_band_is_caught_instead_of_stored(monkeypatch):
    """The counter-test for the property above: with the reducer switched
    to `mean` the same two acquisitions produce an in-between timestamp,
    and the download refuses it rather than returning it."""
    monkeypatch.setitem(raster.RASTER_BAND_REDUCERS, raster.RASTER_DATE_BAND, "mean")
    _, composite = two_acquisition_composite(monkeypatch)

    with pytest.raises(raster.FabricatedDateError) as excinfo:
        raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)
    assert "no source acquisition" in str(excinfo.value)


def test_max_is_the_other_acceptable_date_reducer(monkeypatch):
    """`max` -- the newest pass contributing to the cell -- also returns
    an input value, so it passes the same guard `mean` fails."""
    monkeypatch.setitem(raster.RASTER_BAND_REDUCERS, raster.RASTER_DATE_BAND, "max")
    _, composite = two_acquisition_composite(monkeypatch)

    arrays = raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)
    assert set(arrays[raster.RASTER_DATE_BAND].tolist()) <= {OLD_MS, NEW_MS}


# --------------------------------------------------------------------------
# The policy itself, asserted directly.
# --------------------------------------------------------------------------


def test_the_date_band_is_mapped_to_a_selecting_reducer_never_a_mean():
    """EXPLICIT. `RASTER_BAND_REDUCERS` is the one place the rule lives,
    so it is checked as data rather than inferred from behaviour."""
    date_reducer = raster.RASTER_BAND_REDUCERS[raster.RASTER_DATE_BAND]

    assert date_reducer in {"mode", "max"}, (
        f"the acquisition date is reduced with {date_reducer!r}; only a reducer "
        "that returns one of its inputs (mode, max) may touch a timestamp"
    )
    assert date_reducer != "mean"
    assert date_reducer not in raster.FABRICATING_REDUCERS


def test_the_index_bands_are_averaged_and_every_band_has_a_rule():
    assert all(
        raster.RASTER_BAND_REDUCERS[band] == "mean" for band in raster.RASTER_INDEX_BANDS
    )
    # No band may be left without a stated rule, and no rule may name a
    # band that is not in the composite.
    assert set(raster.RASTER_BAND_REDUCERS) == set(raster.RASTER_BAND_ORDER)
    assert set(raster.RASTER_BAND_ORDER) == {*raster.RASTER_INDEX_BANDS, raster.RASTER_DATE_BAND}
    assert all(name in raster.NUMPY_BAND_REDUCERS for name in raster.RASTER_BAND_REDUCERS.values())


def test_mode_breaks_a_tie_toward_the_newer_pass_not_between_them():
    tied = np.array([OLD_MS, OLD_MS, NEW_MS, NEW_MS], dtype=np.int64)
    assert raster.NUMPY_BAND_REDUCERS["mode"](tied) == NEW_MS
    assert raster.NUMPY_BAND_REDUCERS["max"](tied) == NEW_MS
    # The reducer that must never be used, shown doing exactly the thing.
    assert raster.NUMPY_BAND_REDUCERS["mean"](tied) not in {OLD_MS, NEW_MS}


# --------------------------------------------------------------------------
# Precision: epoch ms does not fit in float32.
# --------------------------------------------------------------------------


def test_epoch_milliseconds_survive_the_transfer_exactly(monkeypatch):
    _, composite = two_acquisition_composite(monkeypatch)
    arrays = raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)

    dates = arrays[raster.RASTER_DATE_BAND]
    assert dates.dtype == np.int64
    assert set(dates.tolist()) == {OLD_MS, NEW_MS}
    # Not "close to" -- the same integer, to the millisecond.
    assert OLD_MS == epoch_ms(OLD_ISO) and NEW_MS == epoch_ms(NEW_ISO)


def test_a_float32_date_band_is_refused_before_anything_reads_it(monkeypatch):
    """float32 carries ~7 significant digits; epoch ms needs 13. The
    damage is silent -- the value still looks like a date -- so the
    dtype is checked rather than the values."""
    _, composite = two_acquisition_composite(monkeypatch, date_dtype=np.float32)

    with pytest.raises(raster.DateBandPrecisionError) as excinfo:
        raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)
    assert "float32" in str(excinfo.value)


def test_float32_really_would_have_moved_the_timestamp():
    """Why the guard above is not theoretical. float32's spacing at
    1.79e12 is 131,072 ms, so this 2026 acquisition comes back 44 seconds
    late -- small, but no longer equal to any real `system:time_start`,
    which is what the fabrication guard matches on. float64 is exact."""
    narrowed = int(np.float32(NEW_MS))
    assert narrowed != NEW_MS
    assert abs(narrowed - NEW_MS) == 44352
    assert np.spacing(np.float32(NEW_MS)) == 131072.0
    assert int(np.float64(NEW_MS)) == NEW_MS


# --------------------------------------------------------------------------
# Composite construction: bands, masking order, window, no-data.
# --------------------------------------------------------------------------


def test_the_composite_carries_indices_true_color_and_a_shared_date(monkeypatch):
    _, composite = two_acquisition_composite(monkeypatch)
    assert composite["band_order"] == raster.RASTER_STORED_BANDS
    assert set(composite["image"].bands) == set(raster.RASTER_STORED_BANDS)
    assert raster.RASTER_TRUE_COLOR_BANDS == ("true_red", "true_green", "true_blue")
    assert composite["scene_timestamps_ms"] == (OLD_MS, NEW_MS)
    assert composite["scene_ids"] == ("older", "newer")


def test_true_color_and_date_use_the_same_per_pixel_scene_as_ndci(monkeypatch):
    older = dict(BANDS_CLEAR)
    newer = {
        band: np.full(NATIVE_SHAPE, value, dtype=np.float64)
        for band, value in BANDS_BRIGHT.items()
    }
    # Earth Engine normalizedDifference masks this pixel because B4 is
    # negative.  Every companion band must therefore fall back to the older
    # scene too; otherwise the RGB picture would not describe its NDCI/date.
    newer["B4"][0, 0] = -1.0
    install_fake_ee(
        monkeypatch,
        [
            ("older", OLD_ISO, NO_CLOUD, older),
            ("newer", NEW_ISO, NO_CLOUD, newer),
        ],
    )

    composite = raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)
    image = composite["image"]

    assert image.bands[raster.RASTER_DATE_BAND][0, 0] == OLD_MS
    assert image.bands["true_red"][0, 0] == older["B4"]
    assert image.bands["true_green"][0, 0] == older["B3"]
    assert image.bands["true_blue"][0, 0] == older["B2"]
    assert image.bands[raster.RASTER_DATE_BAND][0, 1] == NEW_MS
    assert image.bands["true_red"][0, 1] == BANDS_BRIGHT["B4"]


def test_masking_happens_before_any_index_arithmetic(monkeypatch):
    """Both masks are applied to the raw B2-B6 selection first. A ratio
    computed first and masked second still evaluates over cloud and land
    on the way through, and a division by a near-zero land pixel can
    produce a huge finite value that survives into a neighbouring cell
    once the read is coarsened."""
    recorder = install_fake_ee(monkeypatch, [("only", OLD_ISO, NO_CLOUD, BANDS_CLEAR)])
    raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)

    ops = [op for op, _ in recorder["ops"]]
    mask_positions = [i for i, op in enumerate(ops) if op == "updateMask"]
    math_positions = [
        i for i, op in enumerate(ops)
        if op in {"divide", "subtract", "multiply", "normalizedDifference"}
    ]
    # water mask, then cloud mask, then (and only then) any arithmetic.
    assert len(mask_positions) >= 2
    assert min(math_positions) > mask_positions[1], (
        f"index arithmetic ran at op {min(math_positions)} but the second mask was "
        f"applied at {mask_positions[1]} -- masking must come first"
    )
    # The water mask is selfMask()ed, so non-water is masked out rather
    # than contributing a literal 0.
    assert "selfMask" in ops
    assert ops.index("selfMask") < mask_positions[0]


def test_the_window_uses_the_one_system_wide_scene_age_ceiling(monkeypatch):
    monkeypatch.delenv(sentinel2.MAX_SCENE_AGE_ENV_VAR, raising=False)
    recorder = install_fake_ee(monkeypatch, [("only", "2026-09-06T03:30:00", NO_CLOUD, BANDS_CLEAR)])
    raster.build_index_composite(POLYGON, "2026-09-06")

    assert sentinel2.DEFAULT_MAX_SCENE_AGE_DAYS == 14
    # End bound is exclusive, so +1 day keeps the requested day itself.
    assert recorder["bounds"] == [("2026-08-23", "2026-09-07")]


def test_the_env_override_moves_the_raster_window_too(monkeypatch):
    monkeypatch.setenv(sentinel2.MAX_SCENE_AGE_ENV_VAR, "5")
    recorder = install_fake_ee(monkeypatch, [("only", "2026-09-06T03:30:00", NO_CLOUD, BANDS_CLEAR)])
    raster.build_index_composite(POLYGON, "2026-09-06")
    assert recorder["bounds"] == [("2026-09-01", "2026-09-07")]


def test_a_scene_acquired_after_the_requested_day_is_never_a_candidate(monkeypatch):
    install_fake_ee(monkeypatch, [("future", "2026-09-08T03:30:00", NO_CLOUD, BANDS_CLEAR)])
    with pytest.raises(sentinel2.NoCloudFreeImageryError):
        raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)


def test_an_empty_window_is_reported_not_filled_in(monkeypatch):
    install_fake_ee(monkeypatch, [])
    with pytest.raises(sentinel2.NoCloudFreeImageryError):
        raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)


def test_an_all_land_polygon_reports_no_water_cells(monkeypatch):
    """An empty raster is said plainly, never returned as an array of
    zeros that reads like four real index values."""
    install_fake_ee(
        monkeypatch,
        [("only", OLD_ISO, NO_CLOUD, BANDS_CLEAR)],
        water_mask=np.zeros(NATIVE_SHAPE),
    )
    composite = raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)
    with pytest.raises(sentinel2.NoWaterPixelsError):
        raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)


def test_masked_cells_are_dropped_rather_than_returned_as_zero(monkeypatch):
    """GEE writes 0 into masked pixels of an NPY transfer. A zero index
    reading is legitimate, so it is the date band -- never 0 for a real
    acquisition -- that decides which cells exist."""
    land = np.ones(NATIVE_SHAPE)
    land[0:2, 0:2] = 0  # exactly one coarse cell is land
    install_fake_ee(monkeypatch, [("only", OLD_ISO, NO_CLOUD, BANDS_CLEAR)], water_mask=land)
    composite = raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)

    arrays = raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)
    assert arrays["cell_count"] == 3
    assert arrays["grid_shape"] == (2, 2)
    assert np.all(arrays[raster.RASTER_DATE_BAND] == OLD_MS)


def test_each_cell_carries_the_coordinates_gee_computed_it_at(monkeypatch):
    _, composite = two_acquisition_composite(monkeypatch)
    arrays = raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)

    assert arrays["lat"].shape == arrays["lng"].shape == arrays["ndci"].shape
    assert arrays["lat"].dtype == np.float64 and arrays["lng"].dtype == np.float64
    assert np.all((arrays["lat"] >= 13.0) & (arrays["lat"] <= 13.1))
    assert np.all((arrays["lng"] >= 100.0) & (arrays["lng"] <= 100.1))


def test_the_index_values_are_the_same_arithmetic_the_point_path_uses(monkeypatch):
    """The four raster bands are the per-pixel form of
    detection/src/indices.py's formulas, not a second definition. The
    all-clear cell here is fed by one scene only, so its cell values are
    those formulas evaluated on that scene's band values."""
    install_fake_ee(monkeypatch, [("only", OLD_ISO, NO_CLOUD, BANDS_CLEAR)])
    composite = raster.build_index_composite(POLYGON, "2026-09-06", max_scene_age_days=20)
    arrays = raster.download_composite_arrays(composite, scale_m=2 * NATIVE_SCALE_M)

    b2, b3, b4, b5, b6 = (BANDS_CLEAR[b] for b in ("B2", "B3", "B4", "B5", "B6"))
    assert arrays["ndci"] == pytest.approx((b5 - b4) / (b5 + b4), rel=1e-6)
    assert arrays["bda2"] == pytest.approx(b5 / b4, rel=1e-6)
    assert arrays["bda3"] == pytest.approx((1 / b4 - 1 / b5) * b6, rel=1e-6)
    assert arrays["b2_b3"] == pytest.approx(b2 / b3, rel=1e-6)


# --------------------------------------------------------------------------
# The reduction a raster is kept as after its cells are deleted.
# --------------------------------------------------------------------------


def test_the_summary_averages_the_indices_and_selects_the_date():
    arrays = {
        "ndci": np.array([0.1, 0.3], dtype=np.float32),
        "bda2": np.array([1.0, 2.0], dtype=np.float32),
        "bda3": np.array([0.5, 0.5], dtype=np.float32),
        "b2_b3": np.array([0.8, 1.2], dtype=np.float32),
        raster.RASTER_DATE_BAND: np.array([OLD_MS, NEW_MS, NEW_MS], dtype=np.int64),
    }
    summary = raster.summarize_raster_cells(arrays)

    assert summary["cell_count"] == 3
    assert summary["bands"]["ndci"] == pytest.approx(0.2, rel=1e-5)
    assert summary["bands"][raster.RASTER_DATE_BAND] == NEW_MS
    assert summary["bands"][raster.RASTER_DATE_BAND] in {OLD_MS, NEW_MS}
    # Provenance travels with the numbers: a reader of a year-old summary
    # can see the date was selected and not averaged.
    assert summary["reducers"][raster.RASTER_DATE_BAND] == "mode"
    assert summary["reducers"]["ndci"] == "mean"


def test_an_empty_raster_summarises_as_empty_not_as_zero_readings():
    summary = raster.summarize_raster_cells({raster.RASTER_DATE_BAND: np.array([], dtype=np.int64)})
    assert summary["cell_count"] == 0
    assert summary["bands"] == {}
    assert summary["reducers"][raster.RASTER_DATE_BAND] == "mode"
