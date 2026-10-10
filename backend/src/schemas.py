"""
Pydantic response models -- every model that reaches an HTTP response
carries `disclaimer`, enforced by the schema (visible in /docs and
openapi.json), not left to convention.

Detection (`detect()`) and prediction (`risk_level()`) fields are kept in
separate nested objects everywhere (`DetectionBlock` vs. the prediction-
specific fields around it) -- mirrors detection/src/prediction.py's own
separation (CLAUDE.md truth boundary / .claude/agents/backend-api.md
"Non-negotiable rules": never merge them into one score).
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

DISCLAIMER_TEXT = (
    "Satellite index values describe water colour at pixel resolution. "
    "Small or scattered blooms may not be visible. Sentinel-2 anomaly "
    "detection is not computed — no valid baseline exists. Index values "
    "alone establish neither bloom presence nor absence."
)

# The variant EVERY response carries instead of DISCLAIMER_TEXT while
# BASELINE_MODE=test AND a TEST baseline is valid (src/site_anomaly.py
# disclaimer_for) -- whether or not that response itself holds an anomaly.
# DISCLAIMER_TEXT's "anomaly detection is not computed" is false then; this
# says what is computed (at a monitoring site or a raster cell) and what it
# is not. The first two sentences are DISCLAIMER_TEXT's own.
DISCLAIMER_TEXT_TEST_BASELINE = (
    "Satellite index values describe water colour at pixel resolution. "
    "Small or scattered blooms may not be visible. TEST baseline mode: a "
    "Sentinel-2 NDCI reading, at a monitoring site or at a raster cell, may be "
    "compared with that same location's own earlier record for the same season. "
    "Any resulting anomaly is provisional and uncalibrated, has never been "
    "checked against recorded bloom events, and is a statistical statement "
    "only — not a bloom detection, a species identification, a risk level or a "
    "forecast. Index values alone establish neither bloom presence nor absence."
)

_last_disclaimer_warning: str | None = None


def disclaimer_in_force() -> str:
    """The truth-boundary text for a response built now; never raises.

    ``DisclaimerMixin.disclaimer``'s default factory, so a model built per
    request without an explicit ``disclaimer=`` carries the text for the TEST
    baseline in force: ``site_anomaly.disclaimer_for(baseline_status())`` --
    ``DISCLAIMER_TEXT_TEST_BASELINE`` while BASELINE_MODE=test AND the
    baseline is valid, else ``DISCLAIMER_TEXT``. A route that already holds
    one resolution passes ``disclaimer=disclaimer_for(status)`` from it
    instead, so its baseline block and its disclaimer cannot disagree.

    Cost per call: mode off -- one attribute read, no file touched. Test
    mode -- one ``baseline_status()``: the stats and directory listing
    ``baseline_store`` already does to find the newest artefact, a JSON
    parse only when a file changed (cached on mtime/size/inode), the
    manifest checks and a copy of the manifest; the history rows are never
    copied.

    The imports are local because ``site_anomaly`` imports this module. Any
    failure (the never-raising ``baseline_status`` replaced or broken) gives
    ``DISCLAIMER_TEXT``, the answer ``disclaimer_for`` gives a baseline that
    cannot be read; logged once per distinct failure.
    """
    global _last_disclaimer_warning
    try:
        from . import scientific_status, site_anomaly

        text = site_anomaly.disclaimer_for(scientific_status.baseline_status())
    except Exception as exc:  # noqa: BLE001 -- a response must never fail over its caveat
        message = f"disclaimer: baseline status unavailable ({type(exc).__name__}: {exc}); standard text used"
        if message != _last_disclaimer_warning:
            logger.warning(message, exc_info=True)
            _last_disclaimer_warning = message
        return DISCLAIMER_TEXT
    _last_disclaimer_warning = None
    return text


class DisclaimerMixin(BaseModel):
    disclaimer: str = Field(
        default_factory=disclaimer_in_force,
        description="Truth-boundary caveat. Present on every response — satellite-pixel "
        "resolution, small/scattered blooms may be missed, and Sentinel-2 "
        "index values alone cannot establish bloom presence or absence. Which text "
        "depends on the TEST baseline in force when the response is built, and is "
        "the same on every endpoint: while BASELINE_MODE=test and a TEST baseline is "
        "valid, every response carries the TEST-baseline variant (any site or cell "
        "anomaly is provisional, uncalibrated and statistical only), whether or not "
        "that response holds an anomaly; otherwise (mode off, or a refused baseline) "
        "every response carries the standard text, which says no anomaly is computed.",
        examples=[DISCLAIMER_TEXT, DISCLAIMER_TEXT_TEST_BASELINE],
    )


# --------------------------------------------------------------------------
# TEST baseline description (shared by /risk-map, /summary, /detect)
# --------------------------------------------------------------------------


class BaselineInfo(BaseModel):
    """The TEST seasonal baseline in force -- src/scientific_status.py's
    ``baseline_status()``, one key per field. Present on a response only while
    BASELINE_MODE is ``test``; null otherwise.

    A TEST baseline is provisional and uncalibrated: any anomaly it supports is
    a statistical statement about one site's NDCI against that site's own
    earlier record in the same seasonal window. It is not a bloom detection,
    not a species identification and not a forecast.
    """

    mode: str = Field(description="Always 'test' when this block is present.")
    valid: bool = Field(
        description="False when test mode is on but no artefact may be used; then "
        "`reason` says why and every anomaly field stays null."
    )
    kind: str = Field(description="'test': provisional, never checked against recorded bloom events.")
    version: str | None = Field(
        default=None, description="Baseline version. A cached site anomaly is shown only "
        "when it was computed against exactly this version."
    )
    built_at: str | None = None
    history_start: str | None = Field(default=None, description="First acquisition date in the history.")
    history_end: str | None = Field(default=None, description="Last acquisition date in the history.")
    season_rule: str | None = Field(
        default=None, description="Which history months an observation is compared with."
    )
    min_independent_dates: int | None = Field(
        default=None, description="Dates behind one robust z in the weakest seasonal window "
        "of the weakest site (the declared minimum)."
    )
    median_independent_dates: int | float | None = Field(
        default=None, description="Median over sites of the dates in each site's weakest "
        "seasonal window -- not the length of the whole record."
    )
    min_season_dates_by_location: dict[str, int] | None = Field(
        default=None, description="Per site: dates in its weakest seasonal window."
    )
    preprocessing_signature: str | None = Field(
        default=None, description="Hash of the preprocessing the history was made with; "
        "a live pipeline with another signature makes the baseline unusable."
    )
    base_rates: dict | None = Field(
        default=None, description="How often the statistic flagged the baseline's own past "
        "(each date replayed against strictly earlier dates only). Not a measure of "
        "detection accuracy."
    )
    reason: str | None = Field(default=None, description="Why the baseline is not valid, when it is not.")


# --------------------------------------------------------------------------
# /detect
# --------------------------------------------------------------------------


class DetectResponse(DisclaimerMixin):
    """Real Sentinel-2 index values and scene metadata. No calibrated anomaly
    baseline exists, so detection and prediction conclusions are unavailable.
    With BASELINE_MODE off no anomaly is computed; with BASELINE_MODE=test,
    `signal_anomaly` and `baseline` add a provisional, uncalibrated comparison
    with a monitoring site's own seasonal history (statistical only)."""

    model_config = ConfigDict(json_schema_extra={"example": {
        "lat": 13.45, "lng": 100.65, "date": "2024-03-15",
        "status": "ok", "detected": None, "spatial_anomaly_z": None,
        "signal_anomaly_level": None,
        "index_used": "ndci",
        "index_values": {"ndci": 0.01, "2bda": 0.02, "3bda": 0.03, "b2_b3_ratio": 0.9},
        "cloud_fraction": 0.05, "actual_date": "2024-03-14",
        "true_color_image_url": "/satellite-image?lat=13.45&lng=100.65&date=2024-03-14&image_type=true_color",
        "ndci_heatmap_image_url": "/satellite-image?lat=13.45&lng=100.65&date=2024-03-14&image_type=ndci_heatmap",
        "disclaimer": DISCLAIMER_TEXT,
    }})

    lat: float
    lng: float
    date: str = Field(description="Date requested, YYYY-MM-DD.")

    status: Literal["ok", "no_imagery", "no_water_pixels"]
    detected: bool | None = Field(
        default=None, description="Not computed — no valid anomaly baseline exists. "
        "Null does not mean absence of a bloom."
    )
    spatial_anomaly_z: float | None = Field(
        default=None, description="Reserved for a future valid statistic. "
        "Not computed — no valid baseline exists; always null currently."
    )
    signal_anomaly_level: Literal["normal", "watch", "high"] | None = Field(
        default=None,
        description="Preliminary robust statistical level for a future compatible "
        "Sentinel-2 baseline. Null unless BASELINE_MODE=test, because no calibrated "
        "baseline is persisted; in test mode it repeats `signal_anomaly.level` "
        "(provisional, uncalibrated TEST baseline). Separate from biological risk_level.",
    )
    signal_anomaly: dict | None = Field(
        default=None,
        description="Null unless BASELINE_MODE=test. Then this reading against the TEST "
        "baseline's history for the monitoring site at exactly this lat/lng: `level` "
        "(normal|watch|high or null), `robust_z`, `median_ndci`, `mad`, "
        "`independent_date_count`, `reason` (why no level, e.g. site_not_in_baseline, "
        "no_imagery, insufficient_independent_dates, baseline_invalid:<reason>) and "
        "`location_id`. A statistical anomaly against that site's own seasonal record, "
        "not a bloom detection.",
    )
    baseline: BaselineInfo | None = Field(
        default=None, description="The TEST baseline in force; null unless BASELINE_MODE=test."
    )
    index_used: str
    index_values: dict[str, float] | None
    reason: str | None = Field(
        default=None, description="Why status != 'ok', when applicable."
    )

    cloud_fraction: float | None = Field(
        default=None, description="Sentinel-2 cloud fraction in the sample buffer, "
        "when a satellite pull actually happened."
    )
    actual_date: str | None = Field(
        default=None, description="Actual satellite scene date used. Routinely older "
        "than the requested `date` and never newer: the newest usable image acquired "
        "on or before that day is used, up to the system's scene-age ceiling."
    )

    true_color_image_url: str | None = Field(
        default=None, description="GET /satellite-image URL (true-color RGB PNG) for "
        "this exact lat/lng/date, resolving to the same Sentinel-2 scene this response "
        "was computed from. Null only when `status != 'ok'` (no usable scene existed "
        "for the numeric reading either, so a second live render would fail the same "
        "way) -- never a placeholder image. When non-null, the URL still does a live, "
        "several-second GEE render on fetch; it is not pre-cached."
    )
    ndci_heatmap_image_url: str | None = Field(
        default=None, description="GET /satellite-image URL (NDCI heatmap PNG, "
        "5-stop visualization colour ramp) for this exact lat/lng/date. Same null rule as "
        "`true_color_image_url`."
    )

    elevated_z_threshold: float | None = Field(
        default=None, description="Inactive: no valid anomaly statistic exists. "
        "Always null currently."
    )
    warning_z_threshold: float | None = Field(
        default=None, description="Inactive: no valid anomaly statistic exists. "
        "Always null currently."
    )
    in_study_area: bool = Field(
        description="Whether lat/lng falls inside the confirmed upper Gulf of "
        "Thailand study-area polygon (data-pipeline/src/study_area.py). A "
        "reading outside it is never blocked or fabricated -- it's flagged, "
        "not refused -- but should not be trusted to the same degree as a "
        "reading inside the study area."
    )
    study_area_warning: str | None = Field(
        default=None, description="Non-null only when in_study_area is False -- "
        "the real warning text from check_point_in_study_area()."
    )
    threshold_source: Literal["literature_default", "calibrated"] | None = Field(
        default=None, description="No threshold is applied while the anomaly "
        "statistic is unavailable. Always null currently."
    )


