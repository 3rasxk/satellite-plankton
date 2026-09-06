"""
Sentinel-2 image rendering — true-color RGB and NDCI heatmap panel
thumbnails for the Gulf of Thailand Algal Bloom Monitor dashboard.

Data source: same as `sentinel2.py` — Copernicus Sentinel-2 Level-2A
surface reflectance, `COPERNICUS/S2_SR_HARMONIZED`, via Google Earth
Engine. Resolution: rendered at 10 m native band resolution, resampled by
GEE's thumbnail service to a fixed small panel size (see
`DEFAULT_IMAGE_SIZE_PX`) — this is a display product, not an
analysis-resolution image; do not use the PNG output for pixel-level
computation, only `get_sentinel2_bands`'s numeric readings are meant for
that.

Same-scene guarantee: every function here calls
`sentinel2._resolve_sentinel2_scene` — the exact same candidate search/
check loop `get_sentinel2_bands` uses — rather than running a
second, independently written resolution query. Given identical lat/lng/
date/max_scene_age_days/buffer_m/max_cloud_fraction arguments, that
function's underlying GEE query is deterministic (same collection filter
+ same acquisition-time ordering + same checks), so a
`get_true_color_image`/`get_ndci_heatmap` call and a `get_sentinel2_bands`
call made with the same arguments are guaranteed to resolve to the same
`actual_date`/scene, never a different one. Both paths run the one
backward-only rule — newest usable scene on or before the requested date
— so there is no direction for them to disagree about and no caller
carved out of the guarantee. See `sentinel2.py`'s module docstring and
`_resolve_sentinel2_scene`'s docstring for the full argument.

Visualization region vs. numeric sample region: `get_sentinel2_bands`
computes its band means over a small buffer (`DEFAULT_BUFFER_M`, ~30 m —
deliberately tight, to avoid one noisy/shore pixel dominating a scalar
reading). A thumbnail rendered over that same 30 m buffer would be a
nearly-blank 3x3-pixel image with no visual context, so the image
functions here render a wider buffer around the same point
(`DEFAULT_IMAGE_REGION_BUFFER_M`, 500 m) from the *same resolved image*.
The scene/date is identical to the numeric reading; the ground area
shown in the picture is intentionally larger than the ground area the
number was averaged over, so a human has enough surrounding context to
judge the reading (e.g. "is this near a river mouth / the shore").

Masking: the true-color and NDCI thumbnails are NOT pixel-masked for
cloud/land the way the numeric band means are — GEE's `getThumbURL`
renders every pixel in the region as-is (raw scene, potentially
including nearby shoreline, cloud, or turbid pixels within the wider
500 m thumbnail region even when the tighter 30 m numeric-sample buffer
was judged clear and water-only). This is a deliberate, documented
simplification for a glance-able dashboard thumbnail, not an oversight —
the authoritative masked reading is still the numeric one from
`get_sentinel2_bands`; the picture is context, not a second measurement.

No fabricated imagery: if `_resolve_sentinel2_scene` cannot find a
cloud-free-enough scene in the search window, or every pixel in the
sample buffer is land per the JRC Global Surface Water mask, it raises
`NoCloudFreeImageryError` / `NoWaterPixelsError` and this module lets
that propagate unchanged — no placeholder, blank, or stale-date image is
ever returned. `GEEAuthError` propagates the same way.

The color-ramp math (mapping a numeric NDCI value to one of the 5
project-standard ramp colors) and the RGB stretch math (mapping a raw
digital-number reflectance value to a displayable 0-255 channel value)
are implemented as pure functions with no `ee` calls
(`hex_to_rgb`, `linear_stretch_uint8`, `ndci_value_to_color`), mirroring
the split `sentinel2.py` already uses between pure masking math and the
GEE-calling extraction function. These pure functions reimplement, in
plain Python, the same piecewise-linear interpolation
`ee.Image.visualize(min=, max=, palette=[...])` performs server-side, so
they document (and are unit-tested against) the exact mapping the
rendered PNG is expected to show, without requiring a live GEE session
to check it.
"""

from __future__ import annotations

import math
import urllib.error
import urllib.request
from typing import Any

import ee

from .sentinel2 import (
    DEFAULT_BUFFER_M,  # noqa: F401 -- re-exported for callers that want the numeric-path default for comparison
    DEFAULT_MAX_CLOUD_FRACTION,
    _resolve_sentinel2_scene,
)

