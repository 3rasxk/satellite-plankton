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


class RasterScanResponse(DisclaimerMixin):
    """Metadata for the newest raster overlay still present on disk.

    The image itself is fetched separately from `overlay_url`; this
    payload stays small enough to poll. Every field is null when no
    overlay has been rendered -- there is no placeholder raster, because
    an empty overlay drawn over the study area would assert "we looked
    and saw nothing", which is not the same as "we have not looked".
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
        "drift from it. Includes the no-data hatch, which marks water that was NOT measured -- "
        "never a low reading.")
    overlay_url: str | None = Field(default=None, description="Where to fetch the PNG.")
    stale_run_id: int | None = Field(
        default=None, description="Set when a newer run exists whose overlay is not on disk "
        "(running, failed, or expired). The served picture is older than the newest attempt.")
    reason: str | None = Field(
        default=None, description="Why no overlay is being served, when there is none.")


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
