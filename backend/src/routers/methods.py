"""
`GET /methods` -- what the dashboard's Methods page shows, read from the
code that computes it, so every formula, constant and gate state on that
page is the one in force.

Data sources, all read for each response (nothing is cached here):
  * detection/src/indices.py, through the bridge: `INDEX_METADATA` (name,
    formula, bands, role, note), the band wavelength / resolution tables and
    `SCALE_FACTOR`; each worked example is the registered `INDEX_FUNCTIONS`
    entry applied to `methods_info.WORKED_EXAMPLE_BANDS`;
  * src/raster_scan/render.py `BAND_DOMAINS` -- the display domain the
    overlay is painted over (NDCI only; the others have none);
  * data-pipeline: `preprocessing_params()` (collection, bands, cloud classes,
    cloud-fraction and water-occurrence thresholds),
    `default_max_scene_age_days()`, `scene_thresholds()` and the MODIS
    product constants;
  * src/scientific_status.py: `baseline_status()`, `risk_evaluation_active()`,
    `signal_anomaly_active()`; detection/src/signal_anomaly.py's floors and
    robust-z constants; detection/src/baseline.py's season rule;
  * src/config.py poll / minimum-scan intervals, src/raster_scan/trigger.py
    `SETTLE_HOURS`;
  * src/methods_info.py: the two references, copied from LIMITATIONS.md, the
    revisit figure and the worked-example sample bands.

No Earth Engine call and no database read. The handler is a plain `def`, so
FastAPI runs it in its threadpool: in test mode `baseline_status()` stats and
may parse the baseline manifest, which is blocking file I/O.

Limitations: this describes methods, not results. A worked example is
arithmetic on illustrative band values, not an observation. `baseline` and
`gates.signal_anomaly_active` are two reads of the same on-disk artefact; one
replaced between those two reads could make them disagree for one response.
Nothing here is a bloom detection, a risk level or a forecast.
"""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Request

from .. import _detection as bridge
from .. import config as backend_config
from .. import methods_info, scientific_status
from ..raster_scan import render, trigger
from ..schemas import (
    DisplayDomain,
    IndexWorkedExample,
    LatestScenePolicy,
    MethodsBaselineStatus,
    MethodsGates,
    MethodsIndex,
    MethodsModis,
    MethodsReference,
    MethodsResponse,
    MethodsSentinel2,
    SeasonWindow,
    SignalAnomalyFloors,
    SignalAnomalyStatistic,
)
from ..site_anomaly import disclaimer_for

logger = logging.getLogger("backend.routers.methods")

router = APIRouter(tags=["methods"])


def _finite_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _indices() -> list[MethodsIndex]:
    """One entry per registered index, in registry order."""
    sample = dict(methods_info.WORKED_EXAMPLE_BANDS)
    entries = []
    for key, function in bridge.INDEX_FUNCTIONS.items():
        meta = bridge.INDEX_METADATA[key]
        raster_band = methods_info.RASTER_BAND_FOR_INDEX[key]
        domain = render.BAND_DOMAINS.get(raster_band)
        entries.append(MethodsIndex(
            key=key,
            name=meta["name"],
            formula=meta["formula"],
            bands=list(meta["bands"]),
            wavelengths_nm={
                band: bridge.BAND_WAVELENGTHS_NM[band]
                for band in meta["bands"]
                if band in bridge.BAND_WAVELENGTHS_NM
            },
            role=meta["role"],
            note=meta["note"],
            raster_band=raster_band,
            display_domain=None if domain is None else DisplayDomain(min=domain[0], max=domain[1]),
            worked_example=IndexWorkedExample(
                bands=sample,
                # A copy, so the function can never alter the sample shown.
                value=_finite_or_none(function(dict(sample))),
                note=methods_info.WORKED_EXAMPLE_NOTE,
            ),
        ))
    return entries


