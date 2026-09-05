# Upper Gulf Sentinel-2 NDCI Watch Overlay Implementation Plan

> Status correction, 2026-09-06: this is an unimplemented historical proposal in this branch. There is no `/watch-overlay` route or active spectral-index anomaly layer. It is not part of the current removal of invalid anomaly scoring. Current index readings have no anomaly statistic; `/timeseries` MODIS `chlor_a` anomalies remain separate and valid.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add a cached, whole-upper-Gulf Sentinel-2 tile overlay that renders only Gulf-connected clear-water pixels whose five-year seasonal NDCI anomaly is `z >= 1.5`, using a 10 m output grid while disclosing the 20 m effective NDCI source resolution.

**Architecture:** Build and style the raster in Google Earth Engine, refresh it once per backend scheduler cycle, store only tile and run metadata in a singleton SQLAlchemy cache row, expose the cache through `GET /watch-overlay`, and render that URL in Leaflet. Keep the existing six-site `/risk-map` rule-based pipeline unchanged and keep True Color as the reload default.

**Tech Stack:** Python 3.11+, Google Earth Engine Python API, NumPy, PyYAML, FastAPI, SQLAlchemy, Pydantic, pytest, React 19, React-Leaflet 5, Axios, Node's native test runner, Vite, oxlint.

**Spec:** `docs/superpowers/specs/2026-08-27-upper-gulf-ndci-watch-overlay-design.md`

## Global Constraints

- Preserve the dirty frontend worktree and edit only task-related lines. Do not revert the user's map bounds, True Color default, panel removal, or size changes.
- Keep `STUDY_AREA_POLYGON_LATLNG` unchanged. The larger scan geometry is a separate constant.
- Keep data-pipeline, detection, and backend as separate projects and preserve the current namespaced `importlib` bridges.
- Do not add the watch overlay to `risk_level()`, `/risk-map`, `/summary`, or the 14-event validation calculation.
- Do not use trend, SST, rainfall, species inference, or cell-density estimates in this overlay.
- Do not reuse `NdciRasterOverlay.jsx`; it is illustrative noise, not satellite evidence.
- Do not make a live Earth Engine call from `GET /watch-overlay` or from a browser reload.
- Do not commit credentials, `.env` files, tile tokens as source code, or generated databases.
- Call the product **NDCI watch signal (z >= 1.5)** and the mask **Gulf-connected historical surface water**. Never claim bloom confirmation, salinity measurement, or a validated forecast.
- Expose `output_grid_m=10` and `effective_resolution_m=20` together wherever resolution is shown.
- Use project orange `#FF9F0A` for every visible watch pixel. Below-threshold, cloud, invalid, land, disconnected inland water, insufficient-count, and zero-variance pixels stay masked/transparent.
- The approved pipeline call shape is extended with required `gulf_seed_points`, `effective_resolution_m`, and `color` keyword arguments so every approved config value reaches the run without duplicated hard-coded defaults.

## Task 1: Add scan geometry and pure temporal/anomaly primitives

**Files:**

- Modify: `data-pipeline/src/study_area.py`
- Create: `data-pipeline/src/watch_overlay.py`
- Modify: `data-pipeline/src/__init__.py`
- Modify: `data-pipeline/tests/test_study_area.py`
- Create: `data-pipeline/tests/test_watch_overlay.py`

- [ ] **Step 1: Write failing tests for the independent scan polygon**

Add imports and assertions to `data-pipeline/tests/test_study_area.py`:

```python
from src.study_area import (
    STUDY_AREA_POLYGON_LATLNG,
    UPPER_GULF_SCAN_POLYGON_LATLNG,
    upper_gulf_scan_geojson_polygon,
)


def test_scan_polygon_preserves_supplied_vertices_without_replacing_study_area():
    assert UPPER_GULF_SCAN_POLYGON_LATLNG == (
        (13.92257500, 99.29500833),
        (13.92548889, 102.57514444),
        (12.06813056, 102.57761667),
        (12.10439444, 99.31681111),
    )
    assert UPPER_GULF_SCAN_POLYGON_LATLNG != STUDY_AREA_POLYGON_LATLNG


def test_scan_geojson_is_closed_and_uses_lng_lat_order():
    ring = upper_gulf_scan_geojson_polygon()["coordinates"][0]
    assert ring[0] == [99.29500833, 13.922575]
    assert ring[-1] == ring[0]
```

- [ ] **Step 2: Write failing tests for five prior seasonal windows**

Add these tests to `data-pipeline/tests/test_watch_overlay.py`:

```python
from src.watch_overlay import compute_watch_mask, seasonal_windows


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
```

The end date is Earth Engine's exclusive `filterDate` bound, so a `+/- 15 day` window has 31 calendar dates.

- [ ] **Step 3: Write failing tests for threshold, sample-count, and variance masking**

```python
import numpy as np


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
```

- [ ] **Step 4: Run the focused tests and confirm the imports fail**

Run: `cd data-pipeline && ./venv/bin/python -m pytest tests/test_study_area.py tests/test_watch_overlay.py -q`

Expected: FAIL because the scan constant and watch-overlay module do not exist.

- [ ] **Step 5: Implement the scan geometry without changing the current study polygon**

Add to `data-pipeline/src/study_area.py`:

```python
UPPER_GULF_SCAN_POLYGON_LATLNG: tuple[tuple[float, float], ...] = (
    (13.92257500, 99.29500833),
    (13.92548889, 102.57514444),
    (12.06813056, 102.57761667),
    (12.10439444, 99.31681111),
)


def upper_gulf_scan_geojson_polygon() -> dict:
    ring = [[lng, lat] for lat, lng in UPPER_GULF_SCAN_POLYGON_LATLNG]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def upper_gulf_scan_ee_polygon():
    import ee

    ring = [[lng, lat] for lat, lng in UPPER_GULF_SCAN_POLYGON_LATLNG]
    return ee.Geometry.Polygon([ring])
```

