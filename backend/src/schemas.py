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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DISCLAIMER_TEXT = (
    "Detection is at satellite-pixel resolution. Small or scattered blooms "
    "may not be visible. Presence and absence are the reliable signal — "
    "concentration estimates are approximate."
)

# `/validation` needs an additional, separate caveat -- calibration status
# is not the same claim as the pixel-resolution disclaimer above, and
# CLAUDE.md is explicit that the two must not be blurred together.
CALIBRATION_CAVEAT_TEXT = (
    "Escalation thresholds in config.yaml are literature/convention defaults, "
    "not empirically calibrated against Thai events: 7 of the 14 documented "
    "events in data/validation/events.csv now have a real, human-confirmed "
    "coordinate (added 2026-08-22), but all 7 still failed to produce a "
    "usable satellite reading, each for its own verified reason -- four "
    "predate Sentinel-2's 2015 launch, one hit a coverage gap, one hit "
    "monsoon cloud cover, one failed the water-pixel mask at a near-shore "
    "site. The remaining 7 events still have no coordinate at all (named-"
    "place or province-level locations only; CLAUDE.md/docs/DETECTION_PLAN.md "
    "§3 forbid inventing one). Net result across all 14: still 0 real "
    "matched (index value, known outcome) pairs, so thresholds remain "
    "uncalibrated -- see detection/src/config.yaml's own header and "
    "detection/reports/event_table.md for the full per-event detail. "
    "Results below are reported per-event, never as a percentage — n=14 "
    "cannot support one."
)


class DisclaimerMixin(BaseModel):
    disclaimer: str = Field(
        default=DISCLAIMER_TEXT,
        description="Truth-boundary caveat. Present on every response — satellite-pixel "
        "resolution, small/scattered blooms may be missed, presence/absence is the "
        "reliable signal.",
    )


# --------------------------------------------------------------------------
# /detect
# --------------------------------------------------------------------------


class DetectResponse(DisclaimerMixin):
    """Thin wrapper over detect() -- high-confidence, standard remote
    sensing. Never call this a 'prediction'; see /risk-map, /timeseries's
    `level`/`confidence_label` fields for the separate, lower-confidence
    rule-based layer."""

    model_config = ConfigDict(json_schema_extra={"example": {
        "lat": 13.45, "lng": 100.65, "date": "2024-03-15",
        "status": "ok", "detected": False, "anomaly_z": -1.49,
        "index_used": "ndci",
        "index_values": {"ndci": 0.01, "2bda": 0.02, "3bda": 0.03, "b2_b3_ratio": 0.9},
        "cloud_fraction": 0.05, "actual_date": "2024-03-14",
        "true_color_image_url": "/satellite-image?lat=13.45&lng=100.65&date=2024-03-15&image_type=true_color",
        "ndci_heatmap_image_url": "/satellite-image?lat=13.45&lng=100.65&date=2024-03-15&image_type=ndci_heatmap",
        "disclaimer": DISCLAIMER_TEXT,
    }})

    lat: float
    lng: float
    date: str = Field(description="Date requested, YYYY-MM-DD.")

    status: Literal["ok", "no_imagery", "no_water_pixels", "no_climatology"]
    detected: bool = Field(
        description="False whenever status != 'ok' — absence of data is never "
        "reported as absence of a bloom."
    )
    anomaly_z: float | None
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
        default=None, description="Actual satellite scene date used, which may differ "
        "from the requested `date` (nearest cloud-free image within the search window)."
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
        "5-stop risk ramp) for this exact lat/lng/date. Same null rule as "
        "`true_color_image_url`."
    )

    elevated_z_threshold: float | None = Field(
        default=None, description="The operative 'elevated' z-score cutoff for "
        "`index_used`, read live from detection/src/config.yaml -- not a "
        "hardcoded frontend copy. Null when status != 'ok' (no index_used to "
        "look a threshold up for)."
    )
    warning_z_threshold: float | None = Field(
        default=None, description="The operative 'warning' z-score cutoff for "
        "`index_used`, same sourcing as `elevated_z_threshold`."
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
        default=None, description="Whether the two threshold values above are "
        "config.yaml's literature/convention defaults or a real value from a "
        "leave-one-out calibration run. Always 'literature_default' as of this "
        "build -- see /validation's calibration_caveat for why (0 of 14 "
        "validation events have produced a usable satellite reading yet, so no "
        "calibrated_* value exists in config.yaml to prefer over the default). "
        "Read live, not hardcoded, so this flips automatically the moment a "
        "future calibration run does populate a real value."
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
        "6 live-monitoring points, NOT a data/validation/events.csv historical event "
        "-- some grid site names collide with (differently-coordinated) validated "
        "event location names, e.g. grid site 'chaam' ('Cha-am coast, Phetchaburi', "
        "12.75/100.05) vs. validated event th_004 ('Cha-am Coast, Phetchaburi', "
        "12.794/99.984). Every /risk-map feature is a monitoring-grid site today, so "
        "this is currently a constant, but it's a real typed field (not a hardcoded "
        "frontend assumption) so it generalizes cleanly if this endpoint, or the "
        "SitePanel it feeds, ever surfaces a non-grid site type.",
    )

    # -- prediction (risk_level(), rule-based, indicative) --
    risk_level: Literal["normal", "elevated", "watch", "warning"]
    triggered_rules: list[str]
    confidence_label: str = Field(
        description="Always attached per config.yaml's prediction_confidence_label — "
        "this word never travels without its caveat."
    )

    # -- detection (detect(), high confidence) -- nested, never merged into risk_level --
    status: Literal["ok", "no_imagery", "no_water_pixels", "no_climatology", "error", "no_data_yet"]
    detected: bool | None
    anomaly_z: float | None
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
    anomaly_z: float | None
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


