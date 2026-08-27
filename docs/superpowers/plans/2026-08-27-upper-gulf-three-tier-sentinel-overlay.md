# Upper Gulf Three-Tier Sentinel-2 Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the orange-only regional NDCI watch tile with one cached three-tier Sentinel-2/SST raster and show pins only for non-normal samples at the six existing monitoring sites.

**Architecture:** Google Earth Engine builds one masked class raster from Sentinel-2 seasonal NDCI anomaly, a per-pixel 14-day Sentinel-2 NDCI trend, and MODIS-Aqua SST. The scheduler samples that same raster at the six configured sites, stores the tile and typed analysis metadata in a compatibility-migrated singleton cache, and `/watch-overlay` remains database-only. Leaflet renders the tile in scan mode and renders only cached `elevated`, `watch`, or `warning` site alerts in True Color and scan modes.

**Tech Stack:** Python 3.11, NumPy, Google Earth Engine Python API, PyYAML, FastAPI, Pydantic, SQLAlchemy, pytest, React 19, React-Leaflet/Leaflet, Vite, Node test runner, oxlint.

**Spec:** `docs/superpowers/specs/2026-08-27-upper-gulf-three-tier-sentinel-overlay-design.md`

## Global Constraints

- Use the approved scan polygon with rectangular Leaflet bounds `[[12.06813056, 99.29500833], [13.92548889, 102.57761667]]`.
- Candidate water is JRC occurrence `>= 50%` connected to the approved Gulf seeds; each Sentinel-2 observation must also have SCL class 6.
- Select Sentinel-2 B2, B3, B4, B5, B6, SCL, and QA60; reject QA60 cloud bit 10 and cirrus bit 11.
- Do not invent a B2/B3/B6 reflectance-range or turbidity threshold. B2, B3, and B6 contribute source-mask validity and diagnostics only.
- Current NDCI uses the latest usable pixel in 30 days; baseline uses five prior years, each within `+/-15` days, with at least five observations and non-zero variance.
- Trend uses the 14 calendar days ending on the target date, one median observation per UTC date, at least two distinct dates, and `slope > 0`.
- SST uses `NASA/OCEANDATA/MODIS-Aqua/L3SMI`, nearest valid SST within five days (later observation wins a tie), and prior-year seasonal mean within `+/-7` day-of-year.
- Class 1 `elevated` / `เริ่มผิดปกติ` / `#34C759`: `z >= 1.5`.
- Class 2 `watch` / `เฝ้าระวัง` / `#FF9F0A`: `z >= 1.5` and rising trend.
- Class 3 `warning` / `เตือนภัย` / `#FF3B30`: `z >= 2.0`, rising trend, and SST above normal.
- Highest satisfied class wins. Missing trend or SST never causes escalation.
- Normal, cloud, land, invalid, and insufficient-data pixels stay transparent and are never described as confirmed normal.
- Return no normal/no-data site alerts. Pins must sample the same regional class image rather than reuse `/risk-map` levels.
- Preserve True Color as reload default, the full-bounds fit/zoom lock, the removed right-side panel, and the cache-only browser request path.
- The output grid is 10 m; disclose 20 m effective NDCI/trend resolution and approximately 4,638 m SST resolution.
- Keep detection and indicative rule-based prediction separate. Do not modify the locked 14-event validation set or report a validation percentage.
- Never commit `.env`, credentials, generated databases, or virtual-environment links.

---

### Task 1: Add pure three-tier classification and trend rules

**Files:**
- Create: `data-pipeline/src/watch_rules.py`
- Create: `data-pipeline/tests/test_watch_rules.py`
- Modify: `data-pipeline/src/__init__.py`

**Interfaces:**
- Consumes: NumPy arrays or array-like values for z-score, slope, trend date count, current SST, and seasonal SST.
- Produces: `classify_levels(...) -> np.ndarray[np.uint8]`, `linear_daily_trend(observations) -> dict`, `qa60_clear(values) -> np.ndarray[bool]`, and class constants `LEVEL_NONE`, `LEVEL_ELEVATED`, `LEVEL_WATCH`, `LEVEL_WARNING`.

- [ ] **Step 1: Write failing classification tests**

Create `data-pipeline/tests/test_watch_rules.py`:

```python
import numpy as np

from src.watch_rules import (
    LEVEL_ELEVATED,
    LEVEL_NONE,
    LEVEL_WARNING,
    LEVEL_WATCH,
    classify_levels,
    linear_daily_trend,
    qa60_clear,
)


def test_classify_levels_uses_highest_proven_rule_and_safe_downgrades():
    result = classify_levels(
        z=[1.49, 1.50, 1.80, 2.20, 2.20, np.nan],
        slope_per_day=[0.1, np.nan, 0.02, 0.03, -0.01, 0.1],
        trend_observations=[3, 0, 2, 2, 3, 3],
        current_sst=[30, 30, np.nan, 30, 30, 30],
        seasonal_sst=[29, 29, np.nan, 29, 29, 29],
        elevated_z=1.5,
        warning_z=2.0,
        min_trend_observations=2,
    )
    assert result.tolist() == [
        LEVEL_NONE,
        LEVEL_ELEVATED,
        LEVEL_WATCH,
        LEVEL_WARNING,
        LEVEL_ELEVATED,
        LEVEL_NONE,
    ]


def test_linear_daily_trend_deduplicates_dates_with_a_median():
    result = linear_daily_trend([
        ("2026-08-14", 0.10),
        ("2026-08-14", 0.30),
        ("2026-08-20", 0.40),
    ])
    assert result["distinct_dates"] == 2
    assert result["daily_values"] == [
        {"date": "2026-08-14", "ndci": 0.20},
        {"date": "2026-08-20", "ndci": 0.40},
    ]
    assert result["slope_per_day"] > 0
    assert result["rising"] is True


def test_linear_daily_trend_requires_two_dates():
    result = linear_daily_trend([("2026-08-20", 0.40)])
    assert result == {
        "daily_values": [{"date": "2026-08-20", "ndci": 0.40}],
        "distinct_dates": 1,
        "slope_per_day": None,
        "rising": False,
    }


def test_qa60_clear_rejects_cloud_and_cirrus_bits():
    values = np.array([0, 1 << 10, 1 << 11, (1 << 10) | (1 << 11)])
    assert qa60_clear(values).tolist() == [True, False, False, False]
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
cd data-pipeline
./venv/bin/python -m pytest tests/test_watch_rules.py -q
```

Expected: FAIL during collection because `src.watch_rules` does not exist.

- [ ] **Step 3: Implement the pure rules**

Create `data-pipeline/src/watch_rules.py` with a data-source/limitations docstring and these exact public functions:

```python
from collections import defaultdict
from datetime import date

import numpy as np

LEVEL_NONE = 0
LEVEL_ELEVATED = 1
LEVEL_WATCH = 2
LEVEL_WARNING = 3


def qa60_clear(values):
    qa = np.asarray(values, dtype=np.uint16)
    return ((qa & (1 << 10)) == 0) & ((qa & (1 << 11)) == 0)


def classify_levels(
    *, z, slope_per_day, trend_observations, current_sst, seasonal_sst,
    elevated_z: float, warning_z: float, min_trend_observations: int,
):
    z_arr = np.asarray(z, dtype=float)
    slope = np.asarray(slope_per_day, dtype=float)
    count = np.asarray(trend_observations, dtype=float)
    current = np.asarray(current_sst, dtype=float)
    seasonal = np.asarray(seasonal_sst, dtype=float)
    if not (z_arr.shape == slope.shape == count.shape == current.shape == seasonal.shape):
        raise ValueError("all classification inputs must have identical shapes")

    result = np.zeros(z_arr.shape, dtype=np.uint8)
    elevated = np.isfinite(z_arr) & (z_arr >= elevated_z)
    rising = np.isfinite(slope) & (count >= min_trend_observations) & (slope > 0)
    sst_above = np.isfinite(current) & np.isfinite(seasonal) & (current > seasonal)
    result[elevated] = LEVEL_ELEVATED
    result[elevated & rising] = LEVEL_WATCH
    result[(z_arr >= warning_z) & rising & sst_above] = LEVEL_WARNING
    return result


def linear_daily_trend(observations):
    by_date = defaultdict(list)
    for date_string, value in observations:
        if value is not None and np.isfinite(float(value)):
            by_date[date.fromisoformat(date_string)].append(float(value))
    daily = [(day, float(np.median(values))) for day, values in sorted(by_date.items())]
    serialized = [{"date": day.isoformat(), "ndci": value} for day, value in daily]
    if len(daily) < 2:
        return {"daily_values": serialized, "distinct_dates": len(daily), "slope_per_day": None, "rising": False}
    x = np.array([(day - daily[0][0]).days for day, _ in daily], dtype=float)
    y = np.array([value for _, value in daily], dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return {"daily_values": serialized, "distinct_dates": len(daily), "slope_per_day": slope, "rising": slope > 0}
```

Export the four constants and three functions from `data-pipeline/src/__init__.py` without changing existing exports.

- [ ] **Step 4: Run focused and full data-pipeline tests**

Run:

```bash
cd data-pipeline
./venv/bin/python -m pytest tests/test_watch_rules.py -q
./venv/bin/python -m pytest tests/ -q
```

Expected: new focused tests PASS; existing suite remains green without Earth Engine credentials.

- [ ] **Step 5: Commit the pure rule layer**

```bash
git add data-pipeline/src/watch_rules.py data-pipeline/src/__init__.py data-pipeline/tests/test_watch_rules.py
git commit -m "feat(data-pipeline): add three-tier watch rules"
```

---

### Task 2: Build the SCL/QA60 water mask and 14-day Sentinel-2 trend

**Files:**
- Modify: `data-pipeline/src/watch_overlay.py`
- Modify: `data-pipeline/tests/test_watch_overlay.py`

**Interfaces:**
- Consumes: the connected JRC water mask, Sentinel-2 B2-B6/SCL/QA60 images, current/baseline date windows, `trend_window_days`, and `min_trend_observations`.
- Produces: `_usable_water_pixel_mask(image, connected_water)`, `_masked_ndci_image(...)` with `ndci`, `acquired_ms`, and `acquired_day` bands, `_daily_ndci_collection(...)`, and `_build_trend_image(...)` returning `ndci_slope_per_day` plus `trend_observation_count`.

- [ ] **Step 1: Add failing mask and date-window tests**

Extend `data-pipeline/tests/test_watch_overlay.py` with credential-free tests that use operation-recording fake bands:

```python
def test_usable_water_mask_requires_scl_water_and_clear_qa60(monkeypatch):
    graph = OperationGraph()
    image = FakeMaskImage(graph, {"SCL": 6, "QA60": 0})
    result = watch_overlay._usable_water_pixel_mask(image, "connected-water")
    assert graph.selected == ["SCL", "QA60"]
    assert ("eq", "SCL", 6) in graph.operations
    assert ("bitwiseAnd", "QA60", 1 << 10) in graph.operations
    assert ("bitwiseAnd", "QA60", 1 << 11) in graph.operations
    assert graph.combined_with_connected_water
    assert result is graph.final_mask


def test_trend_window_is_fourteen_calendar_days_ending_on_target():
    assert watch_overlay.trend_window("2026-08-27", 14) == (
        "2026-08-14",
        "2026-08-28",
    )
```

Define `OperationGraph` and `FakeMaskImage` inside the test module with `select`, `eq`, `bitwiseAnd`, `And`, and `updateMask` methods that append the tuples asserted above. Do not import or initialize live Earth Engine.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd data-pipeline
./venv/bin/python -m pytest tests/test_watch_overlay.py -q
```

Expected: FAIL because `_usable_water_pixel_mask` and `trend_window` do not exist and `_masked_ndci_image` does not select QA60/B2/B3/B6.

- [ ] **Step 3: Replace the per-scene mask with SCL water plus QA60**

In `data-pipeline/src/watch_overlay.py`, add:

```python
NDCI_DENOMINATOR_EPSILON = 1e-6


def trend_window(target_date: str, window_days: int) -> tuple[str, str]:
    target = date.fromisoformat(target_date)
    return (
        (target - timedelta(days=window_days - 1)).isoformat(),
        (target + timedelta(days=1)).isoformat(),
    )


def _usable_water_pixel_mask(image, connected_water):
    scl_water = image.select("SCL").eq(6)
    qa60 = image.select("QA60")
    qa_clear = qa60.bitwiseAnd(1 << 10).eq(0).And(
        qa60.bitwiseAnd(1 << 11).eq(0)
    )
    source_valid = image.select(["B2", "B3", "B4", "B5", "B6"]).mask().reduce(
        ee.Reducer.min()
    )
    return connected_water.And(scl_water).And(qa_clear).And(source_valid)
```

Update `_masked_ndci_image` to select and scale all B2-B6 bands, apply `_usable_water_pixel_mask`, mask `abs(B5+B4) <= NDCI_DENOMINATOR_EPSILON`, and preserve B2/B3/B6 only as diagnostic bands. Do not add brightness, reflectance-range, or turbidity thresholds.

- [ ] **Step 4: Add one median image per UTC date and linear-fit bands**

Implement:

```python
def _daily_ndci_collection(collection, start: str, end: str):
    day_count = (date.fromisoformat(end) - date.fromisoformat(start)).days
    images = []
    for offset in range(day_count):
        day = date.fromisoformat(start) + timedelta(days=offset)
        next_day = day + timedelta(days=1)
        daily = collection.filterDate(day.isoformat(), next_day.isoformat())
        daily_ndci = daily.select("ndci").median().rename("ndci")
        acquired_day = ee.Image.constant(offset).rename("elapsed_days").toFloat()
        images.append(daily_ndci.addBands(acquired_day).set("observation_date", day.isoformat()))
    return ee.ImageCollection.fromImages(images)