# --------------------------------------------------------------------------
# /risk-map (GeoJSON FeatureCollection)
# --------------------------------------------------------------------------


class RiskMapProperties(DisclaimerMixin):
    site_id: str
    name: str
    site_type: Literal["monitoring_grid"] = Field(
        default="monitoring_grid",
        description="Explicit, typed marker that this site is one of src/grid.py's "
        "7 live-monitoring points. Every /risk-map feature is a monitoring-grid site, so "
        "this is currently a constant, but it's a real typed field (not a hardcoded "
        "frontend assumption) so it generalizes cleanly if this endpoint, or the "
        "SitePanel it feeds, ever surfaces a non-grid site type.",
    )

    # -- prediction (risk_level(), rule-based, indicative) --
    risk_level: Literal["normal", "elevated", "watch", "warning"] | None
    triggered_rules: list[str]
    confidence_label: str = Field(
        description="Always attached per config.yaml's prediction_confidence_label — "
        "this word never travels without its caveat."
    )

    # -- Sentinel-2 reading, separate from risk_level --
    status: Literal["ok", "no_imagery", "no_water_pixels", "no_climatology", "error", "no_data_yet"]
    detected: bool | None
    spatial_anomaly_z: float | None
    signal_anomaly_level: Literal["normal", "watch", "high"] | None = Field(
        default=None,
        description="Preliminary statistical satellite-signal level. Null until a "
        "compatible Sentinel-2 baseline exists; not a bloom-risk classification. "
        "With BASELINE_MODE=test: shown only when this cached reading was assessed "
        "against exactly the response's `baseline.version`.",
    )
    signal_robust_z: float | None = Field(
        default=None, description="Robust z of NDCI against this site's own seasonal "
        "history in the TEST baseline. Same null rule as `signal_anomaly_level`."
    )
    signal_anomaly_reason: str | None = Field(
        default=None, description="Why `signal_anomaly_level` is null in test mode "
        "(e.g. no_imagery, insufficient_independent_dates, site_not_in_baseline, "
        "not_assessed_against_active_baseline, no_cached_reading_yet, "
        "baseline_invalid:<reason>). Null when a level is shown, and always null "
        "with BASELINE_MODE off."
    )
    index_used: str | None
    index_values: dict[str, float] | None = None

    cloud_fraction: float | None = None
    actual_date: str | None = None

    true_color_image_url: str | None = Field(
        default=None, description="GET /risk-map/{site_id}/image?image_type=true_color "
        "URL for this site's latest scheduler-cached true-color PNG. Serves cached "
        "bytes (fast, no live GEE call) -- unlike /detect's or /satellite-image's "
        "image URLs, which render live on fetch. Null whenever no cached image exists "
        "yet for this site (no successful cache row, detection status != 'ok' on the "
        "last refresh, or the image render itself failed that cycle) -- never a "
        "placeholder image."
    )
    ndci_heatmap_image_url: str | None = Field(
        default=None, description="GET /risk-map/{site_id}/image?image_type=ndci_heatmap "
        "URL for this site's latest scheduler-cached NDCI heatmap PNG. Same null rule "
        "as `true_color_image_url`."
    )

    fetched_at: str | None = Field(
        default=None, description="When this cached reading was computed (ISO 8601). "
        "/risk-map serves the scheduler's cache, not a live GEE pull per request."
    )
    stale: bool = Field(
        default=False,
        description="True if the most recent scheduled refresh for this site failed — "
        "this is carried-over data from an earlier successful run, not a fresh one.",
    )
    error: str | None = None


class RiskMapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict = Field(description="GeoJSON Point geometry: {type: 'Point', coordinates: [lng, lat]}")
    properties: RiskMapProperties


class RiskMapResponse(DisclaimerMixin):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[RiskMapFeature]
    baseline: BaselineInfo | None = Field(
        default=None, description="The TEST baseline every feature's signal fields were "
        "checked against; null unless BASELINE_MODE=test."
    )


# --------------------------------------------------------------------------
# /timeseries
# --------------------------------------------------------------------------


class TimeseriesPoint(BaseModel):
    date: str
    chlor_a: float = Field(description="MODIS-Aqua chlor_a reading for this date (mg/m^3).")
    anomaly_z: float | None = Field(
        description="z-score of chlor_a against this date's day-of-year climatology, "
        "or null if the climatology window had no other observations (see `reason`)."
    )
    reason: str | None = Field(
        default=None, description="Why anomaly_z is null, when applicable."
    )
    # MODIS chlor_a is a bulk multi-year archive series (get_modis_chlorophyll_history),
    # not a per-date Sentinel-2 pull -- cloud_fraction/actual_date are Sentinel-2-specific
    # concepts (see detect()'s use of get_sentinel2_bands) and genuinely don't apply to
    # this series, so they're explicitly null rather than omitted or faked.
    cloud_fraction: None = Field(
        default=None, description="Not applicable — MODIS chlor_a series, not a "
        "Sentinel-2 pull. Always null here; see /detect for a Sentinel-2 reading."
    )
    actual_date: None = Field(
        default=None, description="Not applicable — see `cloud_fraction`."
    )


class TimeseriesResponse(DisclaimerMixin):
    lat: float
    lng: float
    source: str = "MODIS-Aqua chlor_a, 2002-present (data-pipeline get_modis_chlorophyll_history)"
    points: list[TimeseriesPoint]


# --------------------------------------------------------------------------
# /summary
# --------------------------------------------------------------------------


class RiskLevelCounts(BaseModel):
    normal: int = 0
    elevated: int = 0
    watch: int = 0
    warning: int = 0
    not_evaluated: int = Field(
        default=0, description="Sites with real index readings but no computed "
        "risk level: no valid anomaly baseline exists. Not a normal-water count."
    )
    not_checked_yet: int = Field(
        default=0,
        description="Sites the scheduler has not reached yet -- no cache row at all. "
        "This is a loading state, not a finding: it says nothing about the water. "
        "Distinct from no_usable_data, and never merged with it.",
    )
    no_usable_data: int = Field(
        default=0,
        description="Sites the scheduler did read, whose reading produced no usable "
        "value -- status no_imagery / no_water_pixels / no_climatology / error. "
        "This is a real finding about a real attempt (cloud cover, no baseline, a "
        "failed fetch), not a loading state. These sites are excluded from the four "
        "risk-level counts rather than being counted as 'normal'.",
    )


class MostRecentDetection(BaseModel):
    site_id: str
    name: str
    spatial_anomaly_z: float | None
    detected: bool
    actual_date: str | None
    fetched_at: str | None


class SummaryResponse(DisclaimerMixin):
    total_sites: int
    risk_level_counts: RiskLevelCounts
    most_recent_detected_signal: MostRecentDetection | None = Field(
        description="The most recent site with detected=true in the cache, or null if "
        "none currently are."
    )
    stale_site_count: int = Field(
        description="Sites whose cached reading is marked stale (last scheduler refresh "
        "failed for them)."
    )
    oldest_fetched_at: str | None
    newest_fetched_at: str | None
    prediction_confidence_label: str
    baseline: BaselineInfo | None = Field(
        default=None, description="The TEST baseline in force; null unless BASELINE_MODE=test."
    )


# --------------------------------------------------------------------------
# /regional-scan
# --------------------------------------------------------------------------

class RasterSceneDateShare(BaseModel):
    """How much of one raster came from one acquisition day.

    A raster is a most-recent-wins mosaic over every usable scene in the
    window, so `oldest_scene_date`..`newest_scene_date` is a span, not a
    description. The span cannot distinguish a picture whose cells are
    mostly one pass from one spread evenly across ten days, and a reader
    shown only the span will assume the second. These entries state which
    it is.
    """

    date: str = Field(description="Acquisition day, YYYY-MM-DD (UTC).")
    cells: int = Field(description="Cells in this raster whose own scene was acquired that day.")
    share: float = Field(
        description="`cells` as a fraction of the run's kept cells, 0..1. The entries sum "
        "to 1.0 up to float rounding -- every kept cell has exactly one acquisition day.")


class RasterCoverage(BaseModel):
    """How much of the study area this overlay actually has a reading for.

    Counted in overlay pixels, which is what a viewer sees, not in stored
    cells: two cells can land on one overlay pixel, and a cell that fell
    marginally outside the polygon is still drawn but is not counted here.

    The denominator is the study POLYGON, land included. The polygon is a
    boundary, not a water mask -- the coastline inside it can never carry
    a reading and is counted against this figure -- so this is NOT the
    fraction of *water* that was measured, and must not be presented as
    one. The unmeasured remainder is cloud, land and "no scene covered
    it" together: the stored raster cannot separate them (LIMITATIONS.md,
    "Unmeasured is not zero").
    """

    measured_fraction: float = Field(
        description="measured_pixels / polygon_pixels, 0..1, as the renderer computed it.")
    measured_pixels: int | None = Field(
        default=None, description="Overlay pixels inside the study polygon carrying a reading. "
        "Null for an overlay rendered before this count was recorded -- the fraction beside it "
        "is still the renderer's own, and the count is left absent rather than reconstructed "
        "by multiplying a rounded fraction back out.")
    polygon_pixels: int = Field(
        description="Overlay pixels whose centre falls inside the study polygon -- land "
        "included. The denominator.")