- [ ] **Step 6: Implement pure date and anomaly helpers**

Start `data-pipeline/src/watch_overlay.py` with a data-source/limitations module docstring and these pure functions:

```python
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np

NUMERICAL_STD_EPSILON = 1e-6


def _prior_year_anchor(target: date, years_back: int) -> date:
    try:
        return target.replace(year=target.year - years_back)
    except ValueError:
        return target.replace(year=target.year - years_back, day=28)


def seasonal_windows(
    target_date: str, *, baseline_years: int, window_days: int
) -> list[tuple[str, str]]:
    target = date.fromisoformat(target_date)
    windows = []
    for years_back in range(1, baseline_years + 1):
        anchor = _prior_year_anchor(target, years_back)
        start = anchor - timedelta(days=window_days)
        end_exclusive = anchor + timedelta(days=window_days + 1)
        windows.append((start.isoformat(), end_exclusive.isoformat()))
    return windows


def compute_watch_mask(
    latest: Any,
    seasonal_mean: Any,
    seasonal_std: Any,
    observation_count: Any,
    *,
    threshold_z: float,
    min_observations: int,
    std_epsilon: float = NUMERICAL_STD_EPSILON,
) -> np.ndarray:
    latest_arr = np.asarray(latest, dtype=float)
    mean_arr = np.asarray(seasonal_mean, dtype=float)
    std_arr = np.asarray(seasonal_std, dtype=float)
    count_arr = np.asarray(observation_count, dtype=float)
    if not (latest_arr.shape == mean_arr.shape == std_arr.shape == count_arr.shape):
        raise ValueError("latest, mean, std, and count must have identical shapes")
    valid = (
        np.isfinite(latest_arr)
        & np.isfinite(mean_arr)
        & np.isfinite(std_arr)
        & (std_arr > std_epsilon)
        & (count_arr >= min_observations)
    )
    z = np.full(latest_arr.shape, np.nan, dtype=float)
    z[valid] = (latest_arr[valid] - mean_arr[valid]) / std_arr[valid]
    return valid & (z >= threshold_z)
```

- [ ] **Step 7: Re-export the scan constant and watch helpers**

Update `data-pipeline/src/__init__.py` imports and `__all__` with `UPPER_GULF_SCAN_POLYGON_LATLNG`, `seasonal_windows`, and the later public builder name `build_ndci_watch_overlay` once Task 2 adds it.

- [ ] **Step 8: Run focused tests**

Run: `cd data-pipeline && ./venv/bin/python -m pytest tests/test_study_area.py tests/test_watch_overlay.py -q`

Expected: PASS.

- [ ] **Step 9: Commit the pure foundation**

```bash
git add data-pipeline/src/study_area.py data-pipeline/src/watch_overlay.py data-pipeline/src/__init__.py data-pipeline/tests/test_study_area.py data-pipeline/tests/test_watch_overlay.py
git commit -m "feat(data-pipeline): add upper Gulf scan primitives"
```

## Task 2: Build the cloud-filtered, Gulf-connected Earth Engine raster

**Files:**

- Modify: `data-pipeline/src/watch_overlay.py`
- Modify: `data-pipeline/src/__init__.py`
- Modify: `data-pipeline/tests/test_watch_overlay.py`

- [ ] **Step 1: Add failing tests proving one preprocessing path serves current and baseline imagery**

Define a tiny fake collection in the test and verify `_build_source_collections()` calls the same injected builder with the same region, water mask, and output scale for every window:

```python
class FakeCollection:
    def __init__(self, windows):
        self.windows = windows

    def merge(self, other):
        return FakeCollection(self.windows + other.windows)


def test_current_and_baseline_use_identical_masked_ndci_builder():
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
```

Also add a metadata test asserting `output_grid_m == 10`, `effective_resolution_m == 20`, `water_mask == "gulf_connected_historical_surface_water"`, and caveat text contains both “not” and “bloom”.

- [ ] **Step 2: Run the focused test and confirm the orchestration helper is missing**

Run: `cd data-pipeline && ./venv/bin/python -m pytest tests/test_watch_overlay.py -q`

Expected: FAIL on the new imports.

- [ ] **Step 3: Add typed empty-imagery handling and truthful constants**

Add to `watch_overlay.py`:

```python
WATCH_WATER_MASK_LABEL = "gulf_connected_historical_surface_water"
WATCH_CAVEAT = (
    "NDCI watch signal, not bloom confirmation or a forecast. Sediment, optically "
    "complex coastal water, and residual cloud may produce a signal. The 10 m output "
    "grid uses Sentinel-2 B5 with 20 m effective source resolution. The water mask "
    "uses Gulf-connected historical surface water and does not measure salinity."
)


class NoWatchOverlayImageryError(RuntimeError):
    """No Sentinel-2 scene exists in the configured current source window."""
```

- [ ] **Step 4: Build the connected historical-water mask**

Use JRC occurrence and cumulative cost, clipping every intermediate image to the supplied scan region:

```python
def _build_gulf_connected_water_mask(
    region, *, water_occurrence_pct: float, gulf_seed_points: list[list[float]]
):
    occurrence = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    persistent_water = occurrence.gte(water_occurrence_pct).clip(region)
    seed_features = [
        ee.Feature(ee.Geometry.Point([lng, lat])) for lat, lng in gulf_seed_points
    ]
    seeds = ee.Image(0).byte().paint(ee.FeatureCollection(seed_features), 1).selfMask()
    water_cost = ee.Image.constant(1).updateMask(persistent_water)
    reached = water_cost.cumulativeCost(
        source=seeds,
        maxDistance=500_000,
        geodeticDistance=True,
    )
    return persistent_water.updateMask(reached.mask()).rename("gulf_connected_water")
```

The `500_000` value is a traversal ceiling larger than the scan polygon's longest span, not a detection threshold. Document it beside the code.

