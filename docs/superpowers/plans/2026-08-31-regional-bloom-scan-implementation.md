# Regional Bloom Scan Implementation Plan

> Correction, 2026-09-06: this historical plan's anomaly-scoring, tiering, persistence and test examples are superseded. The former spectral-index/MODIS-concentration calculation was dimensionally invalid. `detect()` now returns indices/status/actual_date only; `spatial_anomaly_z` is a null placeholder, all tiers are null and no anomaly clusters are produced. Numeric anomaly fixtures and threshold examples below are withdrawn implementation instructions, not valid statistics or evidence. Read `LIMITATIONS.md` §1 and the current source before using this plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full-polygon regional bloom scan (500-point grid over the upper Gulf study-area polygon, event-driven poll+cooldown trigger, grid-adjacency clustering, new `/regional-scan` endpoint) exactly as approved in the design spec — no scope beyond what that spec locked in.

**Architecture:** A new `backend/src/regional_scan/` package (grid generation, adjacency clustering, scan orchestration, poll/trigger) reuses `detect()` (`detection/src/prediction.py`) unchanged for every grid point, persists a latest-run snapshot in three new tables, and serves it through a cache-only `GET /regional-scan` endpoint — mirrors the existing `/risk-map` / scheduler / `DetectionCache` pattern. A new `data-pipeline/src/scene_poll.py` function feeds the trigger's cheap freshness check through the existing three-project import-bridge chain (`data-pipeline` → `detection` → `backend`). A new `backend/src/_study_area.py` bridge (a third instance of the same `importlib.util.spec_from_file_location` pattern `detection/src/_data_pipeline.py` already established) gives grid generation a direct, GEE-free path to the study-area polygon check. Frontend adds one new, independently-scoped map layer component.

**Tech Stack:** FastAPI, SQLAlchemy (existing `backend/src` conventions), APScheduler, Google Earth Engine (`ee`) via the existing `data-pipeline/src` bridge chain, React + react-leaflet (frontend).

**Spec:** `docs/superpowers/specs/2026-08-31-regional-scan-design.md` (this plan implements it section-for-section; §12 "Deferred — per-tile partial scanning" is explicitly OUT of scope for this plan).

## Global Constraints

- Reuses `detect()` (`detection/src/prediction.py`) unchanged for every point — no detection/prediction logic is duplicated or reimplemented (spec §2).
- Threshold tiers use the exact `elevated_z`/`warning_z` cutoffs already in `detection/src/config.yaml` — no new numbers (spec §3).
- Clustering is grid-adjacency connected-components (union-find, 8-connectivity) — no DBSCAN, no new dependency, no tunable parameter (spec §4).
- No point is ever fabricated, interpolated, or filled in from a neighbor — a no-data point is stored with its real status, never dropped (spec §0).
- `GET /regional-scan` never calls GEE live — pure cache read, same convention as `/risk-map`/`/summary` (spec §7).
- The regional-scan scheduler job does **not** fire immediately at process startup, unlike `refresh_grid` (spec §8).
- Every response carries `disclaimer` (existing `DisclaimerMixin`) plus a distinct `caveat` labeling this a detection scan, separate from the unvalidated Ang Sila spatial-trend test (spec §7).
- New env-overridable constants follow the existing `SCHEDULER_INTERVAL_MINUTES` convention in `backend/src/config.py` (spec §8): `REGIONAL_SCAN_GRID_SPACING_KM` (default `5`), `REGIONAL_SCAN_POLL_INTERVAL_HOURS` (default `3`), `REGIONAL_SCAN_COOLDOWN_HOURS` (default `20`).
- Grid generation and adjacency clustering are pure functions, unit-testable without GEE (spec §11).

---

## File Structure

New files:
- `backend/src/_study_area.py` — direct bridge into `data-pipeline/src` for the boundary check (third instance of the established `importlib` pattern).
- `backend/src/regional_scan/__init__.py` — empty, marks the package.
- `backend/src/regional_scan/grid.py` — `generate_scan_grid()`.
- `backend/src/regional_scan/clustering.py` — `cluster_points()`.
- `backend/src/regional_scan/scan.py` — `run_scan()`, `_tier()`.
- `backend/src/regional_scan/trigger.py` — `should_trigger_scan()`, `poll_and_maybe_scan()`.
- `backend/src/routers/regional_scan.py` — `GET /regional-scan`.
- `backend/scripts/run_regional_scan.py` — manual CLI trigger.
- `data-pipeline/src/scene_poll.py` — `get_newest_scene_timestamp()`.
- `frontend/src/components/RegionalScanLayer.jsx` — the new map layer.
- Tests: `backend/tests/test_regional_scan_grid.py`, `test_regional_scan_clustering.py`, `test_regional_scan_scan.py`, `test_regional_scan_trigger.py`, `test_regional_scan_endpoint.py`; `data-pipeline/tests/test_scene_poll.py` (import-only, no live GEE call).

Modified files:
- `backend/src/db_models.py` — add `RegionalScanRun`, `RegionalScanPoint`, `RegionalScanCluster`.
- `backend/src/config.py` — add the three new constants + `REGIONAL_SCAN_POLL_LOOKBACK_DAYS`.
- `backend/src/_detection.py` — re-export `get_newest_scene_timestamp`.
- `backend/src/scheduler.py` — register the new poll job.
- `backend/src/schemas.py` — add `RegionalScanResponse` and friends.
- `backend/src/main.py` — include the new router, add `/regional-scan` to the root route's endpoint list.
- `data-pipeline/src/__init__.py` — re-export `get_newest_scene_timestamp`.
- `detection/src/_data_pipeline.py` — re-export `get_newest_scene_timestamp`.
- `frontend/src/api/client.js` — add `getRegionalScan()`.
- `frontend/src/pages/OverviewPage.jsx` — wire in the new layer behind a toggle.

---

### Task 1: Data model + config constants

**Files:**
- Modify: `backend/src/db_models.py`
- Modify: `backend/src/config.py`
- Test: `backend/tests/test_config.py` (extend existing file)

**Interfaces:**
- Produces: `RegionalScanRun` (fields: `id`, `started_at`, `completed_at`, `status`, `grid_spacing_km`, `date_used`, `newest_scene_date`, `total_points`, `count_ok`, `count_no_imagery`, `count_no_water_pixels`, `count_no_climatology`, `count_error`), `RegionalScanPoint` (fields: `point_id` PK, `lat`, `lng`, `row_idx`, `col_idx`, `status`, `index_values`, `spatial_anomaly_z`, `threshold_tier`, `run_id`), `RegionalScanCluster` (fields: `id`, `run_id`, `centroid_lat`, `centroid_lng`, `cell_count`, `mean_spatial_anomaly_z`, `max_spatial_anomaly_z`, `threshold_tier`, `member_point_ids`) — every later task relies on these exact field names.
- Produces: `config.REGIONAL_SCAN_GRID_SPACING_KM: float`, `config.REGIONAL_SCAN_POLL_INTERVAL_HOURS: int`, `config.REGIONAL_SCAN_COOLDOWN_HOURS: int`, `config.REGIONAL_SCAN_POLL_LOOKBACK_DAYS: int`.

- [ ] **Step 1: Add the three ORM models to `backend/src/db_models.py`**

Append after the existing cache models:

```python
class RegionalScanRun(Base):
    """One row per full-polygon regional-scan run (history kept -- small
    rows, cheap). See docs/superpowers/specs/2026-08-31-regional-scan-design.md
    §6. `newest_scene_date` is the max Sentinel-2 scene timestamp the
    triggering poll considered -- read back by the next poll as its
    comparison baseline (spec §5)."""

    __tablename__ = "regional_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String)  # running|ok|partial_error|error
    grid_spacing_km: Mapped[float] = mapped_column(Float)
    date_used: Mapped[str] = mapped_column(String)
    newest_scene_date: Mapped[str | None] = mapped_column(String, nullable=True)
    total_points: Mapped[int] = mapped_column(Integer)
    count_ok: Mapped[int] = mapped_column(Integer, default=0)
    count_no_imagery: Mapped[int] = mapped_column(Integer, default=0)
    count_no_water_pixels: Mapped[int] = mapped_column(Integer, default=0)
    count_no_climatology: Mapped[int] = mapped_column(Integer, default=0)
    count_error: Mapped[int] = mapped_column(Integer, default=0)


class RegionalScanPoint(Base):
    """Latest-run snapshot, upserted by `point_id` (not appended) --
    same overwrite-latest convention as DetectionCache. No-data points
    are stored with their real status, never omitted (spec §0/§6).
    `point_id` is f"{row_idx}_{col_idx}" -- stable across runs at the
    same grid spacing (backend/src/regional_scan/grid.py)."""

    __tablename__ = "regional_scan_points"

    point_id: Mapped[str] = mapped_column(String, primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    row_idx: Mapped[int] = mapped_column(Integer)
    col_idx: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)  # ok|no_imagery|no_water_pixels|no_climatology|error
    index_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    spatial_anomaly_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold_tier: Mapped[str | None] = mapped_column(String, nullable=True)  # elevated|warning|null
    run_id: Mapped[int] = mapped_column(ForeignKey("regional_scan_runs.id"))


class RegionalScanCluster(Base):
    """Latest-run snapshot -- deleted and reinserted whole each run
    (unlike RegionalScanPoint's stable point_id, cluster membership can
    change entirely between runs). Computed only over real, status='ok'
    member cells by construction -- only already-flagged 'ok' points are
    ever clustered (spec §4)."""

    __tablename__ = "regional_scan_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("regional_scan_runs.id"))
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lng: Mapped[float] = mapped_column(Float)
    cell_count: Mapped[int] = mapped_column(Integer)
    mean_spatial_anomaly_z: Mapped[float] = mapped_column(Float)
    max_spatial_anomaly_z: Mapped[float] = mapped_column(Float)
    threshold_tier: Mapped[str] = mapped_column(String)  # elevated|warning
    member_point_ids: Mapped[list] = mapped_column(JSON)
```