# --------------------------------------------------------------------------
# True-color RGB stretch.
# --------------------------------------------------------------------------
#
# Sentinel-2 SR digital numbers are reflectance x10000 (see indices.py /
# sentinel2.py docstrings), not directly displayable. A common Sentinel-2
# true-color convention stretches roughly 0-3000 across the 0-255 display
# range -- but that convention is tuned for general land scenes (bright
# soil, vegetation, concrete), which run far brighter than open ocean
# water. Live band values observed in this project for open Gulf of
# Thailand water (B2-B6) run ~380-560; a 0-3000 stretch would map 500 to
# 500/3000 = 17% brightness, rendering water scenes as nearly black on a
# small dashboard thumbnail. TRUE_COLOR_MAX is set narrower than the
# generic land convention, calibrated to this project's own observed
# range: 1500 keeps headroom above the highest observed open-water values
# (560) and above typically-brighter near-shore/turbid/sediment pixels,
# while making a mid-500s water value render at ~33-37% brightness --
# visibly water-colored rather than crushed to near-black. This is a
# cosmetic display choice for human legibility, not a detected value or a
# calibrated radiometric product.
TRUE_COLOR_MIN = 0
TRUE_COLOR_MAX = 1500
TRUE_COLOR_BANDS = ("B4", "B3", "B2")  # red, green, blue

# --------------------------------------------------------------------------
# NDCI heatmap color ramp.
# --------------------------------------------------------------------------
#
# Exact hex colors already established for risk elsewhere in this project
# (docs/FRONTEND_PLAN.md §4, frontend/src/constants.js RISK_COLOR_HEX /
# NO_DATA_HEX) -- reused verbatim, in the same low-to-high order, so a
# heatmap thumbnail reads as the same visual language as the map markers
# and risk colors elsewhere in the app, not a new arbitrary palette.
NDCI_RAMP_HEX: tuple[str, str, str, str, str] = (
    "#0A1929",  # deep water / lowest NDCI -- frontend --deep
    "#2E86AB",  # clear water, low chlorophyll -- frontend --clear
    "#48C9A9",  # elevated -- frontend --elevated
    "#E8C547",  # bloom likely -- frontend --bloom
    "#D64545",  # severe bloom / highest NDCI -- frontend --severe
)

# Domain the 5 ramp stops are spread evenly across. Real NDCI values seen
# live in this project so far are small, roughly 0.02-0.09 for non-bloom
# open water (see detection/src/indices.py's ndci()). The generic
# published NDCI range for chlorophyll retrieval spans roughly -1 to 1
# (practically -0.5 to 0.5 over water), but spreading the 5 ramp stops
# across that full literature range would put realistic non-bloom
# readings (0.02-0.09) all within a few percent of the domain's midpoint
# -- visually indistinguishable, defeating the point of a heatmap. This
# domain is chosen narrower, so the range actually observed carries real
# visual dynamic range:
#   -0.05 -> deep/lowest color (a small negative allowance below the
#            observed floor, since NDCI can legitimately dip slightly
#            negative over very clear water)
#    0.15 -> highest/severe color (well above the observed non-bloom
#            ceiling of ~0.09, leaving headroom so an actual elevated
#            reading has room to visibly shift toward "bloom"/"severe"
#            rather than immediately pinning to the top of the ramp)
# This is a cosmetic visualization domain, not a detection threshold --
# it is entirely independent of the z-score anomaly cutoffs in
# detection/src/config.yaml, which operate on anomaly vs. MODIS
# climatology, not on this raw single-scene NDCI value.
NDCI_RAMP_DOMAIN: tuple[float, float] = (-0.05, 0.15)

# --------------------------------------------------------------------------
# Image size.
# --------------------------------------------------------------------------
#
# GEE getThumbURL's `dimensions` scales the longest side of the requested
# region's bounding box to this many pixels (aspect ratio preserved). 480
# sits in the middle of the "400-512px on the long side" range appropriate
# for a small dashboard site-panel thumbnail meant for a human to glance
# at, not for further pixel-level analysis -- large enough to show visible
# water/near-shore structure at DEFAULT_IMAGE_REGION_BUFFER_M's ground
# extent, small enough to stay a quick, cheap fetch (this is a thumbnail
# render request, not a full-resolution tile export).
DEFAULT_IMAGE_SIZE_PX = 480

# Wider than sentinel2.DEFAULT_BUFFER_M (30 m, tuned for a tight, low-noise
# *numeric* sample) -- see module docstring "Visualization region vs.
# numeric sample region" above.
DEFAULT_IMAGE_REGION_BUFFER_M = 500

DEFAULT_THUMB_TIMEOUT_S = 30