- [ ] **Step 5: Implement one shared SCL/water/NDCI collection builder**

Reuse `DEFAULT_CLOUD_CLASSES` from `sentinel2.py`; do not create a second invalid-class list:

```python
def _clear_pixel_mask(image):
    scl = image.select("SCL")
    clear = ee.Image.constant(1)
    for scl_class in DEFAULT_CLOUD_CLASSES:
        clear = clear.And(scl.neq(scl_class))
    return clear


def _masked_ndci_image(image, *, region, water_mask, output_scale_m: int):
    b4 = image.select("B4").multiply(0.0001)
    b5 = (
        image.select("B5")
        .multiply(0.0001)
        .resample("bilinear")
        .reproject(crs=b4.projection(), scale=output_scale_m)
    )
    ndci = b5.subtract(b4).divide(b5.add(b4)).rename("ndci")
    ndci = ndci.updateMask(_clear_pixel_mask(image)).updateMask(water_mask).clip(region)
    ndci = ndci.setDefaultProjection(b4.projection().atScale(output_scale_m))
    acquired = ee.Image.constant(ee.Number(image.get("system:time_start")))
    acquired = acquired.rename("acquired_ms").updateMask(ndci.mask())
    return ndci.addBands(acquired).copyProperties(image, ["system:time_start"])


def _build_masked_ndci_collection(
    start: str, end: str, *, region, water_mask, output_scale_m: int
):
    source = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(start, end)
    )
    return source.map(
        lambda image: _masked_ndci_image(
            image,
            region=region,
            water_mask=water_mask,
            output_scale_m=output_scale_m,
        )
    )
```

- [ ] **Step 6: Implement source orchestration, current mosaic, baseline stats, and threshold mask**

`_build_source_collections()` must accept `collection_builder=_build_masked_ndci_collection` so the deterministic unit test can prove reuse. The production builder then performs:

```python
latest = current.qualityMosaic("acquired_ms").select("ndci")
stats = baseline.select("ndci").reduce(
    ee.Reducer.mean()
    .combine(ee.Reducer.stdDev(), sharedInputs=True)
    .combine(ee.Reducer.count(), sharedInputs=True)
)
mean = stats.select("ndci_mean")
std = stats.select("ndci_stdDev")
count = stats.select("ndci_count")
valid_baseline = count.gte(min_baseline_observations).And(std.gt(NUMERICAL_STD_EPSILON))
z = latest.subtract(mean).divide(std).rename("ndci_z").updateMask(valid_baseline)
watch = z.updateMask(z.gte(threshold_z)).clip(region)
styled = watch.visualize(
    min=threshold_z,
    max=threshold_z + 0.01,
    palette=[color.lstrip("#")],
)
```

Compute the current interval as `[target_date - (latest_window_days - 1), target_date + 1 day)`. With the approved value `latest_window_days=30`, it contains exactly 30 calendar dates ending on the requested day. Before `qualityMosaic`, call `current.size().getInfo()` and raise `NoWatchOverlayImageryError` only when there are no source scenes. Fully clouded individual pixels remain transparent.

- [ ] **Step 7: Implement the public builder and return only tile/run metadata**

Use this signature:

```python
def build_ndci_watch_overlay(
    target_date: str,
    *,
    threshold_z: float,
    latest_window_days: int,
    baseline_years: int,
    seasonal_window_days: int,
    min_baseline_observations: int,
    water_occurrence_pct: float,
    gulf_seed_points: list[list[float]],
    output_scale_m: int,
    effective_resolution_m: int,
    color: str,
) -> dict:
```

Call `initialize_ee()` first. Call `styled.getMapId({})`, extract `mapid` and `tile_fetcher.url_format`, and return:

```python
{
    "status": "ok",
    "tile_url": map_info["tile_fetcher"].url_format,
    "map_id": map_info["mapid"],
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "target_date": target_date,
    "source_window_start": current_start,
    "source_window_end": target_date,
    "newest_scene_date": newest_scene_date,
    "baseline_periods": [
        {"start": start, "end_exclusive": end} for start, end in baseline_windows
    ],
    "threshold_z": threshold_z,
    "baseline_years": baseline_years,
    "seasonal_window_days": seasonal_window_days,
    "min_baseline_observations": min_baseline_observations,
    "water_occurrence_pct": water_occurrence_pct,
    "water_mask": WATCH_WATER_MASK_LABEL,
    "output_grid_m": output_scale_m,
    "effective_resolution_m": effective_resolution_m,
    "color": color,
    "caveat": WATCH_CAVEAT,
}
```

Derive `newest_scene_date` from the current source collection's maximum `system:time_start`; label it as the newest available scene, not the date of every mosaic pixel.

- [ ] **Step 8: Re-export the public builder and typed error**

Update `data-pipeline/src/__init__.py` and `__all__` for `build_ndci_watch_overlay` and `NoWatchOverlayImageryError`.

- [ ] **Step 9: Run data-pipeline tests**

Run: `cd data-pipeline && ./venv/bin/python -m pytest tests/ -q`

Expected: PASS without Earth Engine credentials because all new deterministic tests stop at pure/injected boundaries.

- [ ] **Step 10: Commit the Earth Engine builder**

```bash
git add data-pipeline/src/watch_overlay.py data-pipeline/src/__init__.py data-pipeline/tests/test_watch_overlay.py
git commit -m "feat(data-pipeline): build NDCI watch tiles"
```

## Task 3: Add approved configuration and preserve the cross-project bridges

**Files:**

- Modify: `detection/src/config.yaml`
- Modify: `detection/src/_data_pipeline.py`
- Create: `detection/src/watch_overlay.py`
- Create: `detection/tests/test_watch_overlay.py`
- Modify: `backend/src/_detection.py`
- Modify: `backend/tests/test_smoke.py`

- [ ] **Step 1: Write a failing detection wrapper test**