class LatestSceneInfo(BaseModel):
    """The newest Sentinel-2 acquisition date the latest-scene policy has
    assessed (`scene_assessments`, src/raster_scan/trigger.py), and whether
    it reached the served raster.

    Read-only metadata about WHICH SCENES WERE CHOSEN. It is a cloud and
    water-pixel screen of a date, not a bloom statement: "passed" means
    enough cloud-free water was observed to be worth scanning, nothing more.
    The previous raster keeps being served when the newest date is rejected.
    """

    acquisition_date: str = Field(
        description="Newest assessed acquisition date, YYYY-MM-DD (UTC). One date combines "
        "every tile and orbit of that UTC day over the study polygon.")
    decision: str = Field(
        description="'passed', 'rejected_cloud' or 'rejected_no_water' -- the decision at the "
        "time of the latest assessment. A date that is not yet settled can change it.")
    cloud_fraction: float | None = Field(
        default=None, description="Cloud share (0-1) of the observed water pixels. Null only "
        "when no water pixel was observed (rejected_no_water).")
    threshold_cloud_fraction: float | None = Field(
        default=None, description="The maximum cloud fraction currently configured "
        "(RASTER_SCENE_MAX_CLOUD_FRACTION): a date passes at or below it. The decision itself "
        "was made when the date was assessed, under the threshold in force then. Null when "
        "the configured value is invalid.")
    min_water_pixels: int | None = Field(
        default=None, description="The minimum unmasked water pixels currently configured "
        "(RASTER_SCENE_MIN_WATER_PIXELS) for a date to pass. Null when the configured value "
        "is invalid.")
    reason: str | None = Field(
        default=None, description="Why the date was rejected; null for a passing date.")
    used_in_run_id: int | None = Field(
        default=None, description="The raster scan run this date triggered, once one finished "
        "using it; null while unused. Kept even if a later re-assessment rejects the date.")
    assessed_at: str = Field(description="When the date was last assessed (UTC, ISO 8601).")
    settled: bool = Field(
        description="True once the assessment was made at least 36 h after the date began (UTC), "
        "when every granule of that day has normally been ingested, so the decision is final. "
        "False means later assessments may still change it (e.g. rejected_cloud to passed as "
        "tiles arrive).")
    used_in_served_run: bool = Field(
        description="True when `used_in_run_id` is the run whose raster is served in this "
        "response (`run_id`). False when the date is unused, or was used by a different run.")
    reassessed_after_use: bool = Field(
        description="True when this date was used by a scan (`used_in_run_id` is set) but its "
        "latest assessment is not 'passed'. The raster was built from it before it was "
        "re-assessed as not passing; say so rather than calling it simply 'not used'.")


class ScenePollInfo(BaseModel):
    """Health of the latest-scene poll that looks for newer acquisitions.

    This is the only way to tell "no newer usable scene" apart from "the
    poll could not check": read `last_poll_ok_at` before reading anything
    into the absence of a newer scene.
    """

    last_poll_started_at: str | None = Field(
        default=None, description="When the poll last began (UTC, ISO 8601). A poll skipped "
        "because the process was shutting down records nothing.")
    last_poll_ok_at: str | None = Field(
        default=None, description="When a poll last completed its scene assessment without "
        "error (UTC, ISO 8601), whether or not it found anything new. A missing or old value "
        "means newer scenes may exist that this system has not checked; it is never evidence "
        "of no newer scene.")
    last_error: str | None = Field(
        default=None, description="The most recent poll failure message. Kept after later "
        "successes: compare `last_error_at` with `last_poll_ok_at`.")
    last_error_at: str | None = Field(
        default=None, description="When that failure happened (UTC, ISO 8601).")
    last_error_kind: str | None = Field(
        default=None, description="'gee_auth', 'gee_config', 'assessment_failed' or "
        "'unexpected'.")


class RasterScanResponse(DisclaimerMixin):
    """Metadata for the newest raster overlay still present on disk.

    The image itself is fetched separately from `overlay_url`; this
    payload stays small enough to poll. Every field is null when no
    overlay has been rendered -- there is no placeholder raster, because
    an empty overlay drawn over the study area would assert "we looked
    and saw nothing", which is not the same as "we have not looked".

    The exceptions are `latest_scene`, `last_used_scene_date` and `poll`:
    they describe the scene-selection poll rather than the overlay, are
    independent of BASELINE_MODE, and are served with or without an
    overlay (null only when their tables hold nothing).
    """

    run_id: int | None = Field(default=None, description="Run that produced the served overlay.")
    status: str | None = Field(default=None, description="That run's status.")
    date_used: str | None = Field(default=None, description="Target date the scan was run for.")
    scale_m: int | None = Field(
        default=None, description="Read scale in metres. A cell is ONE nearest-neighbour "
        "sampled native pixel at this spacing, not an average of the pixels it covers -- "
        "see data-pipeline/src/raster.py.")
    cell_count: int | None = Field(default=None, description="Cells carrying a real reading.")
    scene_count: int | None = Field(
        default=None, description="Candidate Sentinel-2 acquisitions considered for the mosaic. "
        "Some may contribute no retained cells after masking and compositing.")
    oldest_scene_date: str | None = Field(
        default=None, description="Oldest acquisition date among the retained cells.")
    newest_scene_date: str | None = Field(
        default=None, description="Newest acquisition date among the retained cells. One raster "
        "routinely mixes several dates; each cell carries its own.")
    scene_dates: list[RasterSceneDateShare] | None = Field(
        default=None, description="Per-acquisition-day breakdown of the kept cells, largest "
        "share first -- the distribution the oldest/newest span hides. Counted per calendar "
        "day, so it is never longer than `scene_count` (several tiles can share a day). Null "
        "for a run taken before this was recorded: unknown, not evenly spread.")
    source_metadata: dict | None = Field(
        default=None, description="Bootstrap/search windows and the exact selected scene IDs "
        "and acquisition dates for this run.")
    completed_at: str | None = Field(default=None, description="When that run finished (UTC).")
    coverage: RasterCoverage | None = Field(
        default=None, description="How much of the study polygon carries a reading, and how "
        "much therefore does not. Null when the overlay's render metadata predates this field.")
    bounds: list[list[float]] | None = Field(
        default=None, description="[[south, west], [north, east]] for a Leaflet ImageOverlay. "
        "Covers the whole study polygon, not merely the cells that returned data, so a cloudy "
        "day cannot silently shrink the overlay.")
    legend: dict | None = Field(
        default=None, description="What each colour means, carried with the picture: the value "
        "swatches are sampled from the same ramp that painted the image, so a legend cannot "
        "drift from it. Explains that transparent no-data is never a low or zero reading.")
    overlay_url: str | None = Field(default=None, description="Where to fetch the PNG.")
    true_color_url: str | None = Field(
        default=None, description="Run-aligned true-color PNG, when this run stored RGB bands.")
    stale_run_id: int | None = Field(
        default=None, description="Set when a newer run exists whose overlay is not on disk "
        "(running, failed, or expired). The served picture is older than the newest attempt.")
    reason: str | None = Field(
        default=None, description="Why no overlay is being served, when there is none.")
    latest_scene: LatestSceneInfo | None = Field(
        default=None, description="The newest acquisition date assessed by the latest-scene "
        "policy, whether it passed, and whether it is in the served raster. Null when no date "
        "has been assessed. The served raster may predate it: a rejected or not-yet-scanned "
        "newest date does not replace the earlier data.")
    last_used_scene_date: str | None = Field(
        default=None, description="The newest acquisition date a raster scan has used "
        "(YYYY-MM-DD); null when none has.")
    poll: ScenePollInfo | None = Field(
        default=None, description="Health of the newer-scene poll. Null when it has never "
        "recorded a status. A null or old `last_poll_ok_at` means newer scenes may exist that "
        "this system has not checked -- never 'no newer scene'.")


class VisibleBandsDN(BaseModel):
    """The cell's stored visible bands, raw COPERNICUS/S2_SR_HARMONIZED digital
    numbers (reflectance x 10000): red = B4, green = B3, blue = B2. Shown so a
    reader can see the signal behind an index value; the low-signal screen
    excludes a cell when any of them is below 50 DN (developer-chosen, not
    validated). Null where the stored value is not finite."""

    red: float | None
    green: float | None
    blue: float | None