# --------------------------------------------------------------------------
# Pure functions — no `ee` calls, unit-testable with plain values.
# --------------------------------------------------------------------------


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """"#RRGGBB" -> (r, g, b) integer tuple, 0-255 each.

    Pure function, no GEE dependency. Raises ValueError on a malformed
    hex string (not a silent best-effort parse) since a bad ramp color
    would otherwise render as a wrong or blank pixel with no clear cause.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Expected '#RRGGBB', got {hex_color!r}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def linear_stretch_uint8(value: float, vmin: float, vmax: float) -> int:
    """Linear min-max stretch of one raw digital-number value to a
    displayable 0-255 channel value, clamped at both ends.

    Pure function mirroring, per-channel, what
    `ee.Image.visualize(min=vmin, max=vmax)` does server-side for the
    true-color render -- reimplemented here so the stretch is documented
    and unit-testable without a live GEE session.

    Raises:
        ValueError: vmax <= vmin (a degenerate/invalid domain).
    """
    if vmax <= vmin:
        raise ValueError(f"vmax ({vmax}) must be > vmin ({vmin})")
    t = (value - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    return int(round(t * 255))


def ndci_value_to_color(
    value: float,
    domain: tuple[float, float] = NDCI_RAMP_DOMAIN,
    stops_hex: tuple[str, ...] = NDCI_RAMP_HEX,
) -> tuple[int, int, int]:
    """Map a single NDCI value to an (r, g, b) color by piecewise-linear
    interpolation across `stops_hex`, evenly spaced across `domain`.

    Pure function reimplementing, in plain Python, the same algorithm
    `ee.Image.visualize(min=, max=, palette=[...])` performs server-side
    for the NDCI heatmap render -- so the exact mapping the rendered PNG
    is expected to show is documented and unit-testable without a live
    GEE session. Values outside `domain` clamp to the first/last stop
    color (matching GEE's `visualize` clamping behavior), rather than
    extrapolating past the defined ramp.

    Raises:
        ValueError: domain's max <= min, or fewer than 2 stops given.
    """
    vmin, vmax = domain
    if vmax <= vmin:
        raise ValueError(f"domain max ({vmax}) must be > domain min ({vmin})")
    if len(stops_hex) < 2:
        raise ValueError("Need at least 2 ramp stops to interpolate between")

    stops_rgb = [hex_to_rgb(h) for h in stops_hex]
    n = len(stops_rgb)

    t = (value - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))

    scaled = t * (n - 1)
    i = int(math.floor(scaled))
    if i >= n - 1:
        return stops_rgb[-1]
    frac = scaled - i
    c0, c1 = stops_rgb[i], stops_rgb[i + 1]
    return tuple(round(c0[k] + (c1[k] - c0[k]) * frac) for k in range(3))  # type: ignore[return-value]


# --------------------------------------------------------------------------
# GEE-backed rendering.
# --------------------------------------------------------------------------


def _fetch_thumb_bytes(url: str, timeout_s: float = DEFAULT_THUMB_TIMEOUT_S) -> bytes:
    """Fetch a GEE thumbnail URL's actual PNG bytes server-side.

    Per this project's convention (`.claude/agents/satellite-data.md`:
    "You own the only code in this project allowed to talk to Google
    Earth Engine"), only `data-pipeline` fetches from GEE-hosted URLs --
    `getThumbURL` alone would leave a live, time-limited signed URL for a
    downstream caller (backend-api) to fetch, which both violates that
    boundary and would break if the caller fetched it after the URL's
    expiry. This uses the standard library (`urllib`) rather than adding
    a new HTTP dependency the rest of `data-pipeline` doesn't otherwise
    need.

    Note: a network failure here (`urllib.error.URLError`/`HTTPError`)
    propagates as-is, unwrapped -- it is a distinct failure mode from GEE
    auth/imagery-availability (which already have typed errors:
    `GEEAuthError`, `NoCloudFreeImageryError`, `NoWaterPixelsError`) and
    this project has not defined a typed error for "the scene resolved
    fine but the thumbnail HTTP fetch itself failed."
    """
    with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310 -- GEE-issued thumbnail URL, not user input
        return response.read()


def get_true_color_image(
    lat: float,
    lng: float,
    date: str,
    max_scene_age_days: int | None = None,
    buffer_m: int = DEFAULT_BUFFER_M,
    max_cloud_fraction: float = DEFAULT_MAX_CLOUD_FRACTION,
    image_region_buffer_m: int = DEFAULT_IMAGE_REGION_BUFFER_M,
    image_size_px: int = DEFAULT_IMAGE_SIZE_PX,
) -> dict[str, Any]:
    """True-color (B4/B3/B2) PNG thumbnail of the same resolved Sentinel-2
    scene `get_sentinel2_bands(lat, lng, date, ...)` would return numeric
    bands for.

    Args:
        lat, lng, date, max_scene_age_days, buffer_m, max_cloud_fraction:
            identical meaning to `get_sentinel2_bands` -- pass the same
            values as a paired numeric call to guarantee the same
            resolved scene (see module docstring, "Same-scene guarantee").
        image_region_buffer_m: radius (metres) of the wider region
            rendered for visual context (default 500 m; see module
            docstring, "Visualization region vs. numeric sample region").
            Independent of `buffer_m`, which only affects the numeric
            water/cloud sample and candidate cloud-fraction check.
        image_size_px: long-side pixel size of the returned PNG (default
            480 -- see `DEFAULT_IMAGE_SIZE_PX`).

    Returns:
        {
            "image_bytes": bytes,       # raw PNG bytes (see module note below)
            "image_format": "png",
            "actual_date": str,         # same value get_sentinel2_bands would return
            "cloud_fraction": float,    # same value get_sentinel2_bands would return
            "stretch_min": int,
            "stretch_max": int,
        }
        `image_bytes` is raw `bytes`, not base64 -- this is an internal
        Python return value for other `data-pipeline`/backend-api code in
        the same process, and base64 is a JSON-serialization concern that
        belongs to whichever layer turns this into an HTTP response
        (this project's convention: only the API layer encodes for
        transport, data-pipeline returns native Python values).

    Raises:
        GEEAuthError: GEE not authenticated.
        NoCloudFreeImageryError: no image in the window met the cloud
            threshold.
        NoWaterPixelsError: the numeric sample buffer is entirely land
            per the JRC GSW mask.
    """
    resolved = _resolve_sentinel2_scene(
        lat, lng, date, max_scene_age_days, buffer_m, max_cloud_fraction
    )
    image = resolved["image"]
    point = ee.Geometry.Point([lng, lat])
    render_region = point.buffer(image_region_buffer_m)

    vis_image = image.select(list(TRUE_COLOR_BANDS)).visualize(
        min=TRUE_COLOR_MIN, max=TRUE_COLOR_MAX
    )
    url = vis_image.getThumbURL(
        {"region": render_region, "dimensions": image_size_px, "format": "png"}
    )
    image_bytes = _fetch_thumb_bytes(url)

    return {
        "image_bytes": image_bytes,
        "image_format": "png",
        "actual_date": resolved["actual_date"],
        "cloud_fraction": resolved["cloud_fraction"],
        "stretch_min": TRUE_COLOR_MIN,
        "stretch_max": TRUE_COLOR_MAX,
    }


def get_ndci_heatmap(
    lat: float,
    lng: float,
    date: str,
    max_scene_age_days: int | None = None,
    buffer_m: int = DEFAULT_BUFFER_M,
    max_cloud_fraction: float = DEFAULT_MAX_CLOUD_FRACTION,
    image_region_buffer_m: int = DEFAULT_IMAGE_REGION_BUFFER_M,
    image_size_px: int = DEFAULT_IMAGE_SIZE_PX,
) -> dict[str, Any]:
    """NDCI heatmap PNG thumbnail of the same resolved Sentinel-2 scene
    `get_sentinel2_bands(lat, lng, date, ...)` would return numeric bands
    for, colored with this project's standard 5-stop risk ramp.

    NDCI is computed per-pixel as (B5-B4)/(B5+B4) -- the same formula
    `detection/src/indices.py`'s `ndci()` uses on the scalar band means,
    here evaluated across the image via `ee.Image.normalizedDifference`
    instead of on the single averaged reading.

    Args:
        lat, lng, date, max_scene_age_days, buffer_m, max_cloud_fraction,
        image_region_buffer_m, image_size_px: see `get_true_color_image`.

    Returns:
        {
            "image_bytes": bytes,       # raw PNG bytes, see get_true_color_image note
            "image_format": "png",
            "actual_date": str,
            "cloud_fraction": float,
            "ramp_domain": (float, float),   # NDCI_RAMP_DOMAIN used
            "ramp_hex": (str, str, str, str, str),  # NDCI_RAMP_HEX used, low->high
        }

    Raises:
        GEEAuthError: GEE not authenticated.
        NoCloudFreeImageryError: no image in the window met the cloud
            threshold.
        NoWaterPixelsError: the numeric sample buffer is entirely land
            per the JRC GSW mask.
    """
    resolved = _resolve_sentinel2_scene(
        lat, lng, date, max_scene_age_days, buffer_m, max_cloud_fraction
    )
    image = resolved["image"]
    point = ee.Geometry.Point([lng, lat])
    render_region = point.buffer(image_region_buffer_m)

    ndci_image = image.normalizedDifference(["B5", "B4"])
    vis_image = ndci_image.visualize(
        min=NDCI_RAMP_DOMAIN[0], max=NDCI_RAMP_DOMAIN[1], palette=list(NDCI_RAMP_HEX)
    )
    url = vis_image.getThumbURL(
        {"region": render_region, "dimensions": image_size_px, "format": "png"}
    )
    image_bytes = _fetch_thumb_bytes(url)

    return {
        "image_bytes": image_bytes,
        "image_format": "png",
        "actual_date": resolved["actual_date"],
        "cloud_fraction": resolved["cloud_fraction"],
        "ramp_domain": NDCI_RAMP_DOMAIN,
        "ramp_hex": NDCI_RAMP_HEX,
    }