Create `detection/tests/test_watch_overlay.py`:

```python
from src import watch_overlay


def test_configured_overlay_passes_every_approved_value(monkeypatch):
    calls = []

    def fake_builder(target_date, **kwargs):
        calls.append((target_date, kwargs))
        return {"status": "ok"}

    monkeypatch.setattr(watch_overlay, "build_ndci_watch_overlay", fake_builder)
    result = watch_overlay.build_configured_ndci_watch_overlay("2026-08-27")

    assert result == {"status": "ok"}
    assert calls == [("2026-08-27", {
        "threshold_z": 1.5,
        "latest_window_days": 30,
        "baseline_years": 5,
        "seasonal_window_days": 15,
        "min_baseline_observations": 5,
        "water_occurrence_pct": 50.0,
        "gulf_seed_points": [[13.0, 100.7], [13.15, 100.82]],
        "output_scale_m": 10,
        "effective_resolution_m": 20,
        "color": "#FF9F0A",
    })]
```

- [ ] **Step 2: Run the focused test and confirm the module is missing**

Run: `cd detection && ./venv/bin/python -m pytest tests/test_watch_overlay.py -q`

Expected: FAIL because `src/watch_overlay.py` does not exist.

- [ ] **Step 3: Add the approved YAML section verbatim**

Append to `detection/src/config.yaml`:

```yaml
ndci_watch_overlay:
  threshold_z: 1.5
  latest_window_days: 30
  baseline_years: 5
  seasonal_window_days: 15
  min_baseline_observations: 5
  water_occurrence_pct: 50.0
  gulf_seed_points:
    - [13.00, 100.70]
    - [13.15, 100.82]
  output_scale_m: 10
  effective_resolution_m: 20
  color: "#FF9F0A"
```

Precede it with comments stating these are uncalibrated product defaults and are independent of `escalation_rules`.

- [ ] **Step 4: Re-export the raw pipeline operation through detection's existing bridge**

In `detection/src/_data_pipeline.py`, add:

```python
build_ndci_watch_overlay = _dp.build_ndci_watch_overlay
NoWatchOverlayImageryError = _dp.NoWatchOverlayImageryError
```

and add both names to `__all__`.

- [ ] **Step 5: Implement the config-driven detection wrapper**

Create `detection/src/watch_overlay.py` using the same loose-module `sys.path` bootstrap as `prediction.py`:

```python
from _data_pipeline import build_ndci_watch_overlay


def load_watch_overlay_config() -> dict:
    with open(CONFIG_PATH) as config_file:
        return yaml.safe_load(config_file)["ndci_watch_overlay"]


def build_configured_ndci_watch_overlay(
    target_date: str, config: dict | None = None
) -> dict:
    values = config or load_watch_overlay_config()
    return build_ndci_watch_overlay(
        target_date,
        threshold_z=values["threshold_z"],
        latest_window_days=values["latest_window_days"],
        baseline_years=values["baseline_years"],
        seasonal_window_days=values["seasonal_window_days"],
        min_baseline_observations=values["min_baseline_observations"],
        water_occurrence_pct=values["water_occurrence_pct"],
        gulf_seed_points=values["gulf_seed_points"],
        output_scale_m=values["output_scale_m"],
        effective_resolution_m=values["effective_resolution_m"],
        color=values["color"],
    )
```

- [ ] **Step 6: Extend the backend bridge without direct data-pipeline imports**

In `backend/src/_detection.py`, load the new file with `_load_detection_module("watch_overlay.py", "detection_src_watch_overlay")`, then re-export:

```python
build_configured_ndci_watch_overlay = _watch_overlay.build_configured_ndci_watch_overlay
load_watch_overlay_config = _watch_overlay.load_watch_overlay_config
NoWatchOverlayImageryError = _data_pipeline_bridge.NoWatchOverlayImageryError
```

Add a backend smoke assertion that these three bridge names exist and are callable/classes without invoking them.

- [ ] **Step 7: Run detection and bridge smoke tests**

Run: `cd detection && ./venv/bin/python -m pytest tests/ -q`

Run: `cd backend && ./venv/bin/python -m pytest tests/test_smoke.py -q`

Expected: PASS.

- [ ] **Step 8: Commit configuration and bridges**

```bash
git add detection/src/config.yaml detection/src/_data_pipeline.py detection/src/watch_overlay.py detection/tests/test_watch_overlay.py backend/src/_detection.py backend/tests/test_smoke.py
git commit -m "feat(detection): configure NDCI watch overlay"
```

## Task 4: Add the singleton cache, response schema, and cache-only endpoint

**Files:**

- Modify: `backend/src/db_models.py`
- Modify: `backend/src/schemas.py`
- Create: `backend/src/routers/watch_overlay.py`
- Modify: `backend/src/main.py`
- Create: `backend/tests/test_watch_overlay.py`
- Modify: `backend/tests/test_disclaimer.py`

- [ ] **Step 1: Write failing endpoint tests for empty and populated cache states**

Create `backend/tests/test_watch_overlay.py`. Use `SessionLocal`, delete `WatchOverlayCache` at each test boundary, and assert:

```python
def test_watch_overlay_empty_cache_is_explicit_and_has_no_tile(client):
    response = client.get("/watch-overlay")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["tile_url"] is None
    assert body["stale"] is True
    assert "not initialized" in body["error"].lower()
    assert body["disclaimer"]
    assert body["caveat"]


def test_watch_overlay_returns_cached_run_without_calling_gee(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("request path must not call Earth Engine")

    monkeypatch.setattr(main_module.bridge, "build_configured_ndci_watch_overlay", forbidden)
    response = client.get("/watch-overlay")
    body = response.json()
    assert body["status"] == "ok"
    assert body["tile_url"].startswith("https://")
    assert body["threshold_z"] == 1.5
    assert body["output_grid_m"] == 10
    assert body["effective_resolution_m"] == 20
    assert body["water_mask"] == "gulf_connected_historical_surface_water"
```