def _build_trend_image(daily_collection, *, min_observations: int):
    count = daily_collection.select("ndci").count().rename("trend_observation_count")
    fit = daily_collection.select(["elapsed_days", "ndci"]).reduce(ee.Reducer.linearFit())
    slope = fit.select("scale").rename("ndci_slope_per_day")
    return slope.updateMask(count.gte(min_observations)).addBands(count)
```

Ensure empty dates remain masked and therefore do not increment `count`. Use the exact 14-day window from `trend_window`; current/baseline collections continue to use the same `_masked_ndci_image` preprocessing.

- [ ] **Step 5: Add a graph test for same-day median and count wiring**

Add a fake-collection test asserting that `_daily_ndci_collection` calls `filterDate` once per calendar day and `median`, and that `_build_trend_image` selects `elapsed_days` before `ndci`, uses `ee.Reducer.linearFit()`, and masks slope by `count >= 2`.

- [ ] **Step 6: Run focused and full data-pipeline suites**

```bash
cd data-pipeline
./venv/bin/python -m pytest tests/test_watch_overlay.py tests/test_watch_rules.py -q
./venv/bin/python -m pytest tests/ -q
```

Expected: all credential-free tests PASS.

- [ ] **Step 7: Commit the Sentinel trend graph**

```bash
git add data-pipeline/src/watch_overlay.py data-pipeline/tests/test_watch_overlay.py
git commit -m "feat(data-pipeline): add masked Sentinel trend"
```

---

### Task 3: Build SST support, the three-color tile, and site-alert samples

**Files:**
- Modify: `data-pipeline/src/watch_overlay.py`
- Modify: `data-pipeline/tests/test_watch_overlay.py`
- Modify: `data-pipeline/src/__init__.py`

**Interfaces:**
- Consumes: Task 1 class constants, Task 2 current/baseline/trend images, MODIS-Aqua SST, exact level thresholds/colors, and `monitoring_sites: list[dict]` containing `site_id`, `name`, `lat`, and `lng`.
- Produces: the expanded `build_ndci_watch_overlay(...) -> dict` contract with one three-color tile and `analysis_metadata.site_alerts` filtered to classes 1-3.

- [ ] **Step 1: Write failing SST-window and site-alert parsing tests**

Add to `data-pipeline/tests/test_watch_overlay.py`:

```python
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
        {"properties": {"site_id": "a", "name": "A", "lat": 13.0, "lng": 100.7, "level_code": 0}},
        {"properties": {"site_id": "b", "name": "B", "lat": 13.1, "lng": 100.8, "level_code": 1, "ndci_z": 1.7, "ndci_slope_per_day": None, "trend_observation_count": 1, "latest_acquired_ms": 1785283200000, "current_sst": None, "seasonal_sst": None, "sst_acquired_ms": None}},
        {"properties": {"site_id": "c", "name": "C", "lat": 13.2, "lng": 100.9, "level_code": 3, "ndci_z": 2.4, "ndci_slope_per_day": 0.01, "trend_observation_count": 3, "latest_acquired_ms": 1785283200000, "current_sst": 30.2, "seasonal_sst": 29.8, "sst_acquired_ms": 1785196800000}},
        {"properties": {"site_id": "d", "name": "D", "lat": 13.3, "lng": 101.0}},
    ]
    alerts = watch_overlay._parse_site_alerts(sampled, level_definitions=LEVEL_DEFINITIONS)
    assert [item["site_id"] for item in alerts] == ["b", "c"]
    assert [item["level"] for item in alerts] == ["elevated", "warning"]
    assert alerts[0]["trend_rising"] is False
    assert alerts[1]["sst_above_normal"] is True
    assert all(item["level"] != "normal" for item in alerts)
```

Define `LEVEL_DEFINITIONS` in the test with the exact three codes, Thai labels, colors, class numbers, and rule flags from the spec.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd data-pipeline
./venv/bin/python -m pytest tests/test_watch_overlay.py -q
```

Expected: FAIL because the SST-window and site-alert helpers do not exist.

- [ ] **Step 3: Build current and seasonal SST images**

Add constants and helpers to `watch_overlay.py`:

```python
MODIS_SST_COLLECTION_ID = "NASA/OCEANDATA/MODIS-Aqua/L3SMI"
MODIS_SST_ARCHIVE_START_DATE = "2002-07-04"


def sst_seasonal_windows(target_date: str, *, archive_start_date: str, window_days: int):
    target = date.fromisoformat(target_date)
    archive_start = date.fromisoformat(archive_start_date)
    windows = []
    for year in range(archive_start.year, target.year):
        try:
            anchor = target.replace(year=year)
        except ValueError:
            anchor = target.replace(year=year, day=28)
        start = anchor - timedelta(days=window_days)
        end_exclusive = anchor + timedelta(days=window_days + 1)
        if end_exclusive > archive_start:
            windows.append((max(start, archive_start).isoformat(), end_exclusive.isoformat()))
    return windows
```

Implement `_build_sst_images(...)` using `MODIS_SST_COLLECTION_ID`. For current SST, filter target `-5` through target `+5` inclusive. Add this scalar quality score to each image, where the `0.1` tie breaker cannot outweigh a one-day distance:

```python
acquired_ms = ee.Number(image.get("system:time_start"))
distance_days = acquired_ms.subtract(target_ms).abs().divide(86_400_000)
later_tie_breaker = acquired_ms.gte(target_ms).multiply(0.1)
quality = ee.Image.constant(distance_days.multiply(-1).add(later_tie_breaker)).rename("sst_quality")
```

Mask the score with the SST band and use `qualityMosaic("sst_quality")` so masked pixels select their nearest available date independently. Return `current_sst`, `sst_acquired_ms`, `seasonal_sst`, and `seasonal_sst_count`; mask the seasonal mean where count is zero.

- [ ] **Step 4: Replace the orange watch image with an auditable class image**

Implement `_build_classification_image(...)` with this exact precedence:

```python
elevated = z.gte(elevated_z)
rising = trend_count.gte(min_trend_observations).And(slope.gt(0))
sst_above = current_sst.gt(seasonal_sst)

level = ee.Image.constant(1).rename("level_code").updateMask(elevated)
level = level.where(elevated.And(rising), 2)
level = level.where(z.gte(warning_z).And(rising).And(sst_above), 3)
```

Add supporting bands `ndci_z`, `latest_acquired_ms`, `ndci_slope_per_day`, `trend_observation_count`, `current_sst`, `seasonal_sst`, and `sst_acquired_ms`. Visualize only `level_code` using `min=1`, `max=3`, and `[green, orange, red]` in class order.

- [ ] **Step 5: Sample the six sites from the final analysis image**

Create a FeatureCollection from the passed `monitoring_sites`, preserve stable site properties, and call `sampleRegions` at 20 m scale with geometries disabled. Convert the returned `features` through `_parse_site_alerts`. The parser must whitelist only class codes 1, 2, and 3, convert millisecond timestamps to UTC dates, retain nullable support fields, and sort by input-site order.

