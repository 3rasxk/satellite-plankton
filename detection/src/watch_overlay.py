"""Configured NDCI watch-overlay builder for the upper Gulf of Thailand.

Data source: the raw Earth Engine operation is re-exported through
``_data_pipeline.py``. Limitations: config.yaml holds uncalibrated product
defaults for the regional Sentinel-2 trend and raster-SST overlay; it does
not alter the separate point-prediction pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _data_pipeline import build_ndci_watch_overlay  # noqa: E402

CONFIG_PATH = _THIS_DIR / "config.yaml"


def load_watch_overlay_config() -> dict:
    """Load the approved NDCI watch-overlay operating defaults."""
    with open(CONFIG_PATH) as config_file:
        return yaml.safe_load(config_file)["ndci_watch_overlay"]


def build_configured_ndci_watch_overlay(
    target_date: str,
    monitoring_sites: list[dict],
    config: dict | None = None,
) -> dict:
    """Build the regional NDCI overlay with every approved operating value."""
    values = config or load_watch_overlay_config()
    return build_ndci_watch_overlay(
        target_date,
        monitoring_sites=monitoring_sites,
        **{key: values[key] for key in (
            "threshold_z", "warning_threshold_z", "latest_window_days",
            "baseline_years", "seasonal_window_days", "min_baseline_observations",
            "trend_window_days", "min_trend_observations", "sst_search_window_days",
            "sst_climatology_window_days", "sst_resolution_m", "water_occurrence_pct",
            "gulf_seed_points", "output_scale_m", "effective_resolution_m", "level_colors",
        )},
    )