class RasterPixelAnomaly(BaseModel):
    """One raster cell against its own TEST seasonal cell baseline.

    Computed by src/raster_scan/cell_anomaly.py with detection's robust z
    (baseline.assess_cells): z = (ndci - median) / (1.4826 * mad), watch at
    z >= 2, high at z >= 3 (provisional engineering boundaries). Assessed
    only when the cell is acquired strictly after the baseline's
    history_end, at most 14 days before the run's date_used, with a
    baseline cell of n >= the declared floor and MAD > 0, and only when the
    reading passes both data-quality screens (NDCI not exactly ±1; every
    visible band >= 50 DN); otherwise `reason` says which rule failed first
    and z/level are null. Null altogether when the run's blob stores no
    visible bands (an unscreened cell is never scored).
    """

    robust_z: float | None = Field(description="Robust z; null unless assessed.")
    median_ndci: float | None = Field(
        description="The cell's baseline median NDCI for this season window; null when the "
        "baseline has no cell at this location.")
    mad: float | None = Field(description="The cell's baseline MAD (unscaled).")
    n_dates: int | None = Field(
        description="Independent clear-sky dates behind the cell's baseline statistics.")
    level: Literal["normal", "watch", "high"] | None = Field(
        description="Anomaly level against the cell's own history (TEST); null unless "
        "assessed. 'normal' does not mean safe water.")
    reason: Literal["invalid", "low_signal", "too_old", "not_after_history", "no_baseline",
                    "insufficient_dates", "zero_mad"] | None = Field(
        description="Why the cell was not assessed (first failing rule of seven); null when "
        "it was. 'invalid' includes a degenerate NDCI of exactly ±1; 'low_signal' a visible "
        "band below 50 DN (developer-chosen data-quality screen, not validated).")
    visible_bands_dn: VisibleBandsDN = Field(
        description="The stored visible bands the low-signal screen judged.")
    baseline_version: str = Field(description="The TEST baseline version used.")
    season_key: str = Field(description="Season window of the run's date_used, e.g. 'm09+-1'.")


class RasterPixelResponse(DisclaimerMixin):
    """One cell of the served raster, looked up by coordinate.

    Read straight out of the stored blob the overlay was drawn from --
    never a live Earth Engine call, so the numbers here are the numbers
    behind the picture on screen and cannot drift from it between clicks.

    `state` answers in the same three states the overlay paints, because a
    difference a reader can see must be a difference they can be told:
    a reading, water inside the study area that was NOT measured, and
    outside the study area. Cloud, land and no-pass are one state because
    the stored raster holds no evidence separating them (see
    `src/raster_scan/pixel.py`).
    """

    model_config = ConfigDict(json_schema_extra={"example": {
        "run_id": 12, "state": "reading",
        "query_lat": 13.05, "query_lng": 100.62,
        "cell_lat": 13.049944, "cell_lng": 100.620321,
        "pixel_centre_lat": 13.050137, "pixel_centre_lng": 100.620126,
        "pixel_row": 214, "pixel_col": 401,
        "index_values": {"ndci": 0.031, "bda2": 1.18, "bda3": 0.29, "b2_b3": 0.83},
        "date_ms": 1788492600000, "acquired_date": "2026-09-04",
        "acquired_at": "2026-09-04T03:30:00Z",
        "scale_m": 200, "date_used": "2026-09-06",
        "disclaimer": DISCLAIMER_TEXT,
    }})

    state: Literal["reading", "not_measured", "outside_study_area"] = Field(
        description="Which of the overlay's three drawn states this coordinate is in. "
        "'not_measured' is water inside the study area with no usable reading -- cloud, "
        "land-masked, or no scene covered it. It is NOT a low reading and NOT a zero: "
        "the three causes are one state because the stored raster cannot tell them apart.")
    meaning: str = Field(description="What `state` means, in the legend's own words.")

    run_id: int = Field(description="The run whose stored cells answered -- the same run "
                        "whose overlay /raster-scan serves, so the number matches the picture.")
    date_used: str | None = Field(default=None, description="Target date that run asked about. "
                                  "NOT the date of this reading -- see `acquired_date`.")
    scale_m: int | None = Field(
        default=None, description="That run's read scale in metres, and the width of the "
        "square this cell is drawn as. The cell is ONE nearest-neighbour sampled native "
        "pixel at that spacing, not an average of the square -- a click anywhere in the "
        "square returns that same single observation.")

    query_lat: float = Field(description="Latitude asked about, echoed back.")
    query_lng: float = Field(description="Longitude asked about, echoed back.")
    cell_lat: float | None = Field(
        default=None, description="The sampled pixel's OWN latitude, as Earth Engine "
        "reported it. Where the observation actually is; null when nothing was measured.")
    cell_lng: float | None = Field(
        default=None, description="The sampled pixel's own longitude. See `cell_lat`.")
    pixel_centre_lat: float | None = Field(
        default=None, description="Centre latitude of the drawn square containing the query. "
        "A display coordinate, not an observation -- `cell_lat` is the measurement's own.")
    pixel_centre_lng: float | None = Field(
        default=None, description="Centre longitude of the drawn square. See `pixel_centre_lat`.")
    pixel_row: int | None = Field(
        default=None, description="Row of that square in the overlay PNG (row 0 is northmost). "
        "Null when the coordinate falls outside the image.")
    pixel_col: int | None = Field(
        default=None, description="Column of that square in the overlay PNG.")

    index_values: dict[str, float | None] | None = Field(
        default=None, description="The four spectral indices stored for this cell, under the "
        "raster's own band names (ndci, bda2, bda3, b2_b3 -- the same quantities /detect "
        "returns as ndci/2bda/3bda/b2_b3_ratio). Exactly the stored values, widened from "
        "float32 and never rounded. Readings only: no anomaly score, no risk level, no "
        "classification -- no valid spectral-index baseline exists. Null unless "
        "state == 'reading'.")
    unreadable_bands: list[str] = Field(
        default_factory=list, description="Bands whose stored value is not a finite number "
        "(an index is a ratio, and a zero-reflectance pixel can produce inf or NaN). Returned "
        "as null rather than clamped to an end of the scale, which would invent a reading. "
        "The overlay draws such a band as unmeasured even though the cell was measured.")

    date_ms: int | None = Field(
        default=None, description="THIS cell's own acquisition time (epoch ms, UTC) -- the "
        "authoritative date field, carried as an integer because float32 cannot hold epoch "
        "milliseconds without moving them off the scene they name. Neighbouring cells "
        "routinely differ: the composite is most-recent-wins per pixel.")
    acquired_date: str | None = Field(
        default=None, description="`date_ms` as YYYY-MM-DD (UTC), derived from it, never the "
        "other way round.")
    acquired_at: str | None = Field(
        default=None, description="`date_ms` as a full UTC timestamp.")
    anomaly: RasterPixelAnomaly | None = Field(
        default=None, description="This cell's NDCI against the cell's OWN TEST seasonal "
        "baseline (Level B). Present only with BASELINE_MODE=test, a valid baseline whose "
        "cell file for the run's season can be used, and state == 'reading'; null "
        "otherwise. A statistical anomaly, uncalibrated -- not a bloom detection and not "
        "a risk level. Its numbers equal the anomaly highlight pin for the same cell.")