Use this result shape:

```python
{
    "site_id": "chaophraya_mouth",
    "name": "Chao Phraya River mouth, Samut Prakan",
    "lat": 13.45,
    "lng": 100.65,
    "level": "warning",
    "label_th": "เตือนภัย",
    "color": "#FF3B30",
    "ndci_z": 2.4,
    "latest_scene_date": "2026-08-26",
    "trend_slope_per_day": 0.01,
    "trend_observations": 3,
    "trend_rising": True,
    "current_sst": 30.2,
    "seasonal_sst": 29.8,
    "sst_date": "2026-08-25",
    "sst_above_normal": True,
}
```

- [ ] **Step 6: Expand the public builder and metadata contract**

Change the builder signature to:

```python
def build_ndci_watch_overlay(
    target_date: str,
    *,
    threshold_z: float,
    warning_threshold_z: float,
    latest_window_days: int,
    baseline_years: int,
    seasonal_window_days: int,
    min_baseline_observations: int,
    trend_window_days: int,
    min_trend_observations: int,
    sst_search_window_days: int,
    sst_climatology_window_days: int,
    sst_resolution_m: int,
    water_occurrence_pct: float,
    gulf_seed_points: list[list[float]],
    output_scale_m: int,
    effective_resolution_m: int,
    level_colors: dict[str, str],
    monitoring_sites: list[dict],
) -> dict:
```

Preserve legacy `threshold_z` and `color` (`color` remains the watch orange) in the top-level response. Build this exact metadata shape, inserting the per-run source dates and parsed alerts:

```python
analysis_metadata = {
    "version": 2,
    "levels": [
        {"code": "elevated", "class_code": 1, "label_th": "เริ่มผิดปกติ", "color": level_colors["elevated"], "min_z": threshold_z, "requires_rising_trend": False, "requires_sst_above_normal": False},
        {"code": "watch", "class_code": 2, "label_th": "เฝ้าระวัง", "color": level_colors["watch"], "min_z": threshold_z, "requires_rising_trend": True, "requires_sst_above_normal": False},
        {"code": "warning", "class_code": 3, "label_th": "เตือนภัย", "color": level_colors["warning"], "min_z": warning_threshold_z, "requires_rising_trend": True, "requires_sst_above_normal": True},
    ],
    "trend": {"window_days": trend_window_days, "min_distinct_dates": min_trend_observations, "slope_units": "ndci_per_day", "rising_rule": "slope_per_day > 0"},
    "sst": {"collection_id": MODIS_SST_COLLECTION_ID, "search_window_days": sst_search_window_days, "climatology_window_days": sst_climatology_window_days, "resolution_m": sst_resolution_m, "above_normal_rule": "current_sst > seasonal_sst"},
    "masks": {"water_mask": WATCH_WATER_MASK_LABEL, "water_occurrence_pct": water_occurrence_pct, "scl_water_class": 6, "qa60_cloud_bit": 10, "qa60_cirrus_bit": 11},
    "resolutions": {"output_grid_m": output_scale_m, "ndci_m": effective_resolution_m, "trend_m": effective_resolution_m, "sst_m": sst_resolution_m},
    "newest_sentinel_scene_date": newest_scene_date,
    "newest_sst_scene_date": newest_sst_scene_date,
    "mosaic_caveat": "Sentinel-2 and SST mosaic pixels may come from different dates.",
    "site_alerts": site_alerts,
}
```

Return it under top-level key `analysis_metadata`.

- [ ] **Step 7: Update tile-contract tests and run the suite**

Update the existing fake builder test to pass every new keyword and assert:

```python
assert result["threshold_z"] == 1.5
assert result["color"] == "#FF9F0A"
assert result["analysis_metadata"]["version"] == 2
assert [level["code"] for level in result["analysis_metadata"]["levels"]] == ["elevated", "watch", "warning"]
assert result["analysis_metadata"]["resolutions"] == {"output_grid_m": 10, "ndci_m": 20, "trend_m": 20, "sst_m": 4638}
assert all(alert["level"] != "normal" for alert in result["analysis_metadata"]["site_alerts"])
```

Run:

```bash
cd data-pipeline
./venv/bin/python -m pytest tests/test_watch_overlay.py tests/test_watch_rules.py -q
./venv/bin/python -m pytest tests/ -q
```

Expected: all credential-free tests PASS.

- [ ] **Step 8: Commit the integrated raster builder**

```bash
git add data-pipeline/src/watch_overlay.py data-pipeline/src/__init__.py data-pipeline/tests/test_watch_overlay.py
git commit -m "feat(data-pipeline): build three-tier Gulf tiles"
```

---

### Task 4: Configure and bridge the expanded overlay contract

**Files:**
- Modify: `detection/src/config.yaml`
- Modify: `detection/src/watch_overlay.py`
- Modify: `detection/tests/test_watch_overlay.py`
- Modify: `detection/src/_data_pipeline.py`
- Modify: `backend/src/_detection.py`
- Modify: `backend/tests/test_smoke.py`

**Interfaces:**
- Consumes: Task 3 `build_ndci_watch_overlay(...)` and `monitoring_sites: list[dict]` from the scheduler.
- Produces: `build_configured_ndci_watch_overlay(target_date, monitoring_sites, config=None) -> dict` with every operating value passed explicitly.

- [ ] **Step 1: Update the config-wrapper test first**

Replace the expected call in `detection/tests/test_watch_overlay.py` with:

```python
sites = [{"site_id": "a", "name": "A", "lat": 13.0, "lng": 100.7}]
result = watch_overlay.build_configured_ndci_watch_overlay("2026-08-27", sites)
assert result == {"status": "ok"}
assert calls == [("2026-08-27", {
    "threshold_z": 1.5,
    "warning_threshold_z": 2.0,
    "latest_window_days": 30,
    "baseline_years": 5,
    "seasonal_window_days": 15,
    "min_baseline_observations": 5,
    "trend_window_days": 14,
    "min_trend_observations": 2,
    "sst_search_window_days": 5,
    "sst_climatology_window_days": 7,
    "sst_resolution_m": 4638,
    "water_occurrence_pct": 50.0,
    "gulf_seed_points": [[13.0, 100.7], [13.15, 100.82]],
    "output_scale_m": 10,
    "effective_resolution_m": 20,
    "level_colors": {"elevated": "#34C759", "watch": "#FF9F0A", "warning": "#FF3B30"},
    "monitoring_sites": sites,
})]
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
cd detection
./venv/bin/python -m pytest tests/test_watch_overlay.py -q
```

Expected: FAIL because the wrapper has the old signature and old kwargs.

- [ ] **Step 3: Replace the orange-only config with explicit operating values**

Update `ndci_watch_overlay` in `detection/src/config.yaml`:

