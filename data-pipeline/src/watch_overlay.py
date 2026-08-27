"""NDCI watch-overlay temporal helpers and Earth Engine tile builder.

Data sources: Sentinel-2 L2A surface reflectance and JRC Global Surface
Water occurrence, both via Google Earth Engine. Limitations: the resulting
current anomaly screen is not bloom confirmation or a forecast; optical
coastal-water signals can include sediment, residual cloud, and other
non-bloom effects.
"""

from datetime import date, timedelta
from datetime import datetime, timezone
from typing import Any

import ee
import numpy as np

from .auth import initialize_ee
from .study_area import upper_gulf_scan_ee_polygon

NUMERICAL_STD_EPSILON = 1e-6
NDCI_DENOMINATOR_EPSILON = 1e-6
WATCH_WATER_MASK_LABEL = "gulf_connected_historical_surface_water"
WATCH_CAVEAT = (
    "NDCI watch signal, not bloom confirmation or a forecast. Sediment, optically "
    "complex coastal water, and residual cloud may produce a signal. The 10 m output "
    "grid uses Sentinel-2 B5 with 20 m effective source resolution. The water mask "
    "uses Gulf-connected historical surface water and does not measure salinity."
)


class NoWatchOverlayImageryError(RuntimeError):
    """No Sentinel-2 scene exists in the configured current source window."""


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


def trend_window(target_date: str, window_days: int) -> tuple[str, str]:
    """Return the inclusive UTC trend window and its exclusive end date."""
    target = date.fromisoformat(target_date)
    return (
        (target - timedelta(days=window_days - 1)).isoformat(),
        (target + timedelta(days=1)).isoformat(),
    )


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


def _build_gulf_connected_water_mask(
    region, *, water_occurrence_pct: float, gulf_seed_points: list[list[float]]
):
    """Return persistent water connected to supplied upper-Gulf seed points."""
    occurrence = (
        ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").clip(region)
    )
    persistent_water = occurrence.gte(water_occurrence_pct).clip(region)
    # Deriving cost from JRC water retains its native grid. The painted seeds
    # have no matching native grid, so align them before connectivity tracing.
    water_cost = persistent_water.selfMask().clip(region)
    seed_features = [
        ee.Feature(ee.Geometry.Point([lng, lat])) for lat, lng in gulf_seed_points
    ]
    seeds = (
        ee.Image(0)
        .byte()
        .paint(ee.FeatureCollection(seed_features), 1)
        .selfMask()
        .clip(region)
        .reproject(crs=water_cost.projection())
    )
    # 500 km exceeds the scan polygon's longest span: it is a traversal
    # ceiling for connectivity, not a bloom or anomaly threshold.
    reached = water_cost.cumulativeCost(
        source=seeds,
        maxDistance=500_000,
        geodeticDistance=True,
    ).clip(region)
    return (
        persistent_water.updateMask(reached.mask())
        .rename("gulf_connected_water")
        .clip(region)
    )


def _usable_water_pixel_mask(image, connected_water):
    """Keep connected water with Sentinel water classification and clear QA60."""
    scl_water = image.select("SCL").eq(6)
    qa60 = image.select("QA60")
    qa_clear = qa60.bitwiseAnd(1 << 10).eq(0).And(
        qa60.bitwiseAnd(1 << 11).eq(0)
    )
    source_valid = image.select(["B2", "B3", "B4", "B5", "B6"]).mask().reduce(
        ee.Reducer.min()
    )
    return connected_water.And(scl_water).And(qa_clear).And(source_valid)


def _masked_ndci_image(image, *, region, water_mask, output_scale_m: int):
    """Build one usable-water NDCI image with diagnostic source bands."""
    reflectance = image.select(["B2", "B3", "B4", "B5", "B6"]).multiply(0.0001)
    b2 = reflectance.select("B2")
    b3 = reflectance.select("B3")
    b4 = reflectance.select("B4")
    b5 = (
        reflectance.select("B5")
        .resample("bilinear")
        .reproject(crs=b4.projection(), scale=output_scale_m)
    )
    b6 = reflectance.select("B6")
    denominator = b5.add(b4)
    usable_water = _usable_water_pixel_mask(image, water_mask)
    valid_ndci = usable_water.And(denominator.abs().gt(NDCI_DENOMINATOR_EPSILON))
    ndci = b5.subtract(b4).divide(denominator).rename("ndci").updateMask(valid_ndci)
    ndci = ndci.clip(region)
    ndci = ndci.setDefaultProjection(b4.projection().atScale(output_scale_m))
    acquired = ee.Image.constant(ee.Number(image.get("system:time_start")))
    acquired = acquired.rename("acquired_ms").updateMask(ndci.mask())
    acquired_day = ee.Image.constant(
        ee.Number(image.get("system:time_start")).divide(86_400_000).floor()
    )
    acquired_day = acquired_day.rename("acquired_day").updateMask(ndci.mask())
    diagnostics = b2.addBands(b3).addBands(b6).updateMask(valid_ndci).clip(region)
    return (
        ndci.addBands(acquired)
        .addBands(acquired_day)
        .addBands(diagnostics)
        .copyProperties(image, ["system:time_start"])
    )