# --------------------------------------------------------------------------
# /raster-scan/highlights
# --------------------------------------------------------------------------

HIGHLIGHT_RANKING_TEXT = "descending value within this run; not a risk level"


class RasterHighlightPin(BaseModel):
    """One highlight pin: a measured cell of the served run, by rank.

    Read from the stored blob (src/raster_scan/highlights.py), never from
    Earth Engine. A rank by value inside one scan -- high NDCI can also come
    from suspended sediment, shallow bottom, sun glint or cloud edges, and
    does not by itself identify a bloom or a species.
    """

    rank: int = Field(description="1 = highest value in this run after de-duplication.")
    cell_lat: float = Field(
        description="The sampled pixel's own latitude -- where the observation is.")
    cell_lng: float = Field(description="The sampled pixel's own longitude.")
    pixel_centre_lat: float = Field(
        description="Centre latitude of the overlay square this cell paints. A display "
        "coordinate; `cell_lat` is the measurement's own.")
    pixel_centre_lng: float = Field(description="Centre longitude of that square.")
    index_values: dict[str, float | None] = Field(
        description="The four stored indices (ndci, bda2, bda3, b2_b3), widened from "
        "float32, never rounded. A non-finite stored value is null, not a number.")
    percentile: float = Field(
        description="Share of this run's cohort with a strictly lower metric, x 100. "
        "Relative to this run only; not comparable across runs.")
    metric_value: float = Field(description="The value this pin was ranked by.")
    date_ms: int = Field(description="This cell's own acquisition time (epoch ms, UTC).")
    acquired_date: str = Field(description="`date_ms` as YYYY-MM-DD (UTC).")
    acquired_at: str = Field(description="`date_ms` as a full UTC timestamp.")
    edge_of_no_data: bool = Field(
        description="True when any of the 8 neighbouring overlay squares whose centre lies "
        "inside the study polygon carries no reading (cloud, land mask, no pass). Neighbours "
        "outside the polygon do not count. Cloud edges and masks can distort index values.")
    risk_tier: None = Field(
        default=None, description="Always null: no tier is computed for a pin -- no valid "
        "spectral-index baseline or validated threshold exists. Reserved so a future, "
        "separately approved gate can fill it without a contract change.")
    visible_bands_dn: VisibleBandsDN | None = Field(
        default=None, description="The cell's stored visible bands (raw DN: red B4, green "
        "B3, blue B2), so a reader can see the signal behind the value. Null when the run's "
        "blob stores no visible bands.")


class RasterHighlightsResponse(DisclaimerMixin):
    """The top-N measured cells of one stored raster run, ranked by value.

    A descriptive ranking inside one scan: no threshold, no baseline, no
    classification. Cells are ranked only where the overlay paints a
    reading (date-valid, finite NDCI, inside the study polygon), so a
    masked or unmeasured area can never hold a pin.
    """

    model_config = ConfigDict(json_schema_extra={"example": {
        "run_id": 4, "mode": "ndci", "metric": "ndci", "ranking": HIGHLIGHT_RANKING_TEXT,
        "n_requested": 5, "min_separation_m": 3000, "cohort_size": 187560,
        "pins": [{
            "rank": 1, "cell_lat": 13.049944, "cell_lng": 100.620321,
            "pixel_centre_lat": 13.050137, "pixel_centre_lng": 100.620126,
            "index_values": {"ndci": 0.112, "bda2": 1.25, "bda3": 0.41, "b2_b3": 0.83},
            "percentile": 99.99, "metric_value": 0.112, "date_ms": 1788492600000,
            "acquired_date": "2026-09-04", "acquired_at": "2026-09-04T03:30:00Z",
            "edge_of_no_data": False, "risk_tier": None,
            "visible_bands_dn": {"red": 412.0, "green": 655.0, "blue": 803.0},
        }],
        "reason": None, "baseline": None, "excluded_degenerate": 0,
        "excluded_low_signal": 12, "quality_note": None,
        "disclaimer": DISCLAIMER_TEXT,
    }})

    run_id: int = Field(description="The run whose stored cells were ranked.")
    mode: Literal["ndci", "anomaly"] = Field(
        description="'ndci': rank by NDCI (this model). 'anomaly': pins that meet the TEST "
        "cell-baseline condition (RasterAnomalyHighlightsResponse).")
    metric: str = Field(description="The stored band the pins are ranked by.")
    ranking: Literal["descending value within this run; not a risk level"] = Field(
        default=HIGHLIGHT_RANKING_TEXT, description="What the order means. Cells whose NDCI "
        "is exactly ±1 are excluded from pins: a band is zero, which is not a physical "
        "water-colour value (see `excluded_degenerate`).")
    n_requested: int = Field(description="Pins asked for (3-10).")
    min_separation_m: int = Field(
        description="De-duplication radius: a cell closer than this (great-circle, between "
        "cell coordinates) to a higher-ranked pin is skipped.")
    cohort_size: int = Field(
        description="Measured cells ranked -- the overlay squares carrying a reading.")
    pins: list[RasterHighlightPin] = Field(description="Highest first; may be fewer than n.")
    reason: str | None = Field(
        default=None, description="Why there are fewer pins than requested: 'no measured "
        "cells' or 'only k separable measured cells'. Null when n pins were found.")
    baseline: dict | None = Field(
        default=None, description="Baseline the pins were compared with. Always null in "
        "'ndci' mode: a ranking by value needs none.")
    excluded_degenerate: int = Field(
        description="Measured cells excluded from pins because their NDCI is exactly ±1 "
        "(|ndci| >= 1 - 1e-6): a band is zero, which is not a physical water-colour value "
        "(mostly mask-edge artefacts). They stay in `cohort_size` and in every percentile "
        "-- the map paints them -- but are never pinned. In 'anomaly' mode they are also "
        "counted in `counts.invalid`.")
    excluded_low_signal: int | None = Field(
        description="Measured cells (not already degenerate) excluded from pins because a "
        "visible band (B4, B3 or B2) is below 50 DN: near-black pixels, where NDCI is a "
        "ratio of noise. A developer-chosen data-quality screen, not validated against "
        "field data. They stay in `cohort_size` and every percentile. Null -- not 0 -- when "
        "the run's blob stores no visible bands and the screen could not run (see "
        "`quality_note`).")
    quality_note: str | None = Field(
        default=None, description="Set when a data-quality screen could not run for this "
        "run (no visible bands stored); null otherwise.")


# --------------------------------------------------------------------------
# /raster-scan/highlights?mode=anomaly (Level B TEST cell baseline)
# --------------------------------------------------------------------------

ANOMALY_RANKING_TEXT = (
    "descending robust z against this location's own TEST seasonal baseline; not a risk level"
)


class RasterAnomalyPin(RasterHighlightPin):
    """A measured cell meeting the TEST anomaly condition: robust z >= 2 against
    the cell's own seasonal baseline (positive anomalies only).

    The ndci-mode pin fields keep their meaning, except `metric_value` (the
    robust z) and `percentile` (share of the ASSESSABLE cells with a strictly
    lower z). A statistical anomaly of one sampled pixel against its own
    clear-sky record -- uncalibrated, not a bloom detection, not a risk level;
    sediment, shallow bottom, glint and cloud edges can also raise NDCI.
    """

    robust_z: float = Field(description="(ndci - median_ndci) / (1.4826 * mad); >= 2.")
    median_ndci: float = Field(description="The cell's baseline median NDCI (season window).")
    mad: float = Field(description="The cell's baseline MAD (unscaled), > 0.")
    n_dates: int = Field(description="Independent clear-sky dates behind the baseline.")
    anomaly_level: Literal["watch", "high"] = Field(
        description="'watch' at z >= 2, 'high' at z >= 3 -- provisional engineering "
        "boundaries against the cell's own history (TEST), not a risk level.")


