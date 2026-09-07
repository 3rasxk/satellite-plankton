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
    "Satellite index values describe water colour at pixel resolution. "
    "Small or scattered blooms may not be visible. Sentinel-2 anomaly "
    "detection is not computed — no valid baseline exists. Index values "
    "alone establish neither bloom presence nor absence."
)

class DisclaimerMixin(BaseModel):
    disclaimer: str = Field(
        default=DISCLAIMER_TEXT,
        description="Truth-boundary caveat. Present on every response — satellite-pixel "
        "resolution, small/scattered blooms may be missed, and Sentinel-2 "
        "index values alone cannot establish bloom presence or absence.",
    )


# --------------------------------------------------------------------------
# /detect
# --------------------------------------------------------------------------


class DetectResponse(DisclaimerMixin):
    """Real Sentinel-2 index values and scene metadata. No valid anomaly
    baseline exists; detection and prediction conclusions are unavailable."""

    model_config = ConfigDict(json_schema_extra={"example": {
        "lat": 13.45, "lng": 100.65, "date": "2024-03-15",
        "status": "ok", "detected": None, "spatial_anomaly_z": None,
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
        "5-stop risk ramp) for this exact lat/lng/date. Same null rule as "
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


# --------------------------------------------------------------------------
# /regional-scan
# --------------------------------------------------------------------------

REGIONAL_SCAN_CAVEAT_TEXT = (
    "Index values only — no anomaly detection active. Real "
    "Sentinel-2 readings across the full upper Gulf study-area polygon, "
    "the same detect() pipeline /detect and /risk-map use. Spatial anomaly "
    "is not computed — no valid baseline exists. It is a "
    "separate output from the unvalidated Ang Sila spatial-trend test "
    "and must not be blurred together with it."
)


class RegionalScanPointSchema(BaseModel):
    point_id: str
    lat: float
    lng: float
    status: Literal["ok", "no_imagery", "no_water_pixels", "no_climatology", "error", "no_data_yet"] = Field(
        description="no_data_yet marks a planned sampling location with no cached reading."
    )
    index_values: dict[str, float] | None = None
    spatial_anomaly_z: float | None = Field(
        default=None, description="Not computed — no valid baseline exists."
    )
    threshold_tier: Literal["elevated", "warning"] | None = None
    actual_date: str | None = Field(
        default=None, description="Real Sentinel-2 scene date behind THIS point's "
        "reading (YYYY-MM-DD) — per point, not per run. It is often older than the "
        "run's `date_used`: each point independently takes the newest usable "
        "scene acquired on or before the target date, so dates differ across "
        "points. Never newer than `date_used`. Null when no scene was resolved for this point "
        "(`status` no_imagery / no_water_pixels / error); never substituted with "
        "`date_used`."
    )


class RegionalScanClusterSchema(BaseModel):
    centroid_lat: float
    centroid_lng: float
    cell_count: int
    mean_spatial_anomaly_z: float
    max_spatial_anomaly_z: float
    threshold_tier: Literal["elevated", "warning"]
    member_point_ids: list[str]
    oldest_scene_date: str | None = Field(
        default=None, description="Oldest Sentinel-2 scene date among this "
        "cluster's member cells (YYYY-MM-DD). Cells are merged by grid "
        "adjacency alone, never by date, so one cluster can mix scene "
        "vintages — measured spans within a single scan were 7, 5 and 10 "
        "days. Null (together with `newest_scene_date` and "
        "`scene_date_span_days`) when any member has no usable scene date; "
        "never backfilled from the run's `date_used`, which is a requested "
        "target date and not a scene date."
    )
    newest_scene_date: str | None = Field(
        default=None, description="Newest Sentinel-2 scene date among this "
        "cluster's member cells (YYYY-MM-DD). Not the same quantity as the "
        "run-level `newest_scene_date`, which is the triggering poll's max "
        "scene timestamp for the whole scan. Null under the same "
        "all-or-nothing rule as `oldest_scene_date`."
    )
    scene_date_span_days: int | None = Field(
        default=None, description="Whole days between `oldest_scene_date` and "
        "`newest_scene_date`; 0 when every member cell came from one scene "
        "date. A wide span is reported, never suppressed — the cluster is "
        "still shown in full, because splitting or filtering it on freshness "
        "would invent a spatial boundary no measurement supports. Null under "
        "the same all-or-nothing rule as `oldest_scene_date`."
    )


class RegionalScanRunMeta(BaseModel):
    run_id: int
    started_at: str
    completed_at: str | None
    status: Literal["running", "ok", "partial_error", "error"]
    grid_spacing_km: float
    date_used: str
    newest_scene_date: str | None = Field(
        description="The triggering scene poll's maximum Sentinel-2 scene "
        "acquisition timestamp for the whole run — one ISO 8601 UTC "
        "timestamp covering the entire study-area polygon, recorded when "
        "the poll decided this scan was worth running, and read back by "
        "the next poll as its comparison baseline. Not the same quantity "
        "as a cluster's `newest_scene_date`, which is a date-only "
        "(YYYY-MM-DD) maximum over one cluster's member cells, each of "
        "which resolved its own latest usable scene independently. "
        "Null when the run was not poll-triggered, or the poll found no "
        "scene in its lookback window."
    )
    total_points: int
    count_ok: int
    count_no_imagery: int
    count_no_water_pixels: int
    count_no_climatology: int
    count_error: int


class RegionalScanResponse(DisclaimerMixin):
    caveat: str = Field(default=REGIONAL_SCAN_CAVEAT_TEXT)
    grid_spacing_km: float = Field(description="Spacing of the displayed cached or planned grid.")
    max_scene_age_days: int = Field(
        description="How old a point's Sentinel-2 scene is currently allowed to be "
        "before the system reports no imagery instead. Every point takes the newest "
        "usable scene acquired on or before the scan's target date, never a later "
        "one; this number only bounds how far back that search gives up. It is the "
        "value in force right now, not proof that an older cached snapshot was "
        "produced under the same setting.",
    )
    run: RegionalScanRunMeta | None = Field(
        default=None, description="Latest scan attempt; null if no scan has started."
    )
    snapshot_date_used: str | None = Field(
        default=None, description="Target date of the scan that produced the displayed "
        "cached points. Can differ from run.date_used while a later attempt is "
        "running or failed. Null for planned coordinates with no cached snapshot.",
    )
    points: list[RegionalScanPointSchema] = Field(
        default_factory=list,
        description="Every cached scan point, without threshold filtering. Before any "
        "readings are cached, the planned grid is returned with no_data_yet and null values.",
    )
    clusters: list[RegionalScanClusterSchema] = []