Insert the populated singleton directly in the test before making the second request.

- [ ] **Step 2: Run the endpoint test and confirm model/route failures**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_watch_overlay.py -q`

Expected: FAIL because the model and route do not exist.

- [ ] **Step 3: Add the cache model as a new table**

Add `WatchOverlayCache` to `backend/src/db_models.py`:

```python
class WatchOverlayCache(Base):
    __tablename__ = "watch_overlay_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String)
    tile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    map_id: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_date: Mapped[str | None] = mapped_column(String, nullable=True)
    source_window_start: Mapped[str | None] = mapped_column(String, nullable=True)
    source_window_end: Mapped[str | None] = mapped_column(String, nullable=True)
    newest_scene_date: Mapped[str | None] = mapped_column(String, nullable=True)
    baseline_periods: Mapped[list | None] = mapped_column(JSON, nullable=True)
    threshold_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seasonal_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_baseline_observations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    water_occurrence_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_mask: Mapped[str | None] = mapped_column(String, nullable=True)
    output_grid_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_resolution_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    caveat: Mapped[str] = mapped_column(Text)
```

This is a new table, so the existing `Base.metadata.create_all()` creates it on startup without altering an existing table.

- [ ] **Step 4: Add a response model separate from rule-based risk schemas**

In `backend/src/schemas.py`, define one backend-owned caveat constant used by both empty and populated responses:

```python
WATCH_OVERLAY_CAVEAT = (
    "NDCI watch signal, not bloom confirmation or a forecast. Sediment, optically "
    "complex coastal water, and residual cloud may produce a signal. The 10 m output "
    "grid uses Sentinel-2 B5 with 20 m effective source resolution. The water mask "
    "uses Gulf-connected historical surface water and does not measure salinity."
)
```

Then add the response model:

```python
class WatchOverlayResponse(DisclaimerMixin):
    status: Literal["ok", "no_imagery", "error"]
    tile_url: str | None = None
    generated_at: str | None = None
    target_date: str | None = None
    source_window_start: str | None = None
    source_window_end: str | None = None
    newest_scene_date: str | None = None
    baseline_periods: list[dict] | None = None
    threshold_z: float | None = None
    baseline_years: int | None = None
    seasonal_window_days: int | None = None
    min_baseline_observations: int | None = None
    water_occurrence_pct: float | None = None
    water_mask: str | None = None
    output_grid_m: int | None = None
    effective_resolution_m: int | None = None
    color: str | None = None
    stale: bool
    error: str | None = None
    caveat: str
```

Do not expose `map_id`; it is scheduler/cache internals and the browser needs only `tile_url`.

- [ ] **Step 5: Implement a strictly DB-only router**

Create `backend/src/routers/watch_overlay.py`. Query `db.get(WatchOverlayCache, 1)`. If absent, return an explicit `status="error"`, `tile_url=None`, `stale=True`, and `WATCH_OVERLAY_CAVEAT` for the empty-cache response. If present, map only database fields into `WatchOverlayResponse`, converting a non-null `generated_at` with `as_aware_utc(row.generated_at).isoformat()`.

The router must not import `_detection`, `ee`, data-pipeline, or scheduler.

- [ ] **Step 6: Register the router and meta endpoint**

Import and include `watch_overlay.router` in `backend/src/main.py`; add `/watch-overlay` to the root endpoint list. Update the module docstring's router count.

- [ ] **Step 7: Enforce the global disclaimer contract**

Extend `backend/tests/test_disclaimer.py` so `/watch-overlay` is among the response-model endpoints checked for `disclaimer`.

- [ ] **Step 8: Run backend endpoint tests**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_watch_overlay.py tests/test_disclaimer.py -q`

Expected: PASS.

- [ ] **Step 9: Commit the cache endpoint**

```bash
git add backend/src/db_models.py backend/src/schemas.py backend/src/routers/watch_overlay.py backend/src/main.py backend/tests/test_watch_overlay.py backend/tests/test_disclaimer.py
git commit -m "feat(backend): expose cached watch overlay"
```

## Task 5: Refresh the overlay through the scheduler with last-good preservation

**Files:**

- Modify: `backend/src/scheduler.py`
- Modify: `backend/tests/test_watch_overlay.py`

- [ ] **Step 1: Add failing scheduler success and failure tests**

Use direct sessions and monkeypatch `scheduler_module.bridge.build_configured_ndci_watch_overlay`. Define the complete successful return fixture at the top of the test module:

```python
def successful_overlay_payload(target_date: str) -> dict:
    return {
        "status": "ok",
        "tile_url": "https://tiles.example/{z}/{x}/{y}",
        "map_id": "pytest-map-id",
        "generated_at": "2026-08-27T02:00:00+00:00",
        "target_date": target_date,
        "source_window_start": "2026-07-29",
        "source_window_end": target_date,
        "newest_scene_date": "2026-08-26",
        "baseline_periods": [
            {"start": "2025-08-12", "end_exclusive": "2025-09-12"},
            {"start": "2024-08-12", "end_exclusive": "2024-09-12"},
            {"start": "2023-08-12", "end_exclusive": "2023-09-12"},
            {"start": "2022-08-12", "end_exclusive": "2022-09-12"},
            {"start": "2021-08-12", "end_exclusive": "2021-09-12"},
        ],
        "threshold_z": 1.5,
        "baseline_years": 5,
        "seasonal_window_days": 15,
        "min_baseline_observations": 5,
        "water_occurrence_pct": 50.0,
        "water_mask": "gulf_connected_historical_surface_water",
        "output_grid_m": 10,
        "effective_resolution_m": 20,
        "color": "#FF9F0A",
        "caveat": WATCH_OVERLAY_CAVEAT,
    }
```

Then add the success and preservation tests:

```python
def test_refresh_watch_overlay_writes_singleton_success(client, monkeypatch):
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda target_date: successful_overlay_payload(target_date),
    )
    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        row = db.get(WatchOverlayCache, 1)
        assert row.status == "ok"
        assert row.tile_url.endswith("/{z}/{x}/{y}")
        assert row.stale is False
        assert row.error is None


def test_refresh_failure_preserves_last_good_tile_and_timestamp(client, monkeypatch):
    successful = successful_overlay_payload("2026-08-27")
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda target_date: successful,
    )
    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        original_tile_url = db.get(WatchOverlayCache, 1).tile_url
        original_generated_at = as_aware_utc(db.get(WatchOverlayCache, 1).generated_at)

    def fail(_target_date):
        raise scheduler_module.bridge.GEEAuthError("forced auth failure")

    monkeypatch.setattr(scheduler_module.bridge, "build_configured_ndci_watch_overlay", fail)
    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-28")
        row = db.get(WatchOverlayCache, 1)
        assert row.tile_url == original_tile_url
        assert as_aware_utc(row.generated_at) == original_generated_at
        assert row.target_date == "2026-08-27"
        assert row.stale is True
        assert "GEEAuthError" in row.error
```

Add a third test: a first-ever `NoWatchOverlayImageryError` creates `status="no_imagery"`, no tile, and truthful configured metadata; a first-ever unexpected exception creates `status="error"`, no tile, and `stale=True`.

- [ ] **Step 2: Run scheduler tests and confirm the refresh function is missing**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_watch_overlay.py -q`

Expected: FAIL on `refresh_watch_overlay` import.

- [ ] **Step 3: Implement successful singleton upsert**

Add `refresh_watch_overlay(db, target_date)` to `backend/src/scheduler.py`. Parse the pipeline's ISO `generated_at` with `datetime.fromisoformat()`. Set `id=1`, copy the returned metadata fields, set `stale=False`, and clear `error`. Never store credentials.

- [ ] **Step 4: Implement failure semantics without destroying the last successful overlay**

Use this branch shape:

```python
except Exception as exc:
    logger.error("scheduler: watch overlay refresh failed: %s: %s", type(exc).__name__, exc)
    if existing is not None and existing.tile_url:
        existing.stale = True
        existing.error = f"{type(exc).__name__}: {exc}"
    else:
        config = bridge.load_watch_overlay_config()
        status = (
            "no_imagery"
            if isinstance(exc, bridge.NoWatchOverlayImageryError)
            else "error"
        )
        row = existing or WatchOverlayCache(id=1)
        if existing is None:
            db.add(row)
        row.status = status
        row.tile_url = None
        row.map_id = None
        row.generated_at = None
        row.target_date = target_date
        row.threshold_z = config["threshold_z"]
        row.baseline_years = config["baseline_years"]
        row.seasonal_window_days = config["seasonal_window_days"]
        row.min_baseline_observations = config["min_baseline_observations"]
        row.water_occurrence_pct = config["water_occurrence_pct"]
        row.water_mask = "gulf_connected_historical_surface_water"
        row.output_grid_m = config["output_scale_m"]
        row.effective_resolution_m = config["effective_resolution_m"]
        row.color = config["color"]
        row.stale = status == "error"
        row.error = f"{type(exc).__name__}: {exc}"
        row.caveat = WATCH_OVERLAY_CAVEAT
    db.commit()
```

Import the `WATCH_OVERLAY_CAVEAT` already defined in Task 4 from `backend/src/schemas.py` into the router and scheduler, avoiding drifting copies.

- [ ] **Step 5: Invoke one overlay refresh per scheduler cycle**

In `refresh_grid()`, call `refresh_watch_overlay(db, target_date)` once after the six-site loop and before closing the session. The overlay function catches and records its own exceptions, so a failed regional scan does not undo or stop point-cache refreshes.

- [ ] **Step 6: Run scheduler and endpoint tests**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_scheduler.py tests/test_watch_overlay.py -q`

Expected: PASS.

- [ ] **Step 7: Commit scheduler integration**

```bash
git add backend/src/scheduler.py backend/src/schemas.py backend/src/routers/watch_overlay.py backend/tests/test_watch_overlay.py
git commit -m "feat(backend): schedule watch overlay refresh"
```

## Task 6: Add frontend API access and deterministic presentation-state logic

**Files:**

- Modify: `frontend/src/api/client.js`
- Create: `frontend/src/utils/watchOverlay.js`
- Create: `frontend/tests/watchOverlay.test.js`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write failing Node-native state tests**

Create `frontend/tests/watchOverlay.test.js`:

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'

import { canRenderWatchTiles, getWatchOverlayMessage } from '../src/utils/watchOverlay.js'

test('renders only a cached tile in watch mode', () => {
  const ready = { status: 'ok', tile_url: 'https://tiles.example/{z}/{x}/{y}', stale: false }
  assert.equal(canRenderWatchTiles('watch', ready), true)
  assert.equal(canRenderWatchTiles('true_color', ready), false)
  assert.equal(canRenderWatchTiles('watch', { ...ready, tile_url: null }), false)
})

test('never describes unavailable pixels as normal', () => {
  assert.match(getWatchOverlayMessage({ status: 'no_imagery', tile_url: null }), /ไม่มีภาพ|no imagery/i)
  assert.match(getWatchOverlayMessage({ status: 'error', tile_url: null, error: 'auth' }), /ไม่พร้อม|unavailable/i)
  assert.match(getWatchOverlayMessage({ status: 'ok', tile_url: 'x', stale: true }), /เก่า|stale/i)
})
```

- [ ] **Step 2: Add the frontend test script and confirm the new module is missing**

Add `"test": "node --test tests/*.test.js"` to `frontend/package.json`.

Run: `cd frontend && npm test`

Expected: FAIL because `src/utils/watchOverlay.js` does not exist.

- [ ] **Step 3: Add the API client operation**

In `frontend/src/api/client.js`:

```javascript
export async function getWatchOverlay() {
  const { data } = await client.get('/watch-overlay')
  return data
}
```

- [ ] **Step 4: Implement pure tile and message guards**

Create `frontend/src/utils/watchOverlay.js`:

```javascript
export function canRenderWatchTiles(mode, overlay) {
  return mode === 'watch' && Boolean(overlay?.tile_url)
}