- [ ] **Step 2: Add the config constants to `backend/src/config.py`**

Append at the end of the file:

```python
# Regional bloom scan (docs/superpowers/specs/2026-08-31-regional-scan-design.md
# §8). Same env-override convention as SCHEDULER_INTERVAL_MINUTES above.
REGIONAL_SCAN_GRID_SPACING_KM: float = float(os.environ.get("REGIONAL_SCAN_GRID_SPACING_KM", "5"))
REGIONAL_SCAN_POLL_INTERVAL_HOURS: int = int(os.environ.get("REGIONAL_SCAN_POLL_INTERVAL_HOURS", "3"))
REGIONAL_SCAN_COOLDOWN_HOURS: int = int(os.environ.get("REGIONAL_SCAN_COOLDOWN_HOURS", "20"))
# Lookback window for the poll's own Sentinel-2 metadata query (spec §5) --
# bounds the filterDate() query cost; does not affect the cooldown/trigger
# decision itself (that compares timestamps, not window length).
REGIONAL_SCAN_POLL_LOOKBACK_DAYS: int = int(os.environ.get("REGIONAL_SCAN_POLL_LOOKBACK_DAYS", "10"))
```

- [ ] **Step 3: Write a test proving the new tables are created and the constants are typed correctly**

Append to `backend/tests/test_config.py`:

```python
def test_regional_scan_config_defaults():
    from src import config

    assert config.REGIONAL_SCAN_GRID_SPACING_KM == 5.0
    assert config.REGIONAL_SCAN_POLL_INTERVAL_HOURS == 3
    assert config.REGIONAL_SCAN_COOLDOWN_HOURS == 20
    assert config.REGIONAL_SCAN_POLL_LOOKBACK_DAYS == 10


def test_regional_scan_tables_created(client):
    from sqlalchemy import inspect

    from src.db import engine

    tables = inspect(engine).get_table_names()
    assert "regional_scan_runs" in tables
    assert "regional_scan_points" in tables
    assert "regional_scan_clusters" in tables
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (both new tests; `client` fixture's `init_db()` call already creates every table registered on `Base.metadata`, which importing `db_models` guarantees).

- [ ] **Step 5: Commit**

```bash
git add backend/src/db_models.py backend/src/config.py backend/tests/test_config.py
git commit -m "feat(backend): add regional-scan data model and config constants"
```

---

### Task 2: `backend/src/_study_area.py` bridge + grid generation

**Files:**
- Create: `backend/src/_study_area.py`
- Create: `backend/src/regional_scan/__init__.py`
- Create: `backend/src/regional_scan/grid.py`
- Test: `backend/tests/test_regional_scan_grid.py`

**Interfaces:**
- Produces: `_study_area.STUDY_AREA_POLYGON_LATLNG: tuple`, `_study_area.check_point_in_study_area(lat, lng) -> dict`.
- Produces: `grid.generate_scan_grid(spacing_km: float) -> list[dict]`, each dict `{'lat': float, 'lng': float, 'row_idx': int, 'col_idx': int, 'point_id': str}`.
- Consumes: nothing from other tasks (this is the first pure-logic building block).

- [ ] **Step 1: Create `backend/src/regional_scan/__init__.py`**

Empty file (marks the package, same as every other `__init__.py` in this repo).

- [ ] **Step 2: Write the failing test for `_study_area.py`**

Create `backend/tests/test_regional_scan_grid.py`:

```python
"""Unit tests for regional-scan grid generation -- pure, GEE-free (spec
§1/§11). No live Earth Engine session required or contacted."""

from __future__ import annotations


def test_study_area_bridge_reexports_polygon_and_check():
    from src import _study_area

    assert len(_study_area.STUDY_AREA_POLYGON_LATLNG) == 4
    result = _study_area.check_point_in_study_area(13.45, 100.65)
    assert result == {"in_study_area": True, "warning": None}


def test_generate_scan_grid_returns_only_in_polygon_points():
    from src.regional_scan.grid import generate_scan_grid
    from src._study_area import check_point_in_study_area

    points = generate_scan_grid(5.0)
    assert len(points) > 0
    for p in points:
        assert check_point_in_study_area(p["lat"], p["lng"])["in_study_area"] is True


def test_generate_scan_grid_point_count_is_plausible_at_5km():
    """Spec §1 measured 500 in-polygon points at 5km spacing over the
    real ~120.6km x 123.2km bounding box. Exact count depends on grid
    origin/rounding choices, so this asserts a plausible range rather
    than the literal 500 -- a brittle exact match would break on any
    reasonable, still-correct implementation choice."""
    from src.regional_scan.grid import generate_scan_grid

    points = generate_scan_grid(5.0)
    assert 350 <= len(points) <= 650


def test_generate_scan_grid_point_ids_are_unique_and_row_col_derived():
    from src.regional_scan.grid import generate_scan_grid

    points = generate_scan_grid(5.0)
    ids = [p["point_id"] for p in points]
    assert len(ids) == len(set(ids))
    for p in points:
        assert p["point_id"] == f"{p['row_idx']}_{p['col_idx']}"


def test_generate_scan_grid_larger_spacing_yields_fewer_points():
    from src.regional_scan.grid import generate_scan_grid

    assert len(generate_scan_grid(10.0)) < len(generate_scan_grid(5.0))
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_grid.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src._study_area'` (or `src.regional_scan.grid`).

- [ ] **Step 4: Create `backend/src/_study_area.py`**

```python
"""
Cross-project bridge into `data-pipeline/src`, used only by
`backend/src/regional_scan/grid.py` to filter a generated grid down to
points inside the confirmed study-area polygon.

`backend/src/_detection.py` already reaches `check_point_in_study_area`
indirectly (through `detection/src/_data_pipeline.py`'s own bridge), but
only via that module's private, undocumented `_dp` attribute -- not part
of its public `__all__`. Rather than reach through another project's
private internals, this file is a third, direct instance of the exact
`importlib.util.spec_from_file_location` namespaced-import pattern
`detection/src/_data_pipeline.py` established for the identical
two-projects-both-named-`src` collision problem (see that module's own
docstring) -- "the same one this codebase already uses twice"
(docs/superpowers/specs/2026-08-31-regional-scan-design.md §1).

No data-pipeline logic is duplicated here -- both names below are the
exact objects from `data-pipeline/src/__init__.py`. `check_point_in_study_area`
is pure and GEE-free (data-pipeline/src/study_area.py's own docstring),
so loading this whole package a second time under a different module
name never triggers a live GEE call -- module import alone never touches
`ee`, only calling a Sentinel-2/MODIS function does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_DATA_PIPELINE_SRC = _REPO_ROOT / "data-pipeline" / "src"

_MODULE_NAME = "backend_data_pipeline_src"


def _load_data_pipeline_package():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]

    init_path = _DATA_PIPELINE_SRC / "__init__.py"
    if not init_path.exists():
        raise ImportError(
            f"data-pipeline/src not found at {_DATA_PIPELINE_SRC} -- expected a "
            "sibling `data-pipeline/` directory next to `backend/`."
        )

    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME,
        init_path,
        submodule_search_locations=[str(_DATA_PIPELINE_SRC)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_dp = _load_data_pipeline_package()

STUDY_AREA_POLYGON_LATLNG = _dp.STUDY_AREA_POLYGON_LATLNG
check_point_in_study_area = _dp.check_point_in_study_area

__all__ = ["STUDY_AREA_POLYGON_LATLNG", "check_point_in_study_area"]
```

- [ ] **Step 5: Create `backend/src/regional_scan/grid.py`**