class RasterAnomalyCounts(BaseModel):
    """How the measured cells of the run were assessed. `assessable` plus the SEVEN
    reason counts equals `measured`; each unassessable cell is counted once, in
    the first rule it fails (invalid, low_signal, too_old, not_after_history,
    no_baseline, insufficient_dates, zero_mad). `watch` and `high` count
    assessable cells."""

    measured: int = Field(description="Cells the overlay paints (the cohort).")
    assessable: int = Field(description="Cells with a robust z.")
    no_baseline: int = Field(description="No baseline cell with this cell_key in the season.")
    insufficient_dates: int = Field(description="Baseline n below the declared floor.")
    zero_mad: int = Field(description="Baseline MAD == 0.")
    not_after_history: int = Field(
        description="Acquired on or before the baseline's history_end (leakage guard).")
    too_old: int = Field(description="Acquired more than 14 days before date_used.")
    invalid: int = Field(
        description="NDCI non-finite, outside [-1, 1] or degenerate (exactly ±1: a zero "
        "band), or acquired after date_used.")
    low_signal: int = Field(
        description="A visible band (B4, B3 or B2) below 50 DN, or not finite: near-black "
        "pixels where NDCI is unreliable. A developer-chosen data-quality screen, not "
        "validated against field data.")
    watch: int = Field(description="Assessable cells with 2 <= z < 3.")
    high: int = Field(description="Assessable cells with z >= 3.")
    flagged_share: float | None = Field(
        description="(watch + high) / assessable: the share of assessable measured cells "
        "at or over the thresholds in THIS scan; null when none is assessable. Level B has "
        "no historical false-alarm rate (its self-check is not available for cells; the "
        "Level A site rates are on /methods). A large share means the criterion fires "
        "often, not that blooms are widespread.")


class CellBaselineSummary(BaseModel):
    """The season of the Level B (per-cell) TEST baseline used, from its manifest."""

    season_key: str
    months: list[int] = Field(description="Calendar months of the season window.")
    file: str | None = None
    scale_m: int = Field(description="Raster scale the baseline cells were read at.")
    history_start: str | None = None
    history_end: str = Field(
        description="Last day the history could contain. Only cells acquired strictly "
        "later are assessed.")
    history_end_rule: str | None = None
    season_rule: str | None = None
    min_independent_dates: int = Field(description="Declared floor on a cell's n.")
    max_observation_age_days: int = Field(
        description="Oldest acquisition (days before date_used) that may be assessed.")
    cell_preprocessing_signature: str
    built_at: str | None = None
    cells: int | None = None
    cells_n_ge_floor: int | None = None
    share_n_ge_floor: float | None = None
    n_median: float | None = None
    n_min: int | None = None
    n_max: int | None = None
    mad_p05: float | None = None
    mad_p50: float | None = None
    mad_p95: float | None = None
    n_dates: int | None = None
    first_date: str | None = None
    last_date: str | None = None


class RasterAnomalyBaseline(BaselineInfo):
    """`baseline_status()` (the TEST baseline in force) plus the Level B season used."""

    level_b: CellBaselineSummary


class RasterAnomalyHighlightsResponse(RasterHighlightsResponse):
    """Pins where measured cells of one stored run meet the TEST anomaly condition.

    Only with BASELINE_MODE=test and a usable Level B baseline for the run's
    season (otherwise `mode=anomaly` answers 409 with the reason). Carries
    the TEST-baseline disclaimer. Not a risk level and not a bloom detection.
    """

    model_config = ConfigDict(json_schema_extra={"example": {
        "run_id": 6, "mode": "anomaly", "metric": "robust_z", "ranking": ANOMALY_RANKING_TEXT,
        "n_requested": 5, "min_separation_m": 3000, "cohort_size": 187560,
        "pins": [{
            "rank": 1, "cell_lat": 13.049944, "cell_lng": 100.620321,
            "pixel_centre_lat": 13.050137, "pixel_centre_lng": 100.620126,
            "index_values": {"ndci": 0.112, "bda2": 1.25, "bda3": 0.41, "b2_b3": 0.83},
            "percentile": 99.99, "metric_value": 3.4, "date_ms": 1791082200000,
            "acquired_date": "2026-10-04", "acquired_at": "2026-10-04T03:30:00Z",
            "edge_of_no_data": False, "risk_tier": None, "robust_z": 3.4,
            "median_ndci": 0.043, "mad": 0.0137, "n_dates": 44, "anomaly_level": "high",
            "visible_bands_dn": {"red": 412.0, "green": 655.0, "blue": 803.0},
        }],
        "counts": {"measured": 187560, "assessable": 180001, "no_baseline": 512,
                   "insufficient_dates": 1047, "zero_mad": 0, "not_after_history": 0,
                   "too_old": 6000, "invalid": 0, "low_signal": 640, "watch": 2210,
                   "high": 640, "flagged_share": 0.01583},
        "reason": None, "baseline": {"mode": "test", "valid": True, "...": "..."},
        "excluded_degenerate": 0, "excluded_low_signal": 640, "quality_note": None,
        "disclaimer": DISCLAIMER_TEXT_TEST_BASELINE,
    }})

    mode: Literal["anomaly"] = Field(description="'anomaly'.")
    metric: Literal["robust_z"] = Field(description="Pins are ranked by robust z.")
    ranking: Literal[
        "descending robust z against this location's own TEST seasonal baseline; "
        "not a risk level"
    ] = Field(default=ANOMALY_RANKING_TEXT, description="What the order means. Cells whose "
              "NDCI is exactly ±1 are never assessed and never pins: a band is zero, which "
              "is not a physical water-colour value (counted in `counts.invalid` and "
              "`excluded_degenerate`).")
    cohort_size: int = Field(description="Measured cells (the overlay squares carrying a "
                             "reading); equals counts.measured.")
    pins: list[RasterAnomalyPin] = Field(
        description="Highest robust z first (tie: NDCI, then lower row, then lower column), "
        "de-duplicated; may be fewer than n.")
    reason: str | None = Field(
        default=None, description="Why there are fewer pins than requested: 'no measured "
        "cells', 'no measured cells are assessable against the TEST cell baseline (0 "
        "assessable of m measured)', 'no cells meet the condition (k assessable of m "
        "measured)' or 'only j separable cells meet the condition (...)'.")
    counts: RasterAnomalyCounts
    baseline: RasterAnomalyBaseline = Field(
        description="The TEST baseline in force (baseline_status()) and the Level B season "
        "the cells were compared with.")


# --------------------------------------------------------------------------
# /methods
# --------------------------------------------------------------------------


class IndexWorkedExample(BaseModel):
    """One index evaluated by the server's own function on fixed sample bands."""

    bands: dict[str, float] = Field(
        description="The sample band values (raw S2_SR_HARMONIZED digital numbers).")
    value: float | None = Field(
        description="The registered index function's output on `bands`, computed for this "
        "response. Null only if that output is not a finite number.")
    note: str = Field(description="What the example is and is not.")