export function getWatchOverlayMessage(overlay, requestError = null) {
  if (requestError) return 'ชั้นข้อมูล NDCI watch ยังไม่พร้อมใช้งาน'
  if (!overlay) return 'กำลังโหลดชั้นข้อมูล NDCI watch…'
  if (overlay.tile_url && overlay.stale) return 'กำลังแสดงข้อมูลล่าสุดที่แคชไว้ (ข้อมูลเก่า)'
  if (overlay.tile_url) return null
  if (overlay.status === 'no_imagery') return 'ไม่มีภาพ Sentinel-2 ที่ใช้ได้ในช่วง 30 วันล่าสุด'
  return 'ชั้นข้อมูล NDCI watch ยังไม่พร้อมใช้งาน'
}
```

- [ ] **Step 5: Run frontend tests**

Run: `cd frontend && npm test`

Expected: PASS, including the existing map-bounds test.

- [ ] **Step 6: Commit API/state support**

```bash
git add frontend/src/api/client.js frontend/src/utils/watchOverlay.js frontend/tests/watchOverlay.test.js frontend/package.json
git commit -m "feat(frontend): add watch overlay state"
```

## Task 7: Render orange-only tiles and replace the rule-based map presentation

**Files:**

- Modify: `frontend/src/pages/OverviewPage.jsx`
- Modify: `frontend/src/components/RiskMap.jsx`
- Modify: `frontend/src/components/MapControls.jsx`
- Modify: `frontend/src/components/RiskLegend.jsx`
- Modify: `frontend/src/styles/global.css`

- [ ] **Step 1: Fetch the cache independently of the existing six-site cache**

In `OverviewPage.jsx`, retain `useState('true_color')`. Rename the existing `useApi(getRiskMap)` values to `riskData`, `riskLoading`, and `riskError`, then add:

```javascript
const {
  data: watchOverlay,
  loading: watchLoading,
  error: watchError,
  refetch: refetchWatch,
} = useApi(getWatchOverlay, [])
```

Pass `watchOverlay` into `RiskMap` and `RiskLegend`. The map must still render when the watch request fails; failure of `/watch-overlay` must not blank the True Color basemap.

- [ ] **Step 2: Rename only the third tab and preserve the first-tab reload default**

Change `MapControls.jsx` to:

```javascript
const MODES = [
  { value: 'true_color', label: 'True Color (RGB)' },
  { value: 'ndci', label: 'NDCI Index (20m)' },
  { value: 'watch', label: 'NDCI Watch (z >= 1.5)' },
]
```

Do not rename the illustrative NDCI tab into the watch tab; they remain separate modes.

- [ ] **Step 3: Render the real tile layer only in watch mode**

Update `RiskMap` to accept `watchOverlay`. Place the server tile above the basemap:

```jsx
{canRenderWatchTiles(mode, watchOverlay) && (
  <TileLayer
    key={watchOverlay.tile_url}
    url={watchOverlay.tile_url}
    opacity={0.9}
    zIndex={450}
  />
)}
```

Keep `NdciRasterOverlay` restricted to `mode === 'ndci'`.

- [ ] **Step 4: Suppress point markers and feature fitting in watch mode**

Define one list and use it in both existing operations:

```jsx
const visibleFeatures = mode === 'watch' ? [] : features

<FitToFeatures features={visibleFeatures} />
{visibleFeatures.map((feature) => {
```

Keep the current body of the `features.map` callback byte-for-byte from the destructuring of `[lng, lat]` through the closing `CircleMarker`. Only its source array changes from `features` to `visibleFeatures`:

```jsx
      })}
```

When switching to watch mode, set the map view to the established upper-Gulf center and bounds-compatible zoom so the regional scan is centered without adding a right-side panel. Implement this with a small `WatchModeView` component using `useMap()` and `useEffect()`, not by remounting the whole map.

- [ ] **Step 5: Replace the four-tier legend only in watch mode**

In `RiskLegend.jsx`, add a `mode === 'watch'` branch before the current NDCI/risk branches:

```jsx
<>
  <h3>NDCI watch signal</h3>
  <div className="legend-row">
    <span className="legend-swatch watch-overlay" />
    <span>
      <span className="legend-label">เฝ้าระวัง: z ≥ {watchOverlay?.threshold_z ?? 1.5}</span>
      <span className="legend-meaning">สีส้มคือสัญญาณ NDCI สูงกว่าฐานฤดูกาล</span>
    </span>
  </div>
  <div className="legend-row">
    <span className="legend-swatch transparent-overlay" />
    <span className="legend-meaning">
      โปร่งใส: ต่ำกว่าเกณฑ์ เมฆบัง ไม่ใช่น้ำทะเลเชื่อมต่ออ่าว หรือข้อมูลฐานไม่พอ
    </span>
  </div>
  <span className="legend-meaning">
    กริด {watchOverlay?.output_grid_m ?? 10} m; ความละเอียดต้นทาง NDCI {watchOverlay?.effective_resolution_m ?? 20} m
  </span>