```yaml
ndci_watch_overlay:
  threshold_z: 1.5
  warning_threshold_z: 2.0
  latest_window_days: 30
  baseline_years: 5
  seasonal_window_days: 15
  min_baseline_observations: 5
  trend_window_days: 14
  min_trend_observations: 2
  sst_search_window_days: 5
  sst_climatology_window_days: 7
  sst_resolution_m: 4638
  water_occurrence_pct: 50.0
  gulf_seed_points:
    - [13.00, 100.70]
    - [13.15, 100.82]
  output_scale_m: 10
  effective_resolution_m: 20
  level_colors:
    elevated: "#34C759"
    watch: "#FF9F0A"
    warning: "#FF3B30"
```

Keep this section separate from the legacy per-site `escalation_rules`; the regional overlay now uses Sentinel-2 trend and raster SST, while the old point pipeline remains unchanged.

- [ ] **Step 4: Update the configured wrapper and bridges**

Implement:

```python
def build_configured_ndci_watch_overlay(
    target_date: str,
    monitoring_sites: list[dict],
    config: dict | None = None,
) -> dict:
    values = config or load_watch_overlay_config()
    return build_ndci_watch_overlay(
        target_date,
        monitoring_sites=monitoring_sites,
        **{key: values[key] for key in (
            "threshold_z", "warning_threshold_z", "latest_window_days",
            "baseline_years", "seasonal_window_days", "min_baseline_observations",
            "trend_window_days", "min_trend_observations", "sst_search_window_days",
            "sst_climatology_window_days", "sst_resolution_m", "water_occurrence_pct",
            "gulf_seed_points", "output_scale_m", "effective_resolution_m", "level_colors",
        )},
    )
```

Keep the namespaced importlib bridges intact. Update module docstrings so they no longer claim the regional overlay has no trend interpretation. In `backend/tests/test_smoke.py`, extend the bridge test with:

```python
import inspect

assert callable(bridge.build_configured_ndci_watch_overlay)
parameters = inspect.signature(bridge.build_configured_ndci_watch_overlay).parameters
assert "target_date" in parameters
assert "monitoring_sites" in parameters
```

- [ ] **Step 5: Run detection and backend bridge tests**

```bash
cd detection
./venv/bin/python -m pytest tests/test_watch_overlay.py -q
./venv/bin/python -m pytest tests/ -q
cd ../backend
./venv/bin/python -m pytest tests/test_smoke.py -q
```

Expected: all PASS without live Earth Engine.

- [ ] **Step 6: Commit the configured bridge**

```bash
git add detection/src/config.yaml detection/src/watch_overlay.py detection/tests/test_watch_overlay.py detection/src/_data_pipeline.py backend/src/_detection.py backend/tests/test_smoke.py
git commit -m "feat(detection): configure three-tier overlay"
```

---

### Task 5: Add a compatibility-safe cache column and typed API metadata

**Files:**
- Create: `backend/src/migrations.py`
- Create: `backend/tests/test_migrations.py`
- Modify: `backend/src/db.py`
- Modify: `backend/src/db_models.py`
- Modify: `backend/src/schemas.py`
- Modify: `backend/src/routers/watch_overlay.py`
- Modify: `backend/tests/test_watch_overlay.py`

**Interfaces:**
- Consumes: Task 3 `analysis_metadata` dictionary.
- Produces: nullable `WatchOverlayCache.analysis_metadata`, typed Pydantic metadata models, and `WatchOverlayResponse.analysis_metadata` without exposing `map_id`.

- [ ] **Step 1: Write a legacy-table migration test**

Create `backend/tests/test_migrations.py`:

```python
from sqlalchemy import create_engine, inspect, text

from src.migrations import ensure_watch_overlay_analysis_metadata_column


def test_additive_watch_overlay_migration_preserves_existing_row():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE watch_overlay_cache (id INTEGER PRIMARY KEY, status VARCHAR NOT NULL, tile_url TEXT)"))
        connection.execute(text("INSERT INTO watch_overlay_cache (id, status, tile_url) VALUES (1, 'ok', 'cached')"))

    ensure_watch_overlay_analysis_metadata_column(engine)
    ensure_watch_overlay_analysis_metadata_column(engine)

    assert "analysis_metadata" in {column["name"] for column in inspect(engine).get_columns("watch_overlay_cache")}
    with engine.connect() as connection:
        row = connection.execute(text("SELECT status, tile_url, analysis_metadata FROM watch_overlay_cache WHERE id=1")).one()
    assert tuple(row) == ("ok", "cached", None)
```

- [ ] **Step 2: Run the migration test and verify RED**

```bash
cd backend
./venv/bin/python -m pytest tests/test_migrations.py -q
```

Expected: FAIL because `src.migrations` does not exist.

- [ ] **Step 3: Implement the idempotent additive migration**

Create `backend/src/migrations.py`:

```python
from sqlalchemy import JSON, inspect, text


def ensure_watch_overlay_analysis_metadata_column(bind) -> None:
    inspector = inspect(bind)
    if "watch_overlay_cache" not in inspector.get_table_names():
        return
    if "analysis_metadata" in {column["name"] for column in inspector.get_columns("watch_overlay_cache")}:
        return
    json_type = JSON().compile(dialect=bind.dialect)
    with bind.begin() as connection:
        connection.execute(text(f"ALTER TABLE watch_overlay_cache ADD COLUMN analysis_metadata {json_type}"))
```

The table and column names are fixed source constants, not user input. In `init_db()`, call `Base.metadata.create_all(bind=engine)` first and then `ensure_watch_overlay_analysis_metadata_column(engine)` so both new and old databases work.

- [ ] **Step 4: Add the ORM column and typed nested schemas**

Add this ORM field:

```python
analysis_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

In `backend/src/schemas.py`, define strict nested models for:

```python
class WatchLevelDefinition(BaseModel):
    code: Literal["elevated", "watch", "warning"]
    class_code: Literal[1, 2, 3]
    label_th: str
    color: str
    min_z: float
    requires_rising_trend: bool
    requires_sst_above_normal: bool


class WatchSiteAlert(BaseModel):
    site_id: str
    name: str
    lat: float
    lng: float
    level: Literal["elevated", "watch", "warning"]
    label_th: str
    color: str
    ndci_z: float
    latest_scene_date: str | None = None
    trend_slope_per_day: float | None = None
    trend_observations: int
    trend_rising: bool
    current_sst: float | None = None
    seasonal_sst: float | None = None
    sst_date: str | None = None
    sst_above_normal: bool


class WatchTrendMetadata(BaseModel):
    window_days: int
    min_distinct_dates: int
    slope_units: Literal["ndci_per_day"]
    rising_rule: Literal["slope_per_day > 0"]


class WatchSstMetadata(BaseModel):
    collection_id: str
    search_window_days: int
    climatology_window_days: int
    resolution_m: int
    above_normal_rule: Literal["current_sst > seasonal_sst"]


