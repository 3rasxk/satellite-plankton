"""NDCI watch-overlay temporal helpers and Earth Engine tile builder.

Data sources: Sentinel-2 L2A surface reflectance, JRC Global Surface Water,
and MODIS-Aqua L3 sea-surface temperature via Google Earth Engine.
Limitations: the resulting anomaly screen is not bloom confirmation or a
forecast; optical coastal-water signals can include sediment, residual cloud,
and other non-bloom effects.
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
MODIS_SST_COLLECTION_ID = "NASA/OCEANDATA/MODIS-Aqua/L3SMI"
MODIS_SST_ARCHIVE_START_DATE = "2002-07-04"
SITE_SAMPLE_NODATA = -9999
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


def sst_seasonal_windows(
    target_date: str, *, archive_start_date: str, window_days: int
) -> list[tuple[str, str]]:
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
            windows.append(
                (max(start, archive_start).isoformat(), end_exclusive.isoformat())
            )
    return windows


def _utc_date_from_millis(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()


def _nullable_sample_value(properties: dict, name: str):
    value = properties.get(name)
    return None if value == SITE_SAMPLE_NODATA else value


def _parse_site_alerts(sampled, *, level_definitions: list[dict]) -> list[dict]:
    """Return ordered alert records for sampled class codes 1 through 3."""
    levels_by_class = {
        definition["class_code"]: definition for definition in level_definitions
    }
    alerts = []
    for input_order, feature in enumerate(sampled):
        properties = feature.get("properties", {})
        raw_level = properties.get("level_code")
        try:
            level_code = int(raw_level)
        except (TypeError, ValueError):
            continue
        definition = levels_by_class.get(level_code)
        if definition is None:
            continue
        slope = _nullable_sample_value(properties, "ndci_slope_per_day")
        current_sst = _nullable_sample_value(properties, "current_sst")
        seasonal_sst = _nullable_sample_value(properties, "seasonal_sst")
        alerts.append(
            (
                properties.get("_site_order", input_order),
                {
                    "site_id": properties.get("site_id"),
                    "name": properties.get("name"),
                    "lat": properties.get("lat"),
                    "lng": properties.get("lng"),
                    "level": definition["code"],
                    "label_th": definition["label_th"],
                    "color": definition["color"],
                    "ndci_z": _nullable_sample_value(properties, "ndci_z"),
                    "latest_scene_date": _utc_date_from_millis(
                        _nullable_sample_value(properties, "latest_acquired_ms")
                    ),
                    "trend_slope_per_day": slope,
                    "trend_observations": _nullable_sample_value(
                        properties, "trend_observation_count"
                    ),
                    "trend_rising": slope is not None and slope > 0,
                    "current_sst": current_sst,
                    "seasonal_sst": seasonal_sst,
                    "sst_date": _utc_date_from_millis(
                        _nullable_sample_value(properties, "sst_acquired_ms")
                    ),
                    "sst_above_normal": current_sst is not None
                    and seasonal_sst is not None
                    and current_sst > seasonal_sst,
                },
            )
        )
    return [alert for _, alert in sorted(alerts, key=lambda item: item[0])]


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


def _build_current_anomaly(
    *,
    current,
    baseline,
    min_baseline_observations: int,
):
    """Return current NDCI z-score and its per-pixel acquisition timestamp."""
    latest = current.qualityMosaic("acquired_ms")
    latest_ndci = latest.select("ndci")
    latest_acquired_ms = latest.select("acquired_ms").rename("latest_acquired_ms")
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
    z = (
        latest_ndci.subtract(mean)
        .divide(std)
        .rename("ndci_z")
        .updateMask(valid_baseline)
    )
    return z, latest_acquired_ms.updateMask(z.mask())


def _build_sst_images(
    target_date: str,
    *,
    region,
    search_window_days: int,
    climatology_window_days: int,
):
    """Build nearest-pixel current SST and all-prior-year seasonal SST."""
    target = date.fromisoformat(target_date)
    target_ms = int(
        datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc).timestamp()
        * 1000
    )
    current_start = target - timedelta(days=search_window_days)
    current_end_exclusive = target + timedelta(days=search_window_days + 1)
    source = ee.ImageCollection(MODIS_SST_COLLECTION_ID).filterBounds(region)
    current_source = source.filterDate(
        current_start.isoformat(), current_end_exclusive.isoformat()
    )

    def add_quality(image):
        sst = image.select("sst").rename("current_sst").clip(region)
        acquired_ms = ee.Number(image.get("system:time_start"))
        distance_days = acquired_ms.subtract(target_ms).abs().divide(86_400_000)
        later_tie_breaker = acquired_ms.gte(target_ms).multiply(0.1)
        quality = (
            ee.Image.constant(
                distance_days.multiply(-1).add(later_tie_breaker)
            )
            .rename("sst_quality")
            .updateMask(sst.mask())
        )
        acquired = (
            ee.Image.constant(acquired_ms)
            .rename("sst_acquired_ms")
            .updateMask(sst.mask())
        )
        return sst.addBands(acquired).addBands(quality)

    current_mosaic = current_source.map(add_quality).qualityMosaic("sst_quality")
    current_sst = (
        current_mosaic.select("current_sst")
        .clip(region)
        .set(
            "newest_sst_scene_ms",
            current_source.aggregate_max("system:time_start"),
        )
    )
    sst_acquired_ms = current_mosaic.select("sst_acquired_ms").clip(region)

    windows = sst_seasonal_windows(
        target_date,
        archive_start_date=MODIS_SST_ARCHIVE_START_DATE,
        window_days=climatology_window_days,
    )
    if not windows:
        raise ValueError("target_date must be later than the MODIS SST archive start")
    first_start, first_end = windows[0]
    seasonal_collection = source.filterDate(first_start, first_end).select("sst")
    for start, end in windows[1:]:
        seasonal_collection = seasonal_collection.merge(
            source.filterDate(start, end).select("sst")
        )
    seasonal_sst_count = seasonal_collection.count().rename("seasonal_sst_count")
    seasonal_sst = (
        seasonal_collection.mean()
        .rename("seasonal_sst")
        .clip(region)
        .updateMask(seasonal_sst_count.gt(0))
    )
    return current_sst, sst_acquired_ms, seasonal_sst, seasonal_sst_count


def _build_classification_image(
    *,
    z,
    latest_acquired_ms,
    trend,
    current_sst,
    seasonal_sst,
    sst_acquired_ms,
    elevated_z: float,
    warning_z: float,
    min_trend_observations: int,
    region,
):
    """Build auditable level codes with all supporting evidence bands."""
    slope = trend.select("ndci_slope_per_day")
    trend_count = trend.select("trend_observation_count")
    elevated = z.gte(elevated_z)
    rising = trend_count.gte(min_trend_observations).And(slope.gt(0))
    sst_above = current_sst.gt(seasonal_sst)

    level = ee.Image.constant(1).rename("level_code").updateMask(elevated)
    level = level.where(elevated.And(rising), 2)
    level = level.where(z.gte(warning_z).And(rising).And(sst_above), 3)
    return (
        level.addBands(z.unmask(SITE_SAMPLE_NODATA))
        .addBands(latest_acquired_ms.unmask(SITE_SAMPLE_NODATA))
        .addBands(slope.unmask(SITE_SAMPLE_NODATA))
        .addBands(trend_count.unmask(SITE_SAMPLE_NODATA))
        .addBands(current_sst.unmask(SITE_SAMPLE_NODATA))
        .addBands(seasonal_sst.unmask(SITE_SAMPLE_NODATA))
        .addBands(sst_acquired_ms.unmask(SITE_SAMPLE_NODATA))
        .clip(region)
    )


def _sample_site_alerts(
    analysis_image,
    *,
    monitoring_sites: list[dict],
    level_definitions: list[dict],
    scale_m: int,
) -> list[dict]:
    """Sample alert evidence from the same final image used for tile styling."""
    features = []
    for site_order, site in enumerate(monitoring_sites):
        properties = {
            "_site_order": site_order,
            "site_id": site["site_id"],
            "name": site["name"],
            "lat": site["lat"],
            "lng": site["lng"],
        }
        features.append(
            ee.Feature(
                ee.Geometry.Point([site["lng"], site["lat"]]), properties
            )
        )
    sampled = analysis_image.sampleRegions(
        collection=ee.FeatureCollection(features),
        scale=scale_m,
        geometries=False,
    )
    return _parse_site_alerts(
        sampled.getInfo().get("features", []),
        level_definitions=level_definitions,
    )


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
    """Build a three-tier upper-Gulf NDCI/SST watch tile and site alerts."""
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
    z, latest_acquired_ms = _build_current_anomaly(
        current=current,
        baseline=baseline,
        min_baseline_observations=min_baseline_observations,
    )
    trend_start, trend_end = trend_window(target_date, trend_window_days)
    trend_source = _build_masked_ndci_collection(
        trend_start,
        trend_end,
        region=region,
        water_mask=water_mask,
        output_scale_m=output_scale_m,
    )
    daily_trend_source = _daily_ndci_collection(
        trend_source, trend_start, trend_end
    )
    trend = _build_trend_image(
        daily_trend_source, min_observations=min_trend_observations
    )
    current_sst, sst_acquired_ms, seasonal_sst, _seasonal_sst_count = (
        _build_sst_images(
            target_date,
            region=region,
            search_window_days=sst_search_window_days,
            climatology_window_days=sst_climatology_window_days,
        )
    )
    newest_sst_scene_date = _utc_date_from_millis(
        current_sst.get("newest_sst_scene_ms").getInfo()
    )
    analysis = _build_classification_image(
        z=z,
        latest_acquired_ms=latest_acquired_ms,
        trend=trend,
        current_sst=current_sst,
        seasonal_sst=seasonal_sst,
        sst_acquired_ms=sst_acquired_ms,
        elevated_z=threshold_z,
        warning_z=warning_threshold_z,
        min_trend_observations=min_trend_observations,
        region=region,
    )
    level_definitions = [
        {
            "code": "elevated",
            "class_code": 1,
            "label_th": "เริ่มผิดปกติ",
            "color": level_colors["elevated"],
            "min_z": threshold_z,
            "requires_rising_trend": False,
            "requires_sst_above_normal": False,
        },
        {
            "code": "watch",
            "class_code": 2,
            "label_th": "เฝ้าระวัง",
            "color": level_colors["watch"],
            "min_z": threshold_z,
            "requires_rising_trend": True,
            "requires_sst_above_normal": False,
        },
        {
            "code": "warning",
            "class_code": 3,
            "label_th": "เตือนภัย",
            "color": level_colors["warning"],
            "min_z": warning_threshold_z,
            "requires_rising_trend": True,
            "requires_sst_above_normal": True,
        },
    ]
    site_alerts = _sample_site_alerts(
        analysis,
        monitoring_sites=monitoring_sites,
        level_definitions=level_definitions,
        scale_m=effective_resolution_m,
    )
    analysis_metadata = {
        "version": 2,
        "levels": level_definitions,
        "trend": {
            "window_days": trend_window_days,
            "min_distinct_dates": min_trend_observations,
            "slope_units": "ndci_per_day",
            "rising_rule": "slope_per_day > 0",
        },
        "sst": {
            "collection_id": MODIS_SST_COLLECTION_ID,
            "search_window_days": sst_search_window_days,
            "climatology_window_days": sst_climatology_window_days,
            "resolution_m": sst_resolution_m,
            "above_normal_rule": "current_sst > seasonal_sst",
        },
        "masks": {
            "water_mask": WATCH_WATER_MASK_LABEL,
            "water_occurrence_pct": water_occurrence_pct,
            "scl_water_class": 6,
            "qa60_cloud_bit": 10,
            "qa60_cirrus_bit": 11,
        },
        "resolutions": {
            "output_grid_m": output_scale_m,
            "ndci_m": effective_resolution_m,
            "trend_m": effective_resolution_m,
            "sst_m": sst_resolution_m,
        },
        "newest_sentinel_scene_date": newest_scene_date,
        "newest_sst_scene_date": newest_sst_scene_date,
        "mosaic_caveat": "Sentinel-2 and SST mosaic pixels may come from different dates.",
        "site_alerts": site_alerts,
    }
    styled = analysis.select("level_code").visualize(
        min=1,
        max=3,
        palette=[
            level_colors["elevated"].lstrip("#"),
            level_colors["watch"].lstrip("#"),
            level_colors["warning"].lstrip("#"),
        ],
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
        "color": level_colors["watch"],
        "caveat": WATCH_CAVEAT,
        "analysis_metadata": analysis_metadata,
    }