class DisplayDomain(BaseModel):
    min: float
    max: float


class MethodsIndex(BaseModel):
    """One spectral index: definition from detection/src/indices.py."""

    key: str = Field(description="detection/'s index key (index_values on /detect, /risk-map).")
    name: str
    formula: str = Field(description="Band arithmetic on Sentinel-2 bands; tested to equal "
                         "what the code computes.")
    bands: list[str]
    wavelengths_nm: dict[str, int] = Field(
        description="Centre wavelength of each band, only where project documentation states "
        "one; a band without an entry has no documented wavelength (not zero).")
    role: Literal["primary", "derived", "comparison", "exploratory"] = Field(
        description="primary: the index readings use. derived: a transformation of another "
        "index, not an independent signal. comparison: reported beside NDCI, read by no "
        "decision. exploratory: context only, not a classifier.")
    note: str
    raster_band: str = Field(description="The same index's band name in the stored raster "
                             "(/raster-scan/pixel, /raster-scan/highlights).")
    display_domain: DisplayDomain | None = Field(
        description="Value range the raster overlay's colour ramp spans. Null when no display "
        "domain has been agreed for this index (it is then never rendered).")
    worked_example: IndexWorkedExample


class MethodsSentinel2(BaseModel):
    """Sentinel-2 settings in force, read from data-pipeline / detection."""

    collection: str
    bands: list[str] = Field(description="Bands read for every reading.")
    native_resolution_m: dict[str, int]
    wavelengths_nm: dict[str, int] = Field(
        description="Documented centre wavelengths only; see `wavelengths_note`.")
    wavelengths_note: str
    revisit_days: int = Field(description="Approximate revisit at this latitude (two satellites).")
    scale_factor: float = Field(
        description="Digital number = reflectance x scale_factor. Every index is a band "
        "ratio, so it cancels; indices are computed on raw digital numbers.")
    max_scene_age_days: int = Field(
        description="Effective ceiling on how old a scene a reading may use "
        "(SENTINEL2_MAX_SCENE_AGE_DAYS or the default), read for this response.")
    max_cloud_fraction: float = Field(
        description="Largest cloud fraction a point reading's scene may have.")
    cloud_mask_scl_classes: list[int] = Field(
        description="Scene Classification Layer classes masked out of every reading.")
    min_water_occurrence_pct: float = Field(
        description="JRC Global Surface Water occurrence at or above which a pixel is water "
        "(ETOPO1 bathymetry decides only where JRC has no data).")


class MethodsModis(BaseModel):
    """MODIS-Aqua product, read from data-pipeline/src/modis.py."""

    collection: str
    bands: list[str]
    grid_resolution_m: int = Field(description="Level-3 mapped grid the product is sampled at.")
    record_start: str = Field(description="First date of the archive.")
    note: str


class SignalAnomalyFloors(BaseModel):
    min_independent_dates: int = Field(
        description="Fewest independent history dates behind one robust z.")
    max_observation_age_days: int = Field(
        description="Oldest an observation may be and still be assessed.")


class SignalAnomalyStatistic(BaseModel):
    formula: str
    mad_scale: float
    watch_at_z: float
    high_at_z: float
    note: str


class MethodsGates(BaseModel):
    """Whether the unvalidated outputs are switched on, and the floors guarding them."""

    risk_evaluation_active: bool = Field(
        description="src/scientific_status.py risk_evaluation_active(), for this response.")
    signal_anomaly_active: bool = Field(
        description="src/scientific_status.py signal_anomaly_active(), for this response.")
    signal_anomaly_floors: SignalAnomalyFloors
    signal_anomaly_statistic: SignalAnomalyStatistic


class LatestScenePolicy(BaseModel):
    """When a new acquisition date is used for a raster scan (src/raster_scan/trigger.py)."""

    max_cloud_fraction: float | None = Field(
        description="Largest cloud fraction over the polygon's water a date may have. Null "
        "when the environment setting is invalid (no default is guessed).")
    min_water_pixels: int | None = Field(
        description="Fewest unmasked water pixels a date needs. Null when the environment "
        "setting is invalid.")
    poll_interval_hours: int
    min_scan_interval_hours: int
    settle_hours: int = Field(
        description="A date's assessment is final once made this many hours after the date "
        "began (UTC); earlier assessments are repeated.")


class SeasonWindow(BaseModel):
    month: int = Field(description="Target calendar month.")
    key: str = Field(description="Season key a TEST baseline stores for that month.")
    months: list[int] = Field(description="History months an observation in `month` is "
                              "compared with.")


class MethodsReference(BaseModel):
    id: str
    citation: str = Field(description="As LIMITATIONS.md gives it.")
    doi: str
    note: str = Field(description="What the reference does not license here (LIMITATIONS.md).")


class MethodsBaselineStatus(BaselineInfo):
    """``baseline_status()``, one key per field, in every mode: ``mode`` 'off' with every
    other field null, or the TEST description (valid, or invalid with `reason`)."""

    mode: Literal["off", "test"] = Field(description="BASELINE_MODE in force.")
    valid: bool | None = Field(
        default=None, description="Null with the mode off. In test mode, false when no "
        "artefact may be used (`reason` says why).")
    kind: str | None = Field(default=None, description="'test' in test mode, else null.")


class DegenerateNdciScreen(BaseModel):
    """src/raster_scan/cell_anomaly.py's degenerate-NDCI screen, as the code applies it."""

    rule: str = Field(description="When a reading is degenerate.")
    threshold_abs: float = Field(description="|ndci| at or above this is degenerate.")
    meaning: str
    effect: str
    status: str


class LowSignalScreen(BaseModel):
    """src/raster_scan/cell_anomaly.py's low-visible-signal screen, as the code applies it."""

    rule: str = Field(description="When a cell is low_signal.")
    min_visible_dn: int = Field(description="Minimum stored DN on each visible band.")
    approx_reflectance: float = Field(description="min_visible_dn / 10000 (S2 SR scale).")
    bands: list[str] = Field(description="Sentinel-2 bands screened (stored as true_blue, "
                             "true_green, true_red).")
    rationale: str
    effect: str
    status: str = Field(description="'developer-chosen, not validated'.")


class QualityScreens(BaseModel):
    """Data-quality screens: they change which raster cells are scored and pinned,
    never the statistic."""

    degenerate_ndci: DegenerateNdciScreen
    low_signal: LowSignalScreen


class MethodsResponse(DisclaimerMixin):
    """What the Methods page shows, read from the code that computes it.

    No Earth Engine call and no database read: formulas and roles from
    detection/src/indices.py, worked examples computed by its functions for
    this response, sensor settings from data-pipeline, gates from
    src/scientific_status.py, floors from detection/src/signal_anomaly.py,
    references from LIMITATIONS.md.
    """

    api_version: str
    indices: list[MethodsIndex]
    sentinel2: MethodsSentinel2
    modis: MethodsModis
    gates: MethodsGates
    latest_scene_policy: LatestScenePolicy
    season_rule: str = Field(description="detection/src/baseline.py SEASON_RULE.")
    season_windows: list[SeasonWindow]
    baseline: MethodsBaselineStatus
    quality_screens: QualityScreens = Field(
        description="The raster data-quality screens in force, read from "
        "src/raster_scan/cell_anomaly.py.")
    references: list[MethodsReference]