# --------------------------------------------------------------------------
# /validation
# --------------------------------------------------------------------------


class ValidationEventRow(BaseModel):
    """One row of the 14-event validation table. Never a percentage
    anywhere in this model or its aggregation — reported per-event."""

    event_id: str
    date_display: str
    location_name: str
    location_precision: str
    species: str
    cell_count_raw: str | None
    cell_count_representative: float | None
    matchable: bool = Field(description="True only if events.csv itself carries a lat/lng.")
    match_method: str | None
    match_reason: str | None
    low_evidentiary_weight: bool = Field(
        description="th_012/th_013/th_014 — pre-monitoring-era, no cell count in any "
        "source; shown for completeness, never averaged into a headline number with "
        "the cell-count-bearing events."
    )
    index_used: str
    anomaly_z: float | None = Field(
        description="Real satellite anomaly_z if a match was possible, else null."
    )
    flagged: bool | None = Field(
        description="Whether the (uncalibrated) threshold would have flagged this event, "
        "only when a real anomaly_z exists; else null."
    )
    notes: str

    true_color_image_url: str | None = Field(
        default=None, description="GET /satellite-image URL (true-color RGB PNG) for "
        "this event's own coordinate and the actual Sentinel-2 scene date the matching "
        "attempt used. Null unless `matchable` is true AND a real satellite reading "
        "exists (`anomaly_z` is not null) -- currently null for all 14 events, since "
        "none has produced a usable reading yet (see `calibration_caveat`). Never a "
        "placeholder image; becomes non-null automatically the moment a future event "
        "does produce one, no frontend change required."
    )
    ndci_heatmap_image_url: str | None = Field(
        default=None, description="GET /satellite-image URL (NDCI heatmap PNG) for "
        "this event. Same null rule as `true_color_image_url`."
    )


class LeaveOneOutRow(BaseModel):
    iteration_label: str
    held_out_event_ids: list[str]
    caught: bool | None = Field(description="null means the iteration could not run "
        "(no real satellite reading for any held-out member).")
    reason: str


class ValidationResponse(DisclaimerMixin):
    calibration_status: Literal["uncalibrated"] = "uncalibrated"
    calibration_caveat: str = Field(default=CALIBRATION_CAVEAT_TEXT)
    n_events: int
    n_matchable: int = Field(description="Events with a usable lat/lng in events.csv.")
    n_with_real_satellite_reading: int
    events: list[ValidationEventRow]
    leave_one_out: list[LeaveOneOutRow]
    computed_at: str = Field(description="When this (cached) calibration attempt was computed.")


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
    anomaly_z: float | None = None
    threshold_tier: Literal["elevated", "warning"] | None = None
    actual_date: str | None = Field(
        default=None, description="Real Sentinel-2 scene date behind THIS point's "
        "reading (YYYY-MM-DD) — per point, not per run. It is often older than the "
        "run's `date_used`: the nearest cloud-free scene is searched within a "
        "±10-day window, so points in one scan are routinely backed by scenes of "
        "different dates. Null when no scene was resolved for this point "
        "(`status` no_imagery / no_water_pixels / error); never substituted with "
        "`date_used`."
    )


class RegionalScanClusterSchema(BaseModel):
    centroid_lat: float
    centroid_lng: float
    cell_count: int
    mean_anomaly_z: float
    max_anomaly_z: float
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
