"""Configured NDCI watch-overlay builder for the upper Gulf of Thailand.

Data source: the raw Earth Engine operation is re-exported through
``_data_pipeline.py``. Limitations: config.yaml holds uncalibrated product
defaults; this wrapper adds no trend or prediction interpretation.
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
    target_date: str, config: dict | None = None
) -> dict:
    """Build the NDCI watch overlay with config.yaml's approved defaults."""
    values = config or load_watch_overlay_config()
    return build_ndci_watch_overlay(
        target_date,
        threshold_z=values["threshold_z"],
        latest_window_days=values["latest_window_days"],
        baseline_years=values["baseline_years"],
        seasonal_window_days=values["seasonal_window_days"],
        min_baseline_observations=values["min_baseline_observations"],
        water_occurrence_pct=values["water_occurrence_pct"],
        gulf_seed_points=values["gulf_seed_points"],
        output_scale_m=values["output_scale_m"],
        effective_resolution_m=values["effective_resolution_m"],
        color=values["color"],
    )