</>
```

Do not append the existing “ไม่มีค่าอ่าน” row below this branch; its dotted marker symbol belongs to point data and would misdescribe raster transparency.

- [ ] **Step 6: Show compact loading/stale/error/source-window state**

Use `getWatchOverlayMessage(watchOverlay, watchError)` only when `mode === 'watch'`. Show a compact overlay-state pill near the existing date pill. When ready, show source window and newest available scene date; state clearly that mosaic pixels can come from different dates. When unavailable, include a retry button that calls `refetchWatch` and leave the basemap usable.

Do not render “normal” when the tile is missing. Do not infer a clear reading from transparency.

- [ ] **Step 7: Add minimal styles**

In `global.css`, add watch orange and transparent swatches plus a compact state pill. Use existing glass, border, radius, and typography tokens. Keep the legend smaller than the removed multi-tier version and avoid restoring any right-side panel.

- [ ] **Step 8: Run frontend verification**

Run: `cd frontend && npm test`

Run: `cd frontend && npm run lint`

Run: `cd frontend && npm run build`

Expected: all PASS.

- [ ] **Step 9: Commit the map UI**

```bash
git add frontend/src/pages/OverviewPage.jsx frontend/src/components/RiskMap.jsx frontend/src/components/MapControls.jsx frontend/src/components/RiskLegend.jsx frontend/src/styles/global.css
git commit -m "feat(frontend): render NDCI watch tiles"
```

## Task 8: Document the truth boundary and API behavior

**Files:**

- Modify: `LIMITATIONS.md`
- Modify: `backend/README.md`
- Modify: `data-pipeline/README.md`

- [ ] **Step 1: Add the watch overlay limitations**

Add a focused `LIMITATIONS.md` subsection covering all of these facts:

- `z >= 1.5` is an uncalibrated anomaly-screen threshold, not bloom confirmation.
- NDCI can respond to sediment and optically complex coastal water.
- SCL filtering removes known cloud/invalid classes but residual contamination is possible.
- Transparent pixels can mean below threshold, cloud, land/disconnected water, insufficient baseline, or zero variance; transparency is not “normal”.
- The 10 m output grid resamples B5 and has 20 m effective source resolution.
- JRC Gulf connectivity removes isolated inland water but does not measure salinity; connected estuaries may remain.
- The 30-day quality mosaic can contain pixels from different acquisition dates.
- Cached Earth Engine tile URLs can become unavailable; stale/error state is surfaced.

- [ ] **Step 2: Document `GET /watch-overlay`**

In `backend/README.md`, add the response fields, cache-only request behavior, scheduler refresh behavior, and an example showing `status`, `tile_url`, source window, threshold, both resolution fields, water-mask label, stale/error, disclaimer, and caveat.

- [ ] **Step 3: Document the data-pipeline operation**

In `data-pipeline/README.md`, add the collection ID, SCL invalid classes, JRC occurrence/connectivity approach, seasonal windows, 30-day latest-valid-pixel composite, and optional credentialed smoke command.

- [ ] **Step 4: Scan documentation for forbidden claims**

Run:

```bash
rg -n "bloom confirmed|salinity mask|validated forecast|10 m resolution" LIMITATIONS.md backend/README.md data-pipeline/README.md frontend/src backend/src data-pipeline/src
```

Expected: no new claim says the overlay confirms blooms, measures salinity, is a validated forecast, or has true 10 m NDCI source resolution. Legitimate pre-existing text must be read in context rather than mechanically changed.

- [ ] **Step 5: Commit documentation**

```bash
git add LIMITATIONS.md backend/README.md data-pipeline/README.md
git commit -m "docs: explain NDCI watch limitations"
```

## Task 9: Run complete deterministic verification and optional live smoke check

**Files:**

- Verify only; modify task-related files only if a command exposes a defect.

- [ ] **Step 1: Run every Python service suite in its own environment**

Run: `cd data-pipeline && ./venv/bin/python -m pytest tests/ -q`

Run: `cd detection && ./venv/bin/python -m pytest tests/ -q`

Run: `cd backend && ./venv/bin/python -m pytest tests/ -q`

Expected: all PASS; no deterministic suite requires live Earth Engine.

- [ ] **Step 2: Run every frontend gate**

Run: `cd frontend && npm test`

Run: `cd frontend && npm run lint`

Run: `cd frontend && npm run build`

Expected: all PASS.

- [ ] **Step 3: Verify reload and endpoint isolation locally**

Start the backend and frontend with `./scripts/dev.sh`. In the browser network panel:

- reload once and confirm `GET /risk-map` and `GET /watch-overlay` are cache reads;
- confirm no browser request invokes a scan endpoint or waits for a live GEE operation;
- confirm True Color is active after reload;
- switch to NDCI Watch and confirm point markers disappear;
- confirm only orange raster pixels appear;
- confirm the right side remains map, with no blank panel;
- confirm stale/error/no-imagery states leave the basemap operational.

- [ ] **Step 4: Run the optional credentialed Earth Engine smoke check**

Only when `EE_PROJECT_ID` and Earth Engine credentials are already configured, run from `detection/`:

```bash
./venv/bin/python -c "from src.watch_overlay import build_configured_ndci_watch_overlay; r=build_configured_ndci_watch_overlay('2026-08-27'); print({k: r[k] for k in ('status','target_date','source_window_start','source_window_end','newest_scene_date','threshold_z','output_grid_m','effective_resolution_m','water_mask')}); print(r['tile_url'])"
```

Expected: `status` is `ok`, metadata matches the configured run, and the printed tile template serves map tiles. If credentials are absent, report that the optional smoke check was skipped; do not weaken the auth guard or fabricate a result.

- [ ] **Step 5: Inspect final scope and commits**

Run: `git status --short`

Run: `git diff --stat c739df3..HEAD`

Run: `git log --oneline --decorate -10`

Expected: only the approved overlay implementation plus the user's pre-existing dirty frontend edits are present; no secrets or generated databases are tracked.

- [ ] **Step 6: Request focused code review before handoff**

Use the `requesting-code-review` skill to review spec compliance, truth-boundary language, Earth Engine masking semantics, cache failure preservation, and frontend mode isolation. Apply only in-scope fixes, rerun the affected gates, and report the exact commands and outcomes.