class WatchMaskMetadata(BaseModel):
    water_mask: str
    water_occurrence_pct: float
    scl_water_class: Literal[6]
    qa60_cloud_bit: Literal[10]
    qa60_cirrus_bit: Literal[11]


class WatchResolutionMetadata(BaseModel):
    output_grid_m: int
    ndci_m: int
    trend_m: int
    sst_m: int
```

Then compose:

```python
class WatchAnalysisMetadata(BaseModel):
    version: Literal[2]
    levels: list[WatchLevelDefinition]
    trend: WatchTrendMetadata
    sst: WatchSstMetadata
    masks: WatchMaskMetadata
    resolutions: WatchResolutionMetadata
    newest_sentinel_scene_date: str | None = None
    newest_sst_scene_date: str | None = None
    mosaic_caveat: str
    site_alerts: list[WatchSiteAlert]
```

Add `analysis_metadata: WatchAnalysisMetadata | None = None` to `WatchOverlayResponse`.

- [ ] **Step 5: Add API contract tests for typed alerts and legacy null metadata**

Extend `backend/tests/test_watch_overlay.py` so a cached version-2 row returns metadata and omits normal alerts:

```python
body = client.get("/watch-overlay").json()
assert body["analysis_metadata"]["version"] == 2
assert [item["level"] for item in body["analysis_metadata"]["site_alerts"]] == ["elevated", "warning"]
assert all(item["level"] != "normal" for item in body["analysis_metadata"]["site_alerts"])
assert "map_id" not in body
```

Add a legacy-row assertion that `analysis_metadata` is `None`. Monkeypatch the GEE bridge to raise if called, preserving the existing endpoint cache-only proof.

- [ ] **Step 6: Return the stored metadata from the router**

Map `analysis_metadata=row.analysis_metadata` into `WatchOverlayResponse`. Do not import detection, scheduler, or Earth Engine in the router.

- [ ] **Step 7: Run migration and endpoint tests**

```bash
cd backend
./venv/bin/python -m pytest tests/test_migrations.py tests/test_watch_overlay.py tests/test_disclaimer.py -q
```

Expected: all PASS.

- [ ] **Step 8: Commit the compatibility layer**

```bash
git add backend/src/migrations.py backend/tests/test_migrations.py backend/src/db.py backend/src/db_models.py backend/src/schemas.py backend/src/routers/watch_overlay.py backend/tests/test_watch_overlay.py
git commit -m "feat(backend): expose typed overlay analysis"
```

---

### Task 6: Cache complete analysis and pass the six monitored sites

**Files:**
- Modify: `backend/src/scheduler.py`
- Modify: `backend/tests/test_watch_overlay.py`
- Modify: `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: Task 4 configured builder and Task 5 nullable `analysis_metadata` cache column.
- Produces: scheduler calls `build_configured_ndci_watch_overlay(target_date, monitoring_sites)` once per cycle and atomically preserves the full last-good tile/metadata/site-alert snapshot.

- [ ] **Step 1: Expand the successful fixture and write failing scheduler assertions**

Add a complete version-2 `analysis_metadata` object to `successful_overlay_payload()` in `backend/tests/test_watch_overlay.py`. Then assert:

```python
assert row.analysis_metadata == successful_overlay_payload("2026-08-27")["analysis_metadata"]
assert all(item["level"] != "normal" for item in row.analysis_metadata["site_alerts"])
```

Update `backend/tests/test_scheduler.py` to capture the builder call:

```python
overlay_calls = []
monkeypatch.setattr(
    scheduler_module.bridge,
    "build_configured_ndci_watch_overlay",
    lambda target_date, monitoring_sites: overlay_calls.append((target_date, monitoring_sites)) or successful_overlay_payload(target_date),
)
refresh_grid()
assert len(overlay_calls) == 1
assert [site["site_id"] for site in overlay_calls[0][1]] == [item["site_id"] for item in MONITORED_GRID]
```

- [ ] **Step 2: Run scheduler tests and verify RED**

```bash
cd backend
./venv/bin/python -m pytest tests/test_watch_overlay.py tests/test_scheduler.py -q
```

Expected: FAIL because the scheduler does not pass site data or persist analysis metadata.

- [ ] **Step 3: Normalize monitored-site inputs at the scheduler boundary**

Add:

```python
def _overlay_site_payloads(sites) -> list[dict]:
    return [
        {"site_id": site.site_id, "name": site.name, "lat": site.lat, "lng": site.lng}
        for site in sites
    ]
```

Change the refresh signature to `refresh_watch_overlay(db, target_date, sites=None)`. If `sites` is `None`, query `MonitoredSite` ordered by `site_id`; otherwise preserve the sequence supplied by `refresh_grid`. Pass `_overlay_site_payloads(sites)` to the configured builder. In `refresh_grid`, call `refresh_watch_overlay(db, target_date, sites)` after all six per-site refreshes.

- [ ] **Step 4: Persist and preserve analysis metadata atomically**

Add `analysis_metadata=overlay["analysis_metadata"]` to success fields. On a failed refresh with a last-good tile, only `stale` and `error` may change; the existing exhaustive column snapshot test must prove `analysis_metadata.site_alerts` also survives unchanged.

For first-run `no_imagery` or errors, set `analysis_metadata=None`; do not synthesize pins or claim a three-tier tile exists. Keep the old top-level config metadata where available.

- [ ] **Step 5: Update all mocks to the two-argument callable**

Every monkeypatched `build_configured_ndci_watch_overlay` in backend tests must accept `target_date, monitoring_sites`. Keep failure-path exceptions and commit-failure regression coverage intact.

- [ ] **Step 6: Run focused and deterministic backend suites**

```bash
cd backend
./venv/bin/python -m pytest tests/test_watch_overlay.py tests/test_scheduler.py tests/test_migrations.py -q
./venv/bin/python -m pytest tests/ -q -k "not test_live_satellite_image"
```

Expected: all deterministic tests PASS. The two explicitly live tests are excluded only because they require external Earth Engine auth/network.

- [ ] **Step 7: Commit scheduler integration**

```bash
git add backend/src/scheduler.py backend/tests/test_watch_overlay.py backend/tests/test_scheduler.py
git commit -m "feat(backend): cache overlay alerts"
```

---

### Task 7: Add frontend filtering for non-normal overlay pins

**Files:**
- Modify: `frontend/src/utils/watchOverlay.js`
- Modify: `frontend/tests/watchOverlay.test.js`

**Interfaces:**
- Consumes: Task 5 `analysis_metadata.levels` and `analysis_metadata.site_alerts`.
- Produces: `getVisibleSiteAlerts(mode, overlay)`, `getOverlayLegendLevels(mode, overlay)`, and existing tile/message helpers.

- [ ] **Step 1: Write failing utility tests**

Extend `frontend/tests/watchOverlay.test.js`:

```javascript
import {
  getOverlayLegendLevels,
  getVisibleSiteAlerts,
} from '../src/utils/watchOverlay.js'

const overlay = {
  status: 'ok',
  tile_url: 'https://tiles.example/{z}/{x}/{y}',
  analysis_metadata: {
    version: 2,
    levels: [
      { code: 'elevated', class_code: 1, label_th: 'เริ่มผิดปกติ', color: '#34C759' },
      { code: 'watch', class_code: 2, label_th: 'เฝ้าระวัง', color: '#FF9F0A' },
      { code: 'warning', class_code: 3, label_th: 'เตือนภัย', color: '#FF3B30' },
    ],
    site_alerts: [
      { site_id: 'normal', level: 'normal', lat: 13, lng: 100 },
      { site_id: 'elevated', level: 'elevated', lat: 13.1, lng: 100.1, color: '#34C759' },
      { site_id: 'warning', level: 'warning', lat: 13.2, lng: 100.2, color: '#FF3B30' },
      { site_id: 'bad-coordinates', level: 'watch', lat: null, lng: 100.3, color: '#FF9F0A' },
    ],
  },
}

test('shows only valid non-normal pins in True Color and scan modes', () => {
  assert.deepEqual(getVisibleSiteAlerts('true_color', overlay).map((item) => item.site_id), ['elevated', 'warning'])
  assert.deepEqual(getVisibleSiteAlerts('watch', overlay).map((item) => item.site_id), ['elevated', 'warning'])
  assert.deepEqual(getVisibleSiteAlerts('ndci', overlay), [])
})

test('does not invent pins or a three-tier legend for legacy metadata', () => {
  assert.deepEqual(getVisibleSiteAlerts('watch', { ...overlay, analysis_metadata: null }), [])
  assert.deepEqual(getOverlayLegendLevels('watch', { ...overlay, analysis_metadata: null }), [])
})

test('legend contains only the three approved abnormal levels', () => {
  assert.deepEqual(getOverlayLegendLevels('true_color', overlay).map((item) => item.code), ['elevated', 'watch', 'warning'])
})
```

- [ ] **Step 2: Run frontend tests and verify RED**

```bash
cd frontend
npm test
```

Expected: FAIL because the new helpers are not exported.

- [ ] **Step 3: Implement defensive whitelist filtering**

Add to `watchOverlay.js`:

```javascript
const ALERT_LEVELS = new Set(['elevated', 'watch', 'warning'])
const ALERT_MODES = new Set(['true_color', 'watch'])

export function getVisibleSiteAlerts(mode, overlay) {
  if (!ALERT_MODES.has(mode) || !overlay?.tile_url) return []
  const alerts = overlay?.analysis_metadata?.site_alerts
  if (!Array.isArray(alerts)) return []
  return alerts.filter((item) => (
    ALERT_LEVELS.has(item?.level)
    && Number.isFinite(item?.lat)
    && Number.isFinite(item?.lng)
  ))
}

export function getOverlayLegendLevels(mode, overlay) {
  if (!ALERT_MODES.has(mode)) return []
  const levels = overlay?.analysis_metadata?.levels
  if (!Array.isArray(levels)) return []
  return levels.filter((item) => ALERT_LEVELS.has(item?.code))
}
```

Keep `canRenderWatchTiles` limited to scan mode and preserve stale/error wording.

- [ ] **Step 4: Run frontend tests, lint, and build**

```bash
cd frontend
npm test
npm run lint
npm run build
```

Expected: all PASS.

- [ ] **Step 5: Commit frontend state filtering**

```bash
git add frontend/src/utils/watchOverlay.js frontend/tests/watchOverlay.test.js
git commit -m "feat(frontend): filter overlay alert pins"
```

---

### Task 8: Render the three-tier tile, compact legend, and conditional pins

**Files:**
- Create: `frontend/src/components/WatchSitePopup.jsx`
- Modify: `frontend/src/components/RiskMap.jsx`
- Modify: `frontend/src/components/RiskLegend.jsx`
- Modify: `frontend/src/components/MapControls.jsx`
- Modify: `frontend/src/pages/OverviewPage.jsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: Task 7 `getVisibleSiteAlerts`/`getOverlayLegendLevels` and Task 5 typed alert fields.
- Produces: alert-only Leaflet markers in True Color and scan modes, a three-tier tile/legend in scan mode, and no normal/no-data markers.

- [ ] **Step 1: Change the scan-tab copy and add the popup component**

Rename only the third tab to `สัญญาณ NDCI (3 ระดับ)`. Keep `True Color (RGB)` first and selected on reload.

Create `WatchSitePopup.jsx` with null-safe rows:

```jsx
function valueOrDash(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : '—'
}