```python
"""
Regional bloom scan grid generation (spec §1): a regular lat/lng grid at
a configurable km spacing across the upper Gulf study-area polygon's
bounding box, filtered to points actually inside the polygon
(`backend/src/_study_area.py`'s `check_point_in_study_area`).

Pure, GEE-free -- unit-testable without a live Earth Engine session
(docs/superpowers/specs/2026-08-31-regional-scan-design.md §1/§11).

Points are indexed by (row_idx, col_idx) -- their position in the
regular pre-filter grid -- so `backend/src/regional_scan/clustering.py`'s
8-connectivity adjacency check is an O(1) dict lookup, never a distance
computation.
"""

from __future__ import annotations

import math

from .. import _study_area

_KM_PER_DEGREE_LAT = 111.32  # standard WGS84 approximation, same order docs/DETECTION_PLAN.md uses


def generate_scan_grid(spacing_km: float) -> list[dict]:
    """Generate the in-polygon scan grid at `spacing_km` spacing.

    Args:
        spacing_km: grid spacing in kilometers (spec §1 default: 5).

    Returns:
        list of {'lat': float, 'lng': float, 'row_idx': int, 'col_idx': int,
                  'point_id': str}, one per in-polygon grid cell.
        `point_id` is f"{row_idx}_{col_idx}" -- a stable key across runs
        at the same spacing (used as RegionalScanPoint's primary key and
        for cluster member traceability, spec §4/§6).
    """
    lats = [lat for lat, _ in _study_area.STUDY_AREA_POLYGON_LATLNG]
    lngs = [lng for _, lng in _study_area.STUDY_AREA_POLYGON_LATLNG]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    mean_lat_rad = math.radians((min_lat + max_lat) / 2)
    lat_step_deg = spacing_km / _KM_PER_DEGREE_LAT
    lng_step_deg = spacing_km / (_KM_PER_DEGREE_LAT * math.cos(mean_lat_rad))

    n_rows = int((max_lat - min_lat) / lat_step_deg) + 1
    n_cols = int((max_lng - min_lng) / lng_step_deg) + 1

    points: list[dict] = []
    for row_idx in range(n_rows):
        lat = min_lat + row_idx * lat_step_deg
        for col_idx in range(n_cols):
            lng = min_lng + col_idx * lng_step_deg
            if _study_area.check_point_in_study_area(lat, lng)["in_study_area"]:
                points.append(
                    {
                        "lat": lat,
                        "lng": lng,
                        "row_idx": row_idx,
                        "col_idx": col_idx,
                        "point_id": f"{row_idx}_{col_idx}",
                    }
                )
    return points
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_grid.py -v`
Expected: PASS (all 5 tests). If the point-count test fails outside `[350, 650]`, do not force-fit the range to whatever the code produces — first re-check the bounding-box/step-size math against spec §1's own measured 500-point/120.6km/123.2km numbers for an actual bug before touching the test.

- [ ] **Step 7: Commit**

```bash
git add backend/src/_study_area.py backend/src/regional_scan/__init__.py backend/src/regional_scan/grid.py backend/tests/test_regional_scan_grid.py
git commit -m "feat(backend): add regional-scan grid generation"
```

---

### Task 3: Adjacency clustering

**Files:**
- Create: `backend/src/regional_scan/clustering.py`
- Test: `backend/tests/test_regional_scan_clustering.py`

**Interfaces:**
- Consumes: nothing (pure, standalone).
- Produces: `clustering.cluster_points(points: list[dict]) -> list[dict]`. Input point dict shape: `{'point_id': str, 'lat': float, 'lng': float, 'row_idx': int, 'col_idx': int, 'spatial_anomaly_z': float, 'threshold_tier': 'elevated'|'warning'}`. Output cluster dict shape: `{'centroid_lat': float, 'centroid_lng': float, 'cell_count': int, 'mean_spatial_anomaly_z': float, 'max_spatial_anomaly_z': float, 'threshold_tier': 'elevated'|'warning', 'member_point_ids': list[str]}` — Task 4 (`scan.py`) both builds the input list in this exact shape and persists the output in this exact shape.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_regional_scan_clustering.py`:

```python
"""Unit tests for grid-adjacency connected-components clustering (spec
§4) -- pure, no GEE, no DB."""

from __future__ import annotations

from src.regional_scan.clustering import cluster_points


def _point(point_id, row, col, z, tier):
    return {
        "point_id": point_id, "lat": 13.0 + row * 0.01, "lng": 100.0 + col * 0.01,
        "row_idx": row, "col_idx": col, "spatial_anomaly_z": z, "threshold_tier": tier,
    }


def test_empty_input_returns_empty_list():
    assert cluster_points([]) == []


def test_single_point_forms_its_own_cluster():
    points = [_point("0_0", 0, 0, 1.6, "elevated")]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["cell_count"] == 1
    assert c["member_point_ids"] == ["0_0"]
    assert c["centroid_lat"] == points[0]["lat"]
    assert c["mean_spatial_anomaly_z"] == 1.6
    assert c["max_spatial_anomaly_z"] == 1.6
    assert c["threshold_tier"] == "elevated"