def _daily_ndci_collection(collection, start: str, end: str):
    """Median valid scenes per UTC calendar date with elapsed-day predictors."""
    day_count = (date.fromisoformat(end) - date.fromisoformat(start)).days
    images = []
    for offset in range(day_count):
        day = date.fromisoformat(start) + timedelta(days=offset)
        next_day = day + timedelta(days=1)
        daily = collection.filterDate(day.isoformat(), next_day.isoformat())
        daily_ndci = daily.select("ndci").median().rename("ndci")
        empty_ndci = ee.Image.constant(0).rename("ndci").updateMask(ee.Image.constant(0))
        daily_ndci = ee.Image(
            ee.Algorithms.If(daily.size().gt(0), daily_ndci, empty_ndci)
        )
        elapsed_days = (
            ee.Image.constant(offset)
            .rename("elapsed_days")
            .toFloat()
            .updateMask(daily_ndci.mask())
        )
        images.append(
            daily_ndci.addBands(elapsed_days).set("observation_date", day.isoformat())
        )
    return ee.ImageCollection.fromImages(images)


def _build_trend_image(daily_collection, *, min_observations: int):
    """Fit daily NDCI slope where enough distinct valid UTC dates exist."""
    count = daily_collection.select("ndci").count().rename("trend_observation_count")
    fit = daily_collection.select(["elapsed_days", "ndci"]).reduce(ee.Reducer.linearFit())
    slope = fit.select("scale").rename("ndci_slope_per_day")
    return slope.updateMask(count.gte(min_observations)).addBands(count)


def _build_masked_ndci_collection(
    start: str, end: str, *, region, water_mask, output_scale_m: int
):
    """Fetch one date window through the shared SCL/water/NDCI preprocessing."""
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


def _build_source_collections(
    *,
    current_window: tuple[str, str],
    baseline_windows: list[tuple[str, str]],
    region,
    water_mask,
    output_scale_m: int,
    collection_builder=_build_masked_ndci_collection,
):
    """Use one injected preprocessing builder for current and baseline sources."""
    current = collection_builder(
        *current_window,
        region=region,
        water_mask=water_mask,
        output_scale_m=output_scale_m,
    )
    if not baseline_windows:
        raise ValueError("baseline_windows must contain at least one seasonal window")
    first_start, first_end = baseline_windows[0]
    baseline = collection_builder(
        first_start,
        first_end,
        region=region,
        water_mask=water_mask,
        output_scale_m=output_scale_m,
    )
    for start, end in baseline_windows[1:]:
        baseline = baseline.merge(
            collection_builder(
                start,
                end,
                region=region,
                water_mask=water_mask,
                output_scale_m=output_scale_m,
            )
        )
    return current, baseline


def _build_watch_image(
    *,
    current,
    baseline,
    region,
    threshold_z: float,
    min_baseline_observations: int,
    color: str,
):
    """Return the thresholded current NDCI anomaly image, styled for tiles."""
    latest = current.qualityMosaic("acquired_ms").select("ndci")
    stats = baseline.select("ndci").reduce(
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )
    mean = stats.select("ndci_mean")
    std = stats.select("ndci_stdDev")
    count = stats.select("ndci_count")
    valid_baseline = count.gte(min_baseline_observations).And(
        std.gt(NUMERICAL_STD_EPSILON)
    )
    z = latest.subtract(mean).divide(std).rename("ndci_z").updateMask(valid_baseline)
    watch = z.updateMask(z.gte(threshold_z)).clip(region)
    return watch.visualize(
        min=threshold_z,
        max=threshold_z + 0.01,
        palette=[color.lstrip("#")],
    )


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
    """Build an upper-Gulf current NDCI anomaly tile and run metadata."""
    initialize_ee()

    target = date.fromisoformat(target_date)
    current_start = target - timedelta(days=latest_window_days - 1)
    current_end_exclusive = target + timedelta(days=1)
    current_window = (current_start.isoformat(), current_end_exclusive.isoformat())
    baseline_windows = seasonal_windows(
        target_date,
        baseline_years=baseline_years,
        window_days=seasonal_window_days,
    )
    region = upper_gulf_scan_ee_polygon()
    water_mask = _build_gulf_connected_water_mask(
        region,
        water_occurrence_pct=water_occurrence_pct,
        gulf_seed_points=gulf_seed_points,
    )
    current, baseline = _build_source_collections(
        current_window=current_window,
        baseline_windows=baseline_windows,
        region=region,
        water_mask=water_mask,
        output_scale_m=output_scale_m,
    )
    if current.size().getInfo() == 0:
        raise NoWatchOverlayImageryError(
            "No Sentinel-2 scene exists in the configured current source window."
        )

    newest_scene_ms = current.aggregate_max("system:time_start").getInfo()
    newest_scene_date = datetime.fromtimestamp(
        newest_scene_ms / 1000, tz=timezone.utc
    ).date().isoformat()
    styled = _build_watch_image(
        current=current,
        baseline=baseline,
        region=region,
        threshold_z=threshold_z,
        min_baseline_observations=min_baseline_observations,
        color=color,
    )
    map_info = styled.getMapId({})
    return {
        "status": "ok",
        "tile_url": map_info["tile_fetcher"].url_format,
        "map_id": map_info["mapid"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_date": target_date,
        "source_window_start": current_start.isoformat(),
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
