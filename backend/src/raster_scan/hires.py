"""High-resolution NDCI image of a stored raster run (Sentinel-2, per pixel).

Data source: Sentinel-2 SR via `bridge.build_index_composite` over the whole
map extent (`MAP_EXTENT`), as of the run's `date_used`, newest unmasked pixel
wins within `HIRES_MAX_SCENE_AGE_DAYS`: per-pixel cloud and water masking,
rendered by Earth Engine with the dashboard's own NDCI ramp (`NDCI_RAMP_HEX`,
`NDCI_RAMP_DOMAIN`) as a PNG thumbnail. Masked pixels (cloud in every scene
of the window, land, no coverage) are transparent. It is NDCI computed per
pixel from the scenes' red-edge and red bands, never derived from a colour
image, and never interpolated or filled.

Cached: one PNG per run under `RASTER_BLOB_ROOT/<run_id>/ndci_hires_full.png`
(a multi-minute Earth Engine render the first time, a file read afterwards).

Limitations: the thumbnail service caps the image size, so the pixel size is
the extent's longest side divided by `HIRES_DIMENSIONS` (about 80 m), coarser
than Sentinel-2's native 10 m. Pixels differ in date, up to the window's
length: each carries its own scene's value, and a cloud-filled pixel can be
months older than the run's newest scene. Small or dispersed blooms may be missed.
"""

from __future__ import annotations

import threading
import urllib.request
from pathlib import Path

from .. import _detection as bridge
from .. import _study_area
from . import storage

HIRES_DIMENSIONS = 3700  # longest side; 4000 is 54.5 MB, over Earth Engine's 48 MiB request cap
HIRES_MAX_SCENE_AGE_DAYS = 180  # cloud-masked pixels take their newest clear scene within this window
# The dashboard's whole map extent (frontend/src/utils/mapBounds.js), (south, west, north, east):
# the image covers all of it, not just the study-area polygon's box.
MAP_EXTENT = (12.06813056, 99.29500833, 13.92548889, 102.57761667)
OUTPUT_BOUNDS = [[MAP_EXTENT[0], MAP_EXTENT[1]], [MAP_EXTENT[2], MAP_EXTENT[3]]]
_DOWNLOAD_TIMEOUT_S = 600
_locks: dict[int, threading.Lock] = {}
_guard = threading.Lock()


def path_for(run_id: int) -> Path:
    return storage.RASTER_BLOB_ROOT / str(run_id) / "ndci_hires_full.png"


def _lock(run_id: int) -> threading.Lock:
    with _guard:
        return _locks.setdefault(run_id, threading.Lock())


def render(run_id: int, date_used: str, max_scene_age_days: int = HIRES_MAX_SCENE_AGE_DAYS) -> Path:
    """The cached PNG for a run (covering OUTPUT_BOUNDS), rendering it first when it does not exist.

    The composite is built over the whole map extent, newest unmasked pixel
    per location within `max_scene_age_days` of `date_used`: a pixel masked by
    cloud takes its newest clear scene in that window, so it can be older than
    the run's own scenes. Each pixel is still a real measurement, never
    interpolated; only cloud-in-every-scene, land and no-coverage stay transparent.
    Raises GEEAuthError, NoCloudFreeImageryError or NoWaterPixelsError from the
    composite, and urllib.error.URLError / OSError from the thumbnail fetch.
    """
    out = path_for(run_id)
    if out.exists():
        return out
    with _lock(run_id):
        if out.exists():
            return out
        import ee  # imported late: only this path needs Earth Engine

        south, west, north, east = MAP_EXTENT
        corners = ((south, west), (south, east), (north, east), (north, west))
        composite = bridge.build_index_composite(corners, date_used, max_scene_age_days=max_scene_age_days)
        region = ee.Geometry.Rectangle([west, south, east, north])
        low, high = bridge.NDCI_RAMP_DOMAIN
        palette = [str(h).lstrip("#") for h in bridge.NDCI_RAMP_HEX]
        image = composite["image"].select("ndci").visualize(min=low, max=high, palette=palette)
        try:
            url = image.getThumbURL({"region": region, "dimensions": HIRES_DIMENSIONS, "format": "png"})
        except ee.EEException as exc:  # e.g. request too large: a typed 502, not a 500
            raise OSError(str(exc)) from exc
        with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT_S) as response:  # noqa: S310
            data = response.read()
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
    return out