def test_8_connected_points_merge_into_one_cluster():
    # A 2x2 block: every cell touches every other cell within radius 1.
    points = [
        _point("0_0", 0, 0, 1.6, "elevated"),
        _point("0_1", 0, 1, 1.7, "elevated"),
        _point("1_0", 1, 0, 2.1, "warning"),
        _point("1_1", 1, 1, 1.8, "elevated"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["cell_count"] == 4
    assert set(c["member_point_ids"]) == {"0_0", "0_1", "1_0", "1_1"}
    # Highest tier among members wins.
    assert c["threshold_tier"] == "warning"
    assert c["max_spatial_anomaly_z"] == 2.1
    assert c["mean_spatial_anomaly_z"] == (1.6 + 1.7 + 2.1 + 1.8) / 4


def test_diagonal_adjacency_merges():
    # (0,0) and (1,1) differ by 1 in both row and col -- 8-connectivity,
    # not 4-connectivity.
    points = [_point("0_0", 0, 0, 1.6, "elevated"), _point("1_1", 1, 1, 1.7, "elevated")]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    assert clusters[0]["cell_count"] == 2


def test_far_apart_points_form_separate_clusters():
    points = [_point("0_0", 0, 0, 1.6, "elevated"), _point("10_10", 10, 10, 1.7, "elevated")]
    clusters = cluster_points(points)
    assert len(clusters) == 2
    assert {c["cell_count"] for c in clusters} == {1}


def test_transitive_chain_merges_into_one_cluster():
    # (0,0)-(1,1)-(2,2) each pair is 8-adjacent, so the whole chain is
    # one connected component even though (0,0) and (2,2) are not
    # directly adjacent to each other.
    points = [
        _point("0_0", 0, 0, 1.6, "elevated"),
        _point("1_1", 1, 1, 1.7, "elevated"),
        _point("2_2", 2, 2, 1.8, "elevated"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    assert clusters[0]["cell_count"] == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_clustering.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.regional_scan.clustering'`.

- [ ] **Step 3: Create `backend/src/regional_scan/clustering.py`**

```python
"""
Grid-adjacency connected-components clustering for flagged regional-scan
points -- union-find over (row_idx, col_idx), 8-connectivity (differ by
<=1 in both row and col). O(n), deterministic, no tunable parameter.
DBSCAN was considered and rejected: its eps/min_samples would be an
unvalidated parameter with no real spatial ground-truth to tune against,
and it would add scikit-learn as a new backend dependency (currently
pulled in only by the orphaned, unwired ensemble_service.py files
flagged in CLAUDE.md §9) -- see
docs/superpowers/specs/2026-08-31-regional-scan-design.md §4.
"""

from __future__ import annotations

_TIER_RANK = {"elevated": 0, "warning": 1}


def cluster_points(points: list[dict]) -> list[dict]:
    """Cluster already-flagged points by 8-connected grid adjacency.

    Args:
        points: list of {'point_id', 'lat', 'lng', 'row_idx', 'col_idx',
                          'spatial_anomaly_z', 'threshold_tier'}. Every member is
                already real/'ok' -- callers only ever pass flagged
                (status='ok', tiered) points, so this function's output
                satisfies spec §4's "computed only over real, status='ok'
                member cells" invariant by construction, not by filtering
                here.

    Returns:
        list of {'centroid_lat', 'centroid_lng', 'cell_count',
                  'mean_spatial_anomaly_z', 'max_spatial_anomaly_z', 'threshold_tier',
                  'member_point_ids'}, one per connected component.
        Empty list if `points` is empty.
    """
    by_coord = {(p["row_idx"], p["col_idx"]): p for p in points}
    parent: dict[tuple[int, int], tuple[int, int]] = {coord: coord for coord in by_coord}

    def find(coord):
        while parent[coord] != coord:
            parent[coord] = parent[parent[coord]]
            coord = parent[coord]
        return coord

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for row, col in by_coord:
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                if d_row == 0 and d_col == 0:
                    continue
                neighbor = (row + d_row, col + d_col)
                if neighbor in by_coord:
                    union((row, col), neighbor)

    groups: dict[tuple[int, int], list[dict]] = {}
    for coord, point in by_coord.items():
        groups.setdefault(find(coord), []).append(point)

    clusters = []
    for members in groups.values():
        lats = [m["lat"] for m in members]
        lngs = [m["lng"] for m in members]
        z_values = [m["spatial_anomaly_z"] for m in members]
        highest_tier = max(members, key=lambda m: _TIER_RANK[m["threshold_tier"]])["threshold_tier"]
        clusters.append(
            {
                "centroid_lat": sum(lats) / len(lats),
                "centroid_lng": sum(lngs) / len(lngs),
                "cell_count": len(members),
                "mean_spatial_anomaly_z": sum(z_values) / len(z_values),
                "max_spatial_anomaly_z": max(z_values),
                "threshold_tier": highest_tier,
                "member_point_ids": [m["point_id"] for m in members],
            }
        )
    return clusters
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_clustering.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/regional_scan/clustering.py backend/tests/test_regional_scan_clustering.py
git commit -m "feat(backend): add regional-scan grid-adjacency clustering"
```

---

### Task 4: Scan orchestration (`run_scan`)

**Files:**
- Create: `backend/src/regional_scan/scan.py`
- Test: `backend/tests/test_regional_scan_scan.py`

**Interfaces:**
- Consumes: `grid.generate_scan_grid(spacing_km) -> list[dict]` (Task 2), `clustering.cluster_points(points) -> list[dict]` (Task 3), `bridge.detect(lat, lng, date) -> dict` and `bridge.load_prediction_config() -> dict` and `bridge.GEEAuthError` (existing `backend/src/_detection.py`), `RegionalScanRun`/`RegionalScanPoint`/`RegionalScanCluster` (Task 1).
- Produces: `scan.run_scan(db: Session, target_date: str, grid_spacing_km: float, newest_scene_date: str | None = None) -> RegionalScanRun`. Task 5 (`trigger.py`) and Task 7 (CLI script) both call this with this exact signature.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_regional_scan_scan.py`:

```python
"""Integration test for run_scan() -- real DB (isolated SQLite, via the
`client` fixture), monkeypatched bridge.detect() so no live GEE call
happens (mirrors backend/tests/test_scheduler.py's pattern)."""

from __future__ import annotations

from sqlalchemy import select

from src import regional_scan
from src.db import SessionLocal
from src.db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from src.regional_scan import scan as scan_module


def _fake_detect_all_ok_high_anomaly(lat, lng, date):
    """Every point 'ok' with spatial_anomaly_z=2.5 (>= warning_z=2.0 in
    detection/src/config.yaml) -- forces every point flagged, so
    clustering has real work to do."""
    return {
        "status": "ok", "detected": True, "spatial_anomaly_z": 2.5,
        "index_used": "ndci", "index_values": {"ndci": 0.3}, "reason": None,
    }


def test_run_scan_persists_points_and_clusters(client, monkeypatch):
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_high_anomaly)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        assert run.status == "ok"
        assert run.total_points > 0
        assert run.count_ok == run.total_points
        assert run.count_error == 0

        points = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(points) == run.total_points
        assert all(p.status == "ok" for p in points)
        assert all(p.threshold_tier == "warning" for p in points)

        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        assert len(clusters) >= 1
        assert sum(c.cell_count for c in clusters) == run.total_points
    finally:
        db.close()


def _fake_detect_no_imagery(lat, lng, date):
    return {
        "status": "no_imagery", "detected": False, "spatial_anomaly_z": None,
        "index_used": "ndci", "index_values": None, "reason": "forced for test",
    }


def test_run_scan_no_imagery_points_are_stored_not_dropped(client, monkeypatch):
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_no_imagery)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        assert run.status == "ok"
        assert run.count_no_imagery == run.total_points
        assert run.count_ok == 0

        points = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(points) == run.total_points
        assert all(p.status == "no_imagery" for p in points)
        assert all(p.threshold_tier is None for p in points)

        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        assert clusters == []
    finally:
        db.close()


def test_run_scan_aborts_on_gee_auth_error_without_touching_prior_points(client, monkeypatch):
    # First, a real successful run leaves known-good points behind.
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_high_anomaly)
    db = SessionLocal()
    try:
        good_run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        prior_point_count = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(prior_point_count) == good_run.total_points

        # Then, a second run's very first detect() call raises
        # GEEAuthError -- must abort without discarding the prior points.
        def _raise(*_a, **_k):
            raise scan_module.bridge.GEEAuthError("forced for test")

        monkeypatch.setattr(scan_module.bridge, "detect", _raise)
        aborted_run = scan_module.run_scan(db, "2026-08-16", grid_spacing_km=20.0)

        assert aborted_run.status == "error"
        assert aborted_run.completed_at is not None

        still_there = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(still_there) == good_run.total_points
    finally:
        db.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.regional_scan.scan'`.

- [ ] **Step 3: Create `backend/src/regional_scan/scan.py`**

```python
"""
Regional scan orchestration (spec §2/§3/§4/§9): run_scan() generates the
grid (backend/src/regional_scan/grid.py), calls detect() unchanged
(detection/src/prediction.py, via backend/src/_detection.py) for every
point, tiers each 'ok' point against config.yaml's elevated_z/warning_z
cutoffs (the same cutoffs risk_level() uses -- no new numbers), clusters
the flagged points, and persists a latest-run snapshot.

GEEAuthError aborts the entire run (status='error') without touching
whatever RegionalScanPoint/RegionalScanCluster rows a prior successful
run already wrote -- it means the whole pipeline is unusable, not that
one point's reading is unavailable (see detect()'s own docstring;
mirrors scheduler.py's identical distinction for DetectionCache). Any
other per-point exception is caught individually (mirroring
scheduler.py's refresh_one_site) and stored as that point's 'error'
status, without killing the run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import _detection as bridge
from ..db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from .clustering import cluster_points
from .grid import generate_scan_grid

logger = logging.getLogger("backend.regional_scan.scan")


def _tier(spatial_anomaly_z: float, index_used: str, config: dict) -> str | None:
    """'warning' | 'elevated' | None, per config.yaml's thresholds --
    same cutoffs risk_level() reads, no new numbers (spec §3)."""
    index_thresholds = config["thresholds"][index_used]
    if spatial_anomaly_z >= index_thresholds["warning_z"]:
        return "warning"
    if spatial_anomaly_z >= index_thresholds["elevated_z"]:
        return "elevated"
    return None


def run_scan(
    db: Session,
    target_date: str,
    grid_spacing_km: float,
    newest_scene_date: str | None = None,
) -> RegionalScanRun:
    """Run one full regional scan and persist its results.

    Args:
        db: an open SQLAlchemy session (caller owns commit/close lifecycle
            for anything beyond this function's own commits).
        target_date: "YYYY-MM-DD" passed to detect() for every point.
        grid_spacing_km: grid spacing in km (backend/src/config.py
            REGIONAL_SCAN_GRID_SPACING_KM by default).
        newest_scene_date: the triggering poll's measured newest-scene
            timestamp, stored on the run row as the next poll's
            comparison baseline (spec §5/§6). None for a manually
            triggered run (backend/scripts/run_regional_scan.py) that
            didn't go through the poll.

    Returns:
        The persisted RegionalScanRun row (status='ok', 'partial_error',
        or 'error').
    """
    grid = generate_scan_grid(grid_spacing_km)
    run = RegionalScanRun(
        started_at=datetime.now(timezone.utc),
        status="running",
        grid_spacing_km=grid_spacing_km,
        date_used=target_date,
        newest_scene_date=newest_scene_date,
        total_points=len(grid),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    config = bridge.load_prediction_config()
    flagged_for_clustering: list[dict] = []
    counts = {"ok": 0, "no_imagery": 0, "no_water_pixels": 0, "no_climatology": 0, "error": 0}

    try:
        for point in grid:
            try:
                result = bridge.detect(point["lat"], point["lng"], target_date)
            except bridge.GEEAuthError:
                raise
            except Exception as exc:  # noqa: BLE001 -- per-point guard, mirrors scheduler.py
                logger.warning(
                    "regional_scan: point %s failed: %s: %s",
                    point["point_id"], type(exc).__name__, exc,
                )
                result = {
                    "status": "error", "detected": False, "spatial_anomaly_z": None,
                    "index_used": None, "index_values": None,
                    "reason": f"{type(exc).__name__}: {exc}",
                }

            status = result["status"]
            counts[status] = counts.get(status, 0) + 1

            tier = None
            if status == "ok" and result["spatial_anomaly_z"] is not None:
                tier = _tier(result["spatial_anomaly_z"], result["index_used"], config)

            existing = db.get(RegionalScanPoint, point["point_id"])
            fields = dict(
                lat=point["lat"], lng=point["lng"],
                row_idx=point["row_idx"], col_idx=point["col_idx"],
                status=status, index_values=result.get("index_values"),
                spatial_anomaly_z=result.get("spatial_anomaly_z"), threshold_tier=tier,
                run_id=run.id,
            )
            if existing is None:
                db.add(RegionalScanPoint(point_id=point["point_id"], **fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)

            if status == "ok" and tier is not None:
                flagged_for_clustering.append(
                    {
                        "point_id": point["point_id"], "lat": point["lat"], "lng": point["lng"],
                        "row_idx": point["row_idx"], "col_idx": point["col_idx"],
                        "spatial_anomaly_z": result["spatial_anomaly_z"], "threshold_tier": tier,
                    }
                )
    except bridge.GEEAuthError as exc:
        # Deliberately does NOT touch any RegionalScanPoint/RegionalScanCluster
        # row written by a prior successful run -- an aborted run must
        # never discard the last known-good snapshot (mirrors
        # scheduler.py's stale-marking, not deleting, on failure).
        run.status = "error"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.error("regional_scan: run %s aborted, GEEAuthError: %s", run.id, exc)
        return run

    # Grid points not touched this run (a spacing change from a prior
    # run) are stale -- drop them so /regional-scan never serves a point
    # from a grid resolution that's no longer in effect.
    current_point_ids = {p["point_id"] for p in grid}
    stale_points = db.execute(
        select(RegionalScanPoint).where(RegionalScanPoint.point_id.not_in(current_point_ids))
    ).scalars().all()
    for row in stale_points:
        db.delete(row)

    # Clusters are recomputed whole every run -- unlike points, cluster
    # membership has no stable identity across runs to upsert by.
    prior_clusters = db.execute(
        select(RegionalScanCluster).where(RegionalScanCluster.run_id != run.id)
    ).scalars().all()
    for row in prior_clusters:
        db.delete(row)
    clusters = cluster_points(flagged_for_clustering)
    for cluster in clusters:
        db.add(RegionalScanCluster(run_id=run.id, **cluster))

    run.completed_at = datetime.now(timezone.utc)
    run.count_ok = counts["ok"]
    run.count_no_imagery = counts["no_imagery"]
    run.count_no_water_pixels = counts["no_water_pixels"]
    run.count_no_climatology = counts["no_climatology"]
    run.count_error = counts["error"]
    run.status = "partial_error" if counts["error"] > 0 else "ok"
    db.commit()
    logger.info(
        "regional_scan: run %s done -- status=%s ok=%d no_imagery=%d no_water_pixels=%d "
        "no_climatology=%d error=%d clusters=%d",
        run.id, run.status, counts["ok"], counts["no_imagery"], counts["no_water_pixels"],
        counts["no_climatology"], counts["error"], len(clusters),
    )
    return run
```

- [ ] **Step 4: Create `backend/src/regional_scan/__init__.py`'s sibling import surface (already created in Task 2) — no change needed here.** Skip to Step 5.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_scan.py -v`
Expected: PASS (3 tests). If `test_run_scan_persists_points_and_clusters` fails because `generate_scan_grid(20.0)` produces zero or one point, that's a real grid-generation bug to fix in Task 2, not a reason to loosen this test.

- [ ] **Step 6: Commit**

```bash
git add backend/src/regional_scan/scan.py backend/tests/test_regional_scan_scan.py
git commit -m "feat(backend): add regional-scan orchestration (run_scan)"
```

---

### Task 5: Scene-freshness poll (data-pipeline → detection → backend bridge chain) + trigger logic

**Files:**
- Create: `data-pipeline/src/scene_poll.py`
- Modify: `data-pipeline/src/__init__.py`
- Modify: `detection/src/_data_pipeline.py`
- Modify: `backend/src/_detection.py`
- Create: `backend/src/regional_scan/trigger.py`
- Test: `data-pipeline/tests/test_scene_poll.py`
- Test: `backend/tests/test_regional_scan_trigger.py`

**Interfaces:**
- Produces: `scene_poll.get_newest_scene_timestamp(polygon_latlng: tuple, since_date: str) -> str | None`, re-exported unchanged through both bridges up to `backend/src/_detection.py`'s `get_newest_scene_timestamp`.
- Consumes (from Task 1): `config.REGIONAL_SCAN_COOLDOWN_HOURS`, `config.REGIONAL_SCAN_POLL_LOOKBACK_DAYS`, `config.REGIONAL_SCAN_GRID_SPACING_KM`, `config.as_aware_utc`, `config.today_str`, `RegionalScanRun`.
- Consumes (from Task 4): `scan.run_scan(...)`.
- Produces: `trigger.should_trigger_scan(last_run: RegionalScanRun | None, newest_scene_date: str | None, cooldown_hours: int, now: datetime) -> bool` (pure), `trigger.poll_and_maybe_scan() -> None` (impure orchestrator, called by Task 6's scheduler job).

- [ ] **Step 1: Write the failing data-pipeline test (import-only, no live GEE call)**

Create `data-pipeline/tests/test_scene_poll.py`:

```python
"""Import-only test for scene_poll.py -- get_newest_scene_timestamp()
itself requires a live GEE session (it calls initialize_ee()), so it is
not exercised here (no fixture in this suite fakes `ee`, matching the
rest of this project's "GEE-touching functions are exercised live during
manual builds, not against a mocked ee" convention -- see
data-pipeline/README.md). This test only proves the module is importable
and its signature is what the detection/backend bridges expect."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scene_poll import get_newest_scene_timestamp


def test_get_newest_scene_timestamp_signature():
    sig = inspect.signature(get_newest_scene_timestamp)
    assert list(sig.parameters) == ["polygon_latlng", "since_date"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd data-pipeline && ./venv/bin/python -m pytest tests/test_scene_poll.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.scene_poll'`.

- [ ] **Step 3: Create `data-pipeline/src/scene_poll.py`**

```python
"""
Sentinel-2 scene-freshness poll for the regional scan's event-driven
trigger (docs/superpowers/specs/2026-08-31-regional-scan-design.md §5).

A single server-side metadata query (filterBounds + filterDate +
aggregate_max('system:time_start')) -- no per-point loop, no pixel
reduction. Measured live, 2026-08-31: 0.75s -- roughly 10,000x cheaper
than the full grid scan it gates (spec §5). Not itself a detection call:
tells the caller only whether any new Sentinel-2 scene has landed over
the study area since `since_date`, nothing about bloom status.
"""

from __future__ import annotations

from datetime import datetime, timezone

import ee

from .auth import initialize_ee


def get_newest_scene_timestamp(
    polygon_latlng: tuple[tuple[float, float], ...], since_date: str
) -> str | None:
    """Newest Sentinel-2 scene's acquisition timestamp intersecting
    `polygon_latlng` since `since_date`, as an ISO 8601 UTC string, or
    None if no scene was found in that window.

    Args:
        polygon_latlng: (lat, lng) vertices in order, implicitly closed
            (e.g. study_area.py's STUDY_AREA_POLYGON_LATLNG).
        since_date: "YYYY-MM-DD", the start of the lookback window.

    Raises:
        GEEAuthError: propagated, never caught.
    """
    initialize_ee()

    ring = [[lng, lat] for lat, lng in polygon_latlng]
    polygon = ee.Geometry.Polygon([ring])
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    max_ts = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(polygon)
        .filterDate(since_date, now_date)
        .aggregate_max("system:time_start")
        .getInfo()
    )
    if max_ts is None:
        return None
    return datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc).isoformat()
```

- [ ] **Step 4: Re-export through `data-pipeline/src/__init__.py`**

In `data-pipeline/src/__init__.py`, add the import and `__all__` entry:

```python
from .scene_poll import get_newest_scene_timestamp
```

(placed alongside the other `from .* import ...` lines) and add `"get_newest_scene_timestamp"` to `__all__`. Also add it to the module docstring's "Public functions re-exported here" list:

```
    get_newest_scene_timestamp(polygon_latlng, since_date)  -- Sentinel-2
                                               scene-freshness poll, see
                                               scene_poll.py
```

- [ ] **Step 5: Re-export through `detection/src/_data_pipeline.py`**

Add after the `check_point_in_study_area = _dp.check_point_in_study_area` line:

```python
# Sentinel-2 scene-freshness poll (data-pipeline/src/scene_poll.py) --
# added for backend-api's regional-scan event-driven trigger. Re-exported
# purely as a pass-through, same reasoning as check_point_in_study_area
# above.
get_newest_scene_timestamp = _dp.get_newest_scene_timestamp
```

and add `"get_newest_scene_timestamp"` to that file's `__all__`.

- [ ] **Step 6: Re-export through `backend/src/_detection.py`**

Add after the `check_point_in_study_area = _data_pipeline_bridge.check_point_in_study_area` line:

```python
# Sentinel-2 scene-freshness poll -- used by
# backend/src/regional_scan/trigger.py's poll_and_maybe_scan().
get_newest_scene_timestamp = _data_pipeline_bridge.get_newest_scene_timestamp
```

and add `"get_newest_scene_timestamp"` to that file's `__all__`.

- [ ] **Step 7: Run the data-pipeline test to verify it passes**

Run: `cd data-pipeline && ./venv/bin/python -m pytest tests/test_scene_poll.py -v`
Expected: PASS.

- [ ] **Step 8: Write the failing backend trigger test**

Create `backend/tests/test_regional_scan_trigger.py`:

```python
"""Unit tests for should_trigger_scan() -- pure decision function (spec
§5), no DB, no GEE. poll_and_maybe_scan() (the impure orchestrator) is
exercised separately in test_regional_scan_scan.py-adjacent integration
coverage via Task 6's scheduler test, not here."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.db_models import RegionalScanRun
from src.regional_scan.trigger import should_trigger_scan

_NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


def test_no_scene_info_never_triggers():
    assert should_trigger_scan(None, None, cooldown_hours=20, now=_NOW) is False


def test_first_ever_run_triggers_when_a_scene_exists():
    assert should_trigger_scan(None, "2026-08-30T10:00:00+00:00", cooldown_hours=20, now=_NOW) is True


def test_same_scene_as_last_run_does_not_trigger():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=30), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-30T10:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is False


def test_newer_scene_but_cooldown_not_elapsed_does_not_trigger():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=5), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-31T09:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is False


def test_newer_scene_and_cooldown_elapsed_triggers():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=21), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-31T09:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is True


def test_cooldown_elapsed_but_no_newer_scene_does_not_trigger():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=21), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-29T10:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is False
```

- [ ] **Step 9: Run the test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_trigger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.regional_scan.trigger'`.

- [ ] **Step 10: Create `backend/src/regional_scan/trigger.py`**

```python
"""
Event-driven poll + cooldown trigger for the regional scan (spec §5).
`should_trigger_scan` is a pure decision function (unit-testable without
GEE or a DB); `poll_and_maybe_scan` is the impure orchestrator the
scheduler job (backend/src/scheduler.py) calls on its own interval.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import _detection as bridge
from .. import _study_area
from ..config import (
    REGIONAL_SCAN_COOLDOWN_HOURS,
    REGIONAL_SCAN_GRID_SPACING_KM,
    REGIONAL_SCAN_POLL_LOOKBACK_DAYS,
    as_aware_utc,
    today_str,
)
from ..db import SessionLocal
from ..db_models import RegionalScanRun
from .scan import run_scan

logger = logging.getLogger("backend.regional_scan.trigger")


def should_trigger_scan(
    last_run: RegionalScanRun | None,
    newest_scene_date: str | None,
    cooldown_hours: int,
    now: datetime,
) -> bool:
    """Pure decision function -- spec §5's "both (a) and (b)" rule.

    (a) the poll's newest scene timestamp is newer than the last run's
        stored newest_scene_date.
    (b) at least `cooldown_hours` have elapsed since the last run started.

    No prior run -> True the moment a scene exists (nothing to compare
    against, nothing to cool down from). No scene info from the poll ->
    False (nothing to trigger on).
    """
    if newest_scene_date is None:
        return False
    if last_run is None:
        return True
    is_new_scene = (
        last_run.newest_scene_date is None or newest_scene_date > last_run.newest_scene_date
    )
    cooldown_met = (now - as_aware_utc(last_run.started_at)) >= timedelta(hours=cooldown_hours)
    return is_new_scene and cooldown_met


def poll_and_maybe_scan() -> None:
    """The scheduled job body: poll for scene freshness, decide, and run
    a full scan if warranted. Never raises -- a poll/scan failure here
    must not crash the scheduler process (mirrors scheduler.py's own
    top-level guard in refresh_one_site)."""
    db = SessionLocal()
    try:
        last_run = db.execute(
            select(RegionalScanRun).order_by(RegionalScanRun.started_at.desc())
        ).scalars().first()

        since = datetime.now(timezone.utc) - timedelta(days=REGIONAL_SCAN_POLL_LOOKBACK_DAYS)
        try:
            newest_scene_date = bridge.get_newest_scene_timestamp(
                _study_area.STUDY_AREA_POLYGON_LATLNG, since.strftime("%Y-%m-%d")
            )
        except bridge.GEEAuthError as exc:
            logger.error("regional_scan poll: GEEAuthError, skipping this tick: %s", exc)
            return

        now = datetime.now(timezone.utc)
        if not should_trigger_scan(last_run, newest_scene_date, REGIONAL_SCAN_COOLDOWN_HOURS, now):
            logger.info(
                "regional_scan poll: not triggering (newest_scene_date=%s, last_run_id=%s)",
                newest_scene_date, last_run.id if last_run else None,
            )
            return

        logger.info("regional_scan poll: triggering full scan (newest_scene_date=%s)", newest_scene_date)
        run_scan(db, today_str(), REGIONAL_SCAN_GRID_SPACING_KM, newest_scene_date=newest_scene_date)
    except Exception as exc:  # noqa: BLE001 -- top-level scheduler-job guard
        logger.error("regional_scan poll: unexpected failure: %s: %s", type(exc).__name__, exc)
    finally:
        db.close()
```

- [ ] **Step 11: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_trigger.py -v`
Expected: PASS (6 tests).

- [ ] **Step 12: Run the full backend and data-pipeline suites to check nothing else broke**

Run: `cd backend && ./venv/bin/python -m pytest tests/ -q && cd ../data-pipeline && ./venv/bin/python -m pytest tests/ -q`
Expected: all prior tests still PASS, plus the new ones.

- [ ] **Step 13: Commit**

```bash
git add data-pipeline/src/scene_poll.py data-pipeline/src/__init__.py \
        detection/src/_data_pipeline.py backend/src/_detection.py \
        backend/src/regional_scan/trigger.py \
        data-pipeline/tests/test_scene_poll.py backend/tests/test_regional_scan_trigger.py
git commit -m "feat: add regional-scan scene-freshness poll and event-driven trigger"
```

---

### Task 6: Scheduler wiring + CLI script

**Files:**
- Modify: `backend/src/scheduler.py`
- Create: `backend/scripts/run_regional_scan.py`
- Test: `backend/tests/test_regional_scan_scheduler_job.py`

**Interfaces:**
- Consumes: `trigger.poll_and_maybe_scan` (Task 5), `scan.run_scan` (Task 4), `config.REGIONAL_SCAN_POLL_INTERVAL_HOURS` / `REGIONAL_SCAN_GRID_SPACING_KM` (Task 1).
- Produces: `create_scheduler()` (existing function) now also registers job id `"poll_regional_scan"`, without `next_run_time` override (never fires at startup, spec §8).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_regional_scan_scheduler_job.py`:

```python
"""Proves the regional-scan poll job is registered on the real scheduler
with the right interval and, critically, WITHOUT firing at startup
(spec §8) -- unlike refresh_grid, which deliberately does fire
immediately (next_run_time=now())."""

from __future__ import annotations

from src.config import REGIONAL_SCAN_POLL_INTERVAL_HOURS
from src.scheduler import create_scheduler


def test_poll_regional_scan_job_registered_without_immediate_fire():
    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("poll_regional_scan")
        assert job is not None
        assert job.trigger.interval.total_seconds() == REGIONAL_SCAN_POLL_INTERVAL_HOURS * 3600
        assert job.max_instances == 1

        refresh_grid_job = scheduler.get_job("refresh_grid")
        # refresh_grid fires immediately at startup; poll_regional_scan
        # must not -- its next run time is roughly one full interval
        # away, not "now".
        assert job.next_run_time > refresh_grid_job.next_run_time
    finally:
        scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_scheduler_job.py -v`
Expected: FAIL with `AssertionError: assert None is not None` (job not registered yet).

- [ ] **Step 3: Wire the job into `backend/src/scheduler.py`**

Add to the imports at the top:

```python
from .config import SCHEDULER_INTERVAL_MINUTES, REGIONAL_SCAN_POLL_INTERVAL_HOURS, today_str
from .regional_scan.trigger import poll_and_maybe_scan
```

(replacing the existing narrower `from .config import SCHEDULER_INTERVAL_MINUTES, today_str` line with the combined one above).

In `create_scheduler()`, add a second `add_job` call after the existing `refresh_grid` one:

```python
def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        refresh_grid,
        "interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        next_run_time=datetime.now(timezone.utc),  # fire once immediately at startup too
        id="refresh_grid",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        poll_and_maybe_scan,
        "interval",
        hours=REGIONAL_SCAN_POLL_INTERVAL_HOURS,
        id="poll_regional_scan",
        max_instances=1,
        coalesce=True,
        # Deliberately no next_run_time override -- must NOT fire at
        # process startup (spec §8): a job that can run for hours firing
        # on every --reload dev restart would be unworkable. max_instances=1
        # also doubles as overlap protection for the scan phase inside
        # poll_and_maybe_scan.
    )
    return scheduler
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_scheduler_job.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && ./venv/bin/python -m pytest tests/ -q`
Expected: all tests still PASS (in particular `test_scheduler.py`, which also constructs schedulers/clients).

- [ ] **Step 6: Create `backend/scripts/run_regional_scan.py`**

```python
"""
Manual trigger for one regional scan, without waiting on the poll/
cooldown cycle -- provides a manual-
trigger pattern (docs/superpowers/specs/2026-08-31-regional-scan-design.md
§8). Makes real, live GEE calls -- up to ~500 Sentinel-2/MODIS reads,
measured 1-3.6hr range (spec §2).

    cd backend && source venv/bin/activate && python scripts/run_regional_scan.py [--date YYYY-MM-DD] [--spacing-km 5]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.config import REGIONAL_SCAN_GRID_SPACING_KM, today_str  # noqa: E402
from src.db import SessionLocal, init_db  # noqa: E402
from src.regional_scan.scan import run_scan  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today (UTC)")
    parser.add_argument(
        "--spacing-km", type=float, default=REGIONAL_SCAN_GRID_SPACING_KM,
        help=f"grid spacing in km (default {REGIONAL_SCAN_GRID_SPACING_KM})",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        run = run_scan(db, args.date or today_str(), args.spacing_km)
        print(
            f"run {run.id}: status={run.status} total_points={run.total_points} "
            f"ok={run.count_ok} no_imagery={run.count_no_imagery} "
            f"no_water_pixels={run.count_no_water_pixels} "
            f"no_climatology={run.count_no_climatology} error={run.count_error}"
        )
        if run.status == "error":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Smoke-check the script parses and imports cleanly (no live GEE call needed for this check)**

Run: `cd backend && ./venv/bin/python -c "import ast; ast.parse(open('scripts/run_regional_scan.py').read())"`
Expected: no output (parses cleanly). Do not run the script itself here — it makes real, slow GEE calls; that is a manual step for whoever has live GEE auth configured.

- [ ] **Step 8: Commit**

```bash
git add backend/src/scheduler.py backend/scripts/run_regional_scan.py backend/tests/test_regional_scan_scheduler_job.py
git commit -m "feat(backend): wire regional-scan poll job into scheduler, add manual CLI trigger"
```

---

### Task 7: `GET /regional-scan` endpoint

**Files:**
- Modify: `backend/src/schemas.py`
- Create: `backend/src/routers/regional_scan.py`
- Modify: `backend/src/main.py`
- Test: `backend/tests/test_regional_scan_endpoint.py`

**Interfaces:**
- Consumes: `RegionalScanRun`/`RegionalScanPoint`/`RegionalScanCluster` (Task 1).
- Produces: `GET /regional-scan` returning `RegionalScanResponse` — `{disclaimer, caveat, run: {...} | null, points: [...], clusters: [...]}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_regional_scan_endpoint.py`:

```python
"""GET /regional-scan -- pure cache read, never calls GEE (spec §7).
Seeds RegionalScanRun/Point/Cluster rows directly via the DB session
(mirrors test_scheduler.py's direct-DB-seeding style) rather than
running a real scan."""

from __future__ import annotations

from datetime import datetime, timezone

from src.db import SessionLocal
from src.db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun


def test_regional_scan_empty_state_before_any_run(client):
    resp = client.get("/regional-scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"] is None
    assert body["points"] == []
    assert body["clusters"] == []
    assert "disclaimer" in body
    assert "caveat" in body


def test_regional_scan_returns_latest_run_points_and_clusters(client):
    db = SessionLocal()
    try:
        run = RegionalScanRun(
            started_at=datetime(2026, 8, 31, 6, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 8, 31, 6, 5, 0, tzinfo=timezone.utc),
            status="ok", grid_spacing_km=5.0, date_used="2026-08-31",
            newest_scene_date="2026-08-30T10:00:00+00:00", total_points=2,
            count_ok=2, count_no_imagery=0, count_no_water_pixels=0,
            count_no_climatology=0, count_error=0,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        db.add(RegionalScanPoint(
            point_id="0_0", lat=13.0, lng=100.5, row_idx=0, col_idx=0,
            status="ok", index_values={"ndci": 0.2}, spatial_anomaly_z=2.5,
            threshold_tier="warning", run_id=run.id,
        ))
        db.add(RegionalScanPoint(
            point_id="0_1", lat=13.05, lng=100.5, row_idx=0, col_idx=1,
            status="ok", index_values={"ndci": 0.19}, spatial_anomaly_z=2.4,
            threshold_tier="warning", run_id=run.id,
        ))
        db.add(RegionalScanCluster(
            run_id=run.id, centroid_lat=13.025, centroid_lng=100.5, cell_count=2,
            mean_spatial_anomaly_z=2.45, max_spatial_anomaly_z=2.5, threshold_tier="warning",
            member_point_ids=["0_0", "0_1"],
        ))
        db.commit()

        resp = client.get("/regional-scan")
        assert resp.status_code == 200
        body = resp.json()

        assert body["run"]["run_id"] == run.id
        assert body["run"]["status"] == "ok"
        assert body["run"]["total_points"] == 2

        assert len(body["points"]) == 2
        assert {p["point_id"] for p in body["points"]} == {"0_0", "0_1"}

        assert len(body["clusters"]) == 1
        assert body["clusters"][0]["cell_count"] == 2
        assert set(body["clusters"][0]["member_point_ids"]) == {"0_0", "0_1"}
    finally:
        db.execute_delete_cleanup = None  # no-op placeholder removed below
        db.close()


def test_root_route_lists_regional_scan_endpoint(client):
    resp = client.get("/")
    assert "/regional-scan" in resp.json()["endpoints"]
```

Remove the stray `db.execute_delete_cleanup = None` line before saving — it was a placeholder slip; the test does not need explicit teardown since the isolated per-session SQLite DB (`backend/tests/conftest.py`) is unique per test run already via `tempfile.mkdtemp`. Final version of that `finally` block is just:

```python
    finally:
        db.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_endpoint.py -v`
Expected: FAIL with 404 (no `/regional-scan` route registered yet).

- [ ] **Step 3: Add schemas to `backend/src/schemas.py`**

Append at the end of the file:

```python
# --------------------------------------------------------------------------
# /regional-scan
# --------------------------------------------------------------------------

REGIONAL_SCAN_CAVEAT_TEXT = (
    "This is a detection scan -- current anomaly state from real, live "
    "Sentinel-2 readings across the full upper Gulf study-area polygon, "
    "the same detect() pipeline /detect and /risk-map use. It is a "
    "separate output from the unvalidated Ang Sila spatial-trend test "
    "and must not be blurred together with it."
)


class RegionalScanPointSchema(BaseModel):
    point_id: str
    lat: float
    lng: float
    status: Literal["ok", "no_imagery", "no_water_pixels", "no_climatology", "error"]
    index_values: dict[str, float] | None = None
    spatial_anomaly_z: float | None = None
    threshold_tier: Literal["elevated", "warning"] | None = None


class RegionalScanClusterSchema(BaseModel):
    centroid_lat: float
    centroid_lng: float
    cell_count: int
    mean_spatial_anomaly_z: float
    max_spatial_anomaly_z: float
    threshold_tier: Literal["elevated", "warning"]
    member_point_ids: list[str]


class RegionalScanRunMeta(BaseModel):
    run_id: int
    started_at: str
    completed_at: str | None
    status: Literal["running", "ok", "partial_error", "error"]
    grid_spacing_km: float
    date_used: str
    newest_scene_date: str | None
    total_points: int
    count_ok: int
    count_no_imagery: int
    count_no_water_pixels: int
    count_no_climatology: int
    count_error: int


class RegionalScanResponse(DisclaimerMixin):
    caveat: str = Field(default=REGIONAL_SCAN_CAVEAT_TEXT)
    run: RegionalScanRunMeta | None = Field(
        default=None, description="Null only if no regional scan has completed yet."
    )
    points: list[RegionalScanPointSchema] = []
    clusters: list[RegionalScanClusterSchema] = []
```

- [ ] **Step 4: Create `backend/src/routers/regional_scan.py`**

```python
"""GET /regional-scan -- pure cache read of the latest full-polygon
regional bloom scan (docs/superpowers/specs/2026-08-31-regional-scan-design.md).
Never calls GEE live, same convention as /risk-map and /summary -- the
scan itself runs on the poll/cooldown scheduler job
(backend/src/regional_scan/trigger.py) or the manual CLI script
(backend/scripts/run_regional_scan.py), never inside a request."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from ..schemas import (
    RegionalScanClusterSchema,
    RegionalScanPointSchema,
    RegionalScanResponse,
    RegionalScanRunMeta,
)

router = APIRouter()


@router.get("/regional-scan", response_model=RegionalScanResponse, tags=["regional-scan"])
async def get_regional_scan(db: Session = Depends(get_db)) -> RegionalScanResponse:
    latest_run = db.execute(
        select(RegionalScanRun).order_by(RegionalScanRun.started_at.desc())
    ).scalars().first()

    if latest_run is None:
        return RegionalScanResponse(run=None, points=[], clusters=[])

    points = db.execute(select(RegionalScanPoint)).scalars().all()
    clusters = db.execute(
        select(RegionalScanCluster).where(RegionalScanCluster.run_id == latest_run.id)
    ).scalars().all()

    return RegionalScanResponse(
        run=RegionalScanRunMeta(
            run_id=latest_run.id,
            started_at=as_aware_utc(latest_run.started_at).isoformat(),
            completed_at=(
                as_aware_utc(latest_run.completed_at).isoformat()
                if latest_run.completed_at else None
            ),
            status=latest_run.status,
            grid_spacing_km=latest_run.grid_spacing_km,
            date_used=latest_run.date_used,
            newest_scene_date=latest_run.newest_scene_date,
            total_points=latest_run.total_points,
            count_ok=latest_run.count_ok,
            count_no_imagery=latest_run.count_no_imagery,
            count_no_water_pixels=latest_run.count_no_water_pixels,
            count_no_climatology=latest_run.count_no_climatology,
            count_error=latest_run.count_error,
        ),
        points=[
            RegionalScanPointSchema(
                point_id=p.point_id, lat=p.lat, lng=p.lng, status=p.status,
                index_values=p.index_values, spatial_anomaly_z=p.spatial_anomaly_z,
                threshold_tier=p.threshold_tier,
            )
            for p in points
        ],
        clusters=[
            RegionalScanClusterSchema(
                centroid_lat=c.centroid_lat, centroid_lng=c.centroid_lng,
                cell_count=c.cell_count, mean_spatial_anomaly_z=c.mean_spatial_anomaly_z,
                max_spatial_anomaly_z=c.max_spatial_anomaly_z, threshold_tier=c.threshold_tier,
                member_point_ids=c.member_point_ids,
            )
            for c in clusters
        ],
    )
```

- [ ] **Step 5: Wire the router into `backend/src/main.py`**

Change the router import line:

```python
from .routers import alerts, detect, regional_scan, risk_map, satellite, satellite_image, summary, timeseries
```

Add alongside the existing router registrations:

```python
app.include_router(regional_scan.router)
```

Add `"/regional-scan"` to the `root()` route's `endpoints` list:

```python
        "endpoints": [
            "/risk-map",
            "/risk-map/{site_id}/image",
            "/timeseries",
            "/detect",
            "/satellite-image",
            "/summary",
            "/regional-scan",
        ],
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_regional_scan_endpoint.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && ./venv/bin/python -m pytest tests/ -q`
Expected: all tests PASS (should now be 23 + the new regional-scan tests from Tasks 1-7).

- [ ] **Step 8: Commit**

```bash
git add backend/src/schemas.py backend/src/routers/regional_scan.py backend/src/main.py backend/tests/test_regional_scan_endpoint.py
git commit -m "feat(backend): add GET /regional-scan endpoint"
```

---

### Task 8: Frontend regional-scan map layer

**Files:**
- Modify: `frontend/src/api/client.js`
- Create: `frontend/src/components/RegionalScanLayer.jsx`
- Modify: `frontend/src/pages/OverviewPage.jsx`

**Interfaces:**
- Consumes: `GET /regional-scan` response shape from Task 7 (`{disclaimer, caveat, run, points, clusters}`).
- Produces: `getRegionalScan()` (client.js), `<RegionalScanLayer data={regionalScanData} />` (a self-contained react-leaflet layer, rendered only inside a `<MapContainer>`).

This is intentionally the lightest task in this plan — spec §10 scopes it as "its own component; does not touch the existing 6-site grid, RiskMap.jsx's existing markers, or any existing endpoint." No frontend test harness exists in this repo yet (only `npm run lint`/`npm run build`), so verification here is lint + build + a manual dev-server check, not a new test file.

- [ ] **Step 1: Add `getRegionalScan()` to `frontend/src/api/client.js`**

Add alongside the existing API helpers:

```javascript
export async function getRegionalScan() {
  const { data } = await client.get('/regional-scan')
  return data
}
```

- [ ] **Step 2: Create `frontend/src/components/RegionalScanLayer.jsx`**

```jsx
import { Fragment, useMemo } from 'react'
import { CircleMarker, Tooltip } from 'react-leaflet'
import { RISK_COLOR_HEX } from '../constants.js'

/**
 * Full-polygon regional bloom scan overlay (backend GET /regional-scan) --
 * a distinct layer from RiskMap.jsx's 6-site monitoring grid, per spec
 * §0/§10: does not touch or replace that grid or any of its markers.
 * Renders real NDCI/2BDA/3BDA/spatial_anomaly_z values in each pin's popup --
 * never a colored dot with no data behind it (no-fabrication rule, §0).
 * Must be rendered inside a react-leaflet <MapContainer>.
 */
export default function RegionalScanLayer({ data }) {
  const clusters = data?.clusters || []
  const points = data?.points || []

  // Points already covered by a cluster are shown once, via the
  // cluster marker -- avoids stacking a cluster circle directly on top
  // of its own single-point members.
  const clusteredPointIds = useMemo(
    () => new Set(clusters.flatMap((c) => c.member_point_ids)),
    [clusters],
  )
  const unclustered = useMemo(
    () => points.filter((p) => p.threshold_tier && !clusteredPointIds.has(p.point_id)),
    [points, clusteredPointIds],
  )

  if (!data?.run) return null

  return (
    <>
      {clusters.map((cluster, i) => (
        <CircleMarker
          key={`cluster-${i}`}
          center={[cluster.centroid_lat, cluster.centroid_lng]}
          radius={Math.min(10 + cluster.cell_count * 2, 40)}
          pathOptions={{
            color: RISK_COLOR_HEX[cluster.threshold_tier],
            weight: 1.5,
            fillColor: RISK_COLOR_HEX[cluster.threshold_tier],
            fillOpacity: 0.35,
          }}
        >
          <Tooltip direction="top" offset={[0, -10]} opacity={0.95}>
            <div style={{ fontWeight: 600, fontSize: '13px' }}>
              Cluster of {cluster.cell_count} cells
            </div>
            <div style={{ fontSize: '11.5px', marginTop: '2px', color: '#1d1d1f' }}>
              mean spatial_anomaly_z {cluster.mean_spatial_anomaly_z.toFixed(2)} · max {cluster.max_spatial_anomaly_z.toFixed(2)}
            </div>
          </Tooltip>
        </CircleMarker>
      ))}
      {unclustered.map((point) => (
        <Fragment key={point.point_id}>
          <CircleMarker
            center={[point.lat, point.lng]}
            radius={6}
            pathOptions={{
              color: RISK_COLOR_HEX[point.threshold_tier],
              weight: 1.5,
              fillColor: RISK_COLOR_HEX[point.threshold_tier],
              fillOpacity: 0.6,
            }}
          >
            <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
              <div style={{ fontSize: '11.5px' }}>
                spatial_anomaly_z {point.spatial_anomaly_z?.toFixed(2)}
                {point.index_values
                  ? ` · ${Object.entries(point.index_values)
                      .map(([k, v]) => `${k}=${v.toFixed(3)}`)
                      .join(', ')}`
                  : ''}
              </div>
            </Tooltip>
          </CircleMarker>
        </Fragment>
      ))}
    </>
  )
}
```

- [ ] **Step 3: Wire the layer behind a toggle in `frontend/src/pages/OverviewPage.jsx`**

Add the import at the top:

```javascript
import { useApi } from '../hooks/useApi.js'
import { getRiskMap, getRegionalScan } from '../api/client.js'
import RegionalScanLayer from '../components/RegionalScanLayer.jsx'
```

(merge `getRegionalScan` into the existing `getRiskMap` import line rather than duplicating the import statement).

Add a second `useApi` call and a toggle state, inside the `OverviewPage` component body, after the existing `useApi(getRiskMap, [])` line:

```javascript
  const [showRegionalScan, setShowRegionalScan] = useState(false)
  const { data: regionalScanData } = useApi(getRegionalScan, [], { enabled: showRegionalScan })
```

(add `showRegionalScan` state alongside the existing `mode`/`selectedSite` `useState` calls).

Render the layer and its toggle inside the existing `{data && data.features.length > 0 && (...)}` block, immediately after `<RiskMap ... />`:

```jsx
            <RiskMap
              featureCollection={data}
              mode={mode}
              onSelectSite={setSelectedSite}
            />
```

becomes:

```jsx
            <RiskMap
              featureCollection={data}
              mode={mode}
              onSelectSite={setSelectedSite}
            >
              {showRegionalScan && <RegionalScanLayer data={regionalScanData} />}
            </RiskMap>
```

This requires `RiskMap` to render `{children}` inside its `<MapContainer>` — react-leaflet layers must be descendants of `MapContainer` to access the map context, so `RegionalScanLayer` cannot be a sibling of `<RiskMap>`.

- [ ] **Step 4: Make `RiskMap.jsx` accept and render `children`**

In `frontend/src/components/RiskMap.jsx`, add `children` to the destructured props and render it once inside `<MapContainer>`, after the existing marker `.map(...)` block and before the closing `</MapContainer>`:

```jsx
export default function RiskMap({ featureCollection, onSelectSite = () => {}, mode = 'risk', children }) {
```

and, near the end of the JSX (just before `</MapContainer>`):

```jsx
      {children}
    </MapContainer>
```

- [ ] **Step 5: Add the toggle button, next to the existing `MapControls`**

Immediately after `<MapControls mode={mode} onModeChange={setMode} />` in `OverviewPage.jsx`:

```jsx
            <MapControls mode={mode} onModeChange={setMode} />
            <button
              type="button"
              className="map-segmented-control glass"
              style={{ position: 'absolute', top: 76, left: 16, zIndex: 500 }}
              onClick={() => setShowRegionalScan((v) => !v)}
              aria-pressed={showRegionalScan}
            >
              {showRegionalScan ? 'Hide regional scan' : 'Show regional scan'}
            </button>
```

- [ ] **Step 6: Lint**

Run: `cd frontend && npm run lint`
Expected: no new errors from `RegionalScanLayer.jsx`, `client.js`, `OverviewPage.jsx`, or `RiskMap.jsx`.

- [ ] **Step 7: Build**

Run: `cd frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 8: Manual dev-server check**

Run: `cd frontend && npm run dev` (with the backend running via `./scripts/dev.sh` or `cd backend && source venv/bin/activate && uvicorn src.main:app --reload` in another terminal). Open the app, toggle "Show regional scan." Before any scan has run (fresh DB), the toggle should render nothing (no error) — `data?.run` is `null`, `RegionalScanLayer` returns `null`. This confirms the empty-state path from Task 7's endpoint test actually renders cleanly in the browser, not just in the API response.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/client.js frontend/src/components/RegionalScanLayer.jsx \
        frontend/src/components/RiskMap.jsx frontend/src/pages/OverviewPage.jsx
git commit -m "feat(frontend): add regional-scan map layer, toggleable on the overview map"
```

---

## Self-Review

**Spec coverage:**
- §1 Grid generation → Task 2.
- §2 Per-point extraction (reuses `detect()`) → Task 4.
- §3 Threshold tiers (reuses `config.yaml`) → Task 4 (`_tier`).
- §4 Clustering → Task 3.
- §5 Trigger model (poll + cooldown) → Task 5.
- §6 Data model → Task 1.
- §7 `GET /regional-scan` → Task 7.
- §8 Scheduler / job architecture + CLI script → Task 6.
- §9 Error handling → Task 4 (`run_scan`'s GEEAuthError-abort vs. per-point-catch split).
- §10 Frontend → Task 8.
- §11 Testing → every task's own test step (grid/clustering pure-function unit tests; scan/trigger/endpoint DB-backed tests with mocked `bridge.detect`/no live GEE).
- §12 Deferred (per-tile scanning) → deliberately not implemented; nothing in Task 1's schema carries tile/provenance/freshness-range fields.

**Placeholder scan:** none — every step above contains complete, runnable code, not a description of what to write.

**Type consistency:** `generate_scan_grid` → `{lat, lng, row_idx, col_idx, point_id}` (Task 2) is exactly what `run_scan` (Task 4) iterates and exactly what `cluster_points` (Task 3) expects as input shape (plus `spatial_anomaly_z`/`threshold_tier` added by `run_scan` before clustering). `run_scan`'s signature (`db, target_date, grid_spacing_km, newest_scene_date=None`) matches both call sites: `trigger.poll_and_maybe_scan` (Task 5) and `scripts/run_regional_scan.py` (Task 6). `RegionalScanRun`/`Point`/`Cluster` field names (Task 1) match every read/write site in `scan.py` (Task 4), `trigger.py` (Task 5), and `routers/regional_scan.py` (Task 7) exactly.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-31-regional-bloom-scan-implementation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