export default function WatchSitePopup({ alert }) {
  return (
    <div className="watch-site-popup">
      <strong>{alert.name}</strong>
      <span className="watch-site-level" style={{ color: alert.color }}>{alert.label_th}</span>
      <dl>
        <dt>NDCI z-score</dt><dd>{valueOrDash(alert.ndci_z)}</dd>
        <dt>เทรนด์ 14 วัน</dt><dd>{alert.trend_rising ? 'เพิ่มขึ้น' : 'ข้อมูลไม่พอ/ไม่เพิ่มขึ้น'}</dd>
        <dt>ความชันต่อวัน</dt><dd>{valueOrDash(alert.trend_slope_per_day, 4)}</dd>
        <dt>วันที่ใช้คำนวณเทรนด์</dt><dd>{alert.trend_observations}</dd>
        <dt>วันที่ภาพ</dt><dd>{alert.latest_scene_date || '—'}</dd>
        <dt>SST</dt><dd>{Number.isFinite(alert.current_sst) ? `${alert.current_sst.toFixed(2)} °C` : '—'}</dd>
        <dt>SST ตามฤดูกาล</dt><dd>{Number.isFinite(alert.seasonal_sst) ? `${alert.seasonal_sst.toFixed(2)} °C` : '—'}</dd>
        <dt>สถานะ SST</dt><dd>{alert.sst_above_normal ? 'สูงกว่าปกติ' : 'ไม่สูงกว่าปกติ/ข้อมูลไม่พอ'}</dd>
        <dt>วันที่ SST</dt><dd>{alert.sst_date || '—'}</dd>
      </dl>
      <small>สัญญาณเชิงกฎ ไม่ใช่การยืนยันแพลงก์ตอนบลูมหรือชนิดสิ่งมีชีวิต</small>
    </div>
  )
}
```

- [ ] **Step 2: Render only the filtered alert markers**

In `RiskMap.jsx`, import `CircleMarker` and `Popup`, `getVisibleSiteAlerts`, and `WatchSitePopup`. Compute:

```jsx
const siteAlerts = getVisibleSiteAlerts(mode, watchOverlay)
```

After the tile layers, render:

```jsx
{siteAlerts.map((alert) => (
  <CircleMarker
    key={alert.site_id}
    center={[alert.lat, alert.lng]}
    radius={9}
    pathOptions={{ color: '#FFFFFF', weight: 2, fillColor: alert.color, fillOpacity: 0.92 }}
  >
    <Popup><WatchSitePopup alert={alert} /></Popup>
  </CircleMarker>
))}
```

Do not restore `FitToFeatures`; `ScanBoundsView`, `MAP_BOUNDS`, `getBoundsZoom(bounds, false)`, and `maxBounds` remain authoritative. Do not accept `/risk-map` features as a `RiskMap` prop.

- [ ] **Step 3: Replace the orange-only legend with metadata-driven rows**

Use `getOverlayLegendLevels(mode, watchOverlay)`. For True Color and scan modes, return `null` when no version-2 level metadata exists. Otherwise render exactly the three metadata rows and one transparency explanation. Do not render a normal row or dotted normal/no-data marker.

Keep the illustrative NDCI gradient only in `mode === 'ndci'`. The compact alert legend must state output 10 m, NDCI/trend 20 m, and SST approximately 4.6 km from `analysis_metadata.resolutions`.

- [ ] **Step 4: Update state copy without changing request behavior**

In `OverviewPage.jsx`, keep independent `getWatchOverlay` fetching and map rendering regardless of `/risk-map`. Update scan-mode ready copy to `สัญญาณ NDCI 3 ระดับพร้อมใช้งาน`. Show Sentinel and SST newest dates when present, retain the mosaic-date caveat, and keep retry only for unavailable tiles. Do not add a right-side panel.

- [ ] **Step 5: Add compact marker, popup, and legend styling**

In `global.css`, add scoped `.watch-site-popup`, `.watch-site-level`, and definition-list styles. Add swatches by metadata inline color or classes for elevated/watch/warning. Keep the legend within the smaller approved footprint, preserve touch targets, and avoid reintroducing removed legacy marker classes.

- [ ] **Step 6: Run frontend verification**

```bash
cd frontend
npm test
npm run lint
npm run build
```

Expected: all PASS. Inspect the production build output for no unresolved import or JSX errors.

- [ ] **Step 7: Perform a local UI smoke check when a browser is connected**

Start the backend and frontend, reload Overview, and verify:

1. True Color is selected and the full scan bounds are visible.
2. No gray/normal pins appear.
3. Only green/orange/red cached site alerts appear in True Color.
4. Scan mode adds the three-color raster without changing bounds.
5. Illustrative NDCI hides the site-alert pins.
6. The compact legend has no normal row.
7. No right-side panel appears.

If no browser surface is connected, record this as an unperformed visual check rather than claiming success from source inspection.

- [ ] **Step 8: Commit the map presentation**

```bash
git add frontend/src/components/WatchSitePopup.jsx frontend/src/components/RiskMap.jsx frontend/src/components/RiskLegend.jsx frontend/src/components/MapControls.jsx frontend/src/pages/OverviewPage.jsx frontend/src/styles/global.css
git commit -m "feat(frontend): render three-tier overlay alerts"
```

---

### Task 9: Update truth-boundary docs and run final verification

**Files:**
- Modify: `LIMITATIONS.md`
- Modify: `data-pipeline/README.md`
- Modify: `backend/README.md`
- Modify: `docs/superpowers/specs/2026-08-27-upper-gulf-three-tier-sentinel-overlay-design.md` only if implementation names differ from the approved interfaces; do not weaken the approved rules.

**Interfaces:**
- Consumes: completed Tasks 1-8.
- Produces: accurate operator documentation and evidence from all deterministic gates, plus an optional credentialed Earth Engine smoke result.

- [ ] **Step 1: Replace orange-only documentation with the three-tier contract**

Document all of these facts in the three listed operator docs:

- Sentinel-2 B2-B6 plus SCL/QA60 masking and SCL water class;
- Gulf-connected historical water remains a heuristic, not salinity;
- 30-day current NDCI, five prior seasonal years, and minimum five baseline observations;
- 14-day per-pixel Sentinel-2 NDCI trend with at least two distinct dates;
- MODIS-Aqua SST nearest within five days and prior-year seasonal mean;
- exact three rules/colors and highest-rule-wins behavior;
- normal and unusable pixels are both transparent and are not equivalent claims;
- only non-normal site samples create pins;
- 10 m output, 20 m NDCI/trend, and approximately 4.6 km SST;
- cached scheduler/API flow and last-good stale fallback;
- uncalibrated indicative rules, not bloom confirmation or a validated forecast.

- [ ] **Step 2: Run documentation consistency checks**

```bash
rg -n "orange-only|only orange|no 14-day trend|z >= 1.5\).*orange" LIMITATIONS.md data-pipeline/README.md backend/README.md
rg -n "เริ่มผิดปกติ|เฝ้าระวัง|เตือนภัย|QA60|SCL|4.6 km|site_alerts" LIMITATIONS.md data-pipeline/README.md backend/README.md
git diff --check
```

Expected: the first grep returns no stale product claim; the second finds the new contract in the appropriate docs; diff check is clean.

- [ ] **Step 3: Run every deterministic suite**

```bash
cd data-pipeline
./venv/bin/python -m pytest tests/ -q
cd ../detection
./venv/bin/python -m pytest tests/ -q
cd ../backend
./venv/bin/python -m pytest tests/ -q -k "not test_live_satellite_image"
cd ../frontend
npm test
npm run lint
npm run build
cd ..
git diff --check
```

Expected: all deterministic Python suites, frontend tests, lint, build, and diff check PASS.

- [ ] **Step 4: Run the optional credentialed Earth Engine smoke check**

When Earth Engine credentials and network are available:

```bash
cd detection
./venv/bin/python -c "from src.watch_overlay import build_configured_ndci_watch_overlay; from pathlib import Path; import importlib.util; p=Path('../backend/src/grid.py').resolve(); s=importlib.util.spec_from_file_location('backend_grid', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); r=build_configured_ndci_watch_overlay('2026-08-27', m.MONITORED_GRID); print({k: r[k] for k in ('status','target_date','newest_scene_date','threshold_z','output_grid_m','effective_resolution_m')}); print(r['analysis_metadata']); print(r['tile_url'])"
```

Verify the tile URL exists, metadata version is 2, levels are exactly `elevated/watch/warning`, `site_alerts` is a subset of the six configured IDs, and no alert has level `normal`. If credentials/network are unavailable, record the skipped or failed external check separately; do not treat it as a deterministic-suite failure.

- [ ] **Step 5: Commit documentation**

```bash
git add LIMITATIONS.md data-pipeline/README.md backend/README.md docs/superpowers/specs/2026-08-27-upper-gulf-three-tier-sentinel-overlay-design.md
git commit -m "docs: explain three-tier overlay limits"
```

- [ ] **Step 6: Request a whole-branch review**

Generate a diff from the feature base through `HEAD` and ask an independent reviewer to check scientific truth boundaries, class precedence, SCL/QA60 wiring, date de-duplication, SST resolution disclosure, cache migration preservation, stale snapshot completeness, cache-only API behavior, normal-pin exclusion, map bounds preservation, and regression-test coverage. Address every Critical or Important finding with a focused test before declaring completion.