def _sentinel2() -> MethodsSentinel2:
    params = bridge.preprocessing_params()
    return MethodsSentinel2(
        collection=params["collection"],
        bands=list(params["bands"]),
        native_resolution_m=dict(bridge.BAND_NATIVE_RESOLUTION_M),
        wavelengths_nm=dict(bridge.BAND_WAVELENGTHS_NM),
        wavelengths_note=methods_info.WAVELENGTHS_NOTE,
        revisit_days=methods_info.SENTINEL2_REVISIT_DAYS,
        scale_factor=bridge.INDEX_SCALE_FACTOR,
        max_scene_age_days=bridge.default_max_scene_age_days(),
        max_cloud_fraction=params["max_cloud_fraction"],
        cloud_mask_scl_classes=list(params["cloud_classes"]),
        min_water_occurrence_pct=params["min_water_occurrence_pct"],
    )


def _modis() -> MethodsModis:
    return MethodsModis(
        collection=bridge.MODIS_COLLECTION_ID,
        bands=[bridge.MODIS_CHLOR_A_BAND, bridge.MODIS_SST_BAND],
        grid_resolution_m=bridge.MODIS_GRID_SCALE_M,
        record_start=bridge.MODIS_ARCHIVE_START,
        note=methods_info.MODIS_NOTE,
    )


def _gates() -> MethodsGates:
    return MethodsGates(
        risk_evaluation_active=scientific_status.risk_evaluation_active(),
        signal_anomaly_active=scientific_status.signal_anomaly_active(),
        signal_anomaly_floors=SignalAnomalyFloors(
            min_independent_dates=bridge.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES,
            max_observation_age_days=bridge.SIGNAL_ANOMALY_MAX_OBSERVATION_AGE_DAYS,
        ),
        signal_anomaly_statistic=SignalAnomalyStatistic(
            formula=(
                "robust_z = (current NDCI - median NDCI) / "
                f"({bridge.SIGNAL_ANOMALY_MAD_SCALE} * MAD)"
            ),
            mad_scale=bridge.SIGNAL_ANOMALY_MAD_SCALE,
            watch_at_z=bridge.SIGNAL_ANOMALY_WATCH_AT_Z,
            high_at_z=bridge.SIGNAL_ANOMALY_HIGH_AT_Z,
            note=methods_info.SIGNAL_ANOMALY_NOTE,
        ),
    )


def _scene_thresholds() -> tuple[float | None, int | None]:
    """The scene-screen thresholds, or both null on an invalid environment value.

    `scene_thresholds()` raises rather than substitute a default; a guessed
    threshold would misstate the criterion (same rule as /raster-scan).
    """
    try:
        return bridge.scene_thresholds()
    except ValueError as exc:
        logger.warning("scene thresholds unavailable for /methods: %s", exc)
        return None, None


def _latest_scene_policy() -> LatestScenePolicy:
    max_cloud_fraction, min_water_pixels = _scene_thresholds()
    return LatestScenePolicy(
        max_cloud_fraction=max_cloud_fraction,
        min_water_pixels=min_water_pixels,
        poll_interval_hours=backend_config.RASTER_SCAN_POLL_INTERVAL_HOURS,
        min_scan_interval_hours=backend_config.RASTER_SCAN_MIN_INTERVAL_HOURS,
        settle_hours=trigger.SETTLE_HOURS,
    )


def _season_windows() -> list[SeasonWindow]:
    logic = bridge.baseline_logic
    return [
        SeasonWindow(month=month, key=logic.season_key(month), months=list(logic.season_months(month)))
        for month in range(1, 13)
    ]


@router.get("/methods", response_model=MethodsResponse)
def get_methods(request: Request) -> MethodsResponse:
    """Formulas, sensors, thresholds, gate states and references in force.

    Read-only and offline: no Earth Engine call, no database read. Each
    worked example is computed for this response by the same index function
    every reading uses.
    """
    status = scientific_status.baseline_status()
    return MethodsResponse(
        api_version=request.app.version,
        indices=_indices(),
        sentinel2=_sentinel2(),
        modis=_modis(),
        gates=_gates(),
        latest_scene_policy=_latest_scene_policy(),
        season_rule=bridge.baseline_logic.SEASON_RULE,
        season_windows=_season_windows(),
        baseline=MethodsBaselineStatus(**status),
        references=[MethodsReference(**reference) for reference in methods_info.REFERENCES],
        disclaimer=disclaimer_for(status),
    )
