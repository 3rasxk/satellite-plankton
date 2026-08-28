"""
The monitored grid -- a small, fixed set of points across the upper Gulf
of Thailand that `/risk-map`, `/summary`, and the scheduler operate over.

This is NOT the validation set (`data/validation/events.csv`, 14
historical events with mostly-unrecoverable coordinates -- see
`src/_detection.py` / the `/validation` router). These are new,
deliberately chosen monitoring points, picked to be representative of the
study area CLAUDE.md §0/§4 describes (upper Gulf of Thailand, focus sites
e.g. Chonburi/Bang Saen) -- not tied to any historical bloom's exact
pixel, because (per Phase 2's finding) no historical event's location is
precise enough to derive one.

Six points, live-tested against real Sentinel-2/MODIS during this build
(2026-08-22, detect() at date 2024-03-15):
  - bangsaen              -> no_imagery on that date (no cloud-free S2 scene
                              in the search window -- a real, expected gap)
  - siracha                -> no_water_pixels (buffer catches shoreline/
                              JRC-GSW-uncovered pixels at this coastal point)
  - thachin_mouth          -> no_climatology (MODIS day-of-year window had
                              too few archive observations at this river-
                              mouth point)
  - chaophraya_mouth       -> ok (real anomaly_z returned)
  - upper_gulf_open_water  -> ok (real anomaly_z returned) -- same point
                              used as one of the two th_001 regional-proxy
                              candidates in thresholds.py
  - chaam                  -> ok (real anomaly_z returned)

Keeping the non-'ok' points in the grid deliberately, rather than swapping
in easier coordinates until everything reads 'ok': this is the honest
day-to-day shape of the system (docs/DETECTION_PLAN.md §8 "Clouds" /
"Turbid water" limitations), and /risk-map's job is to report that
plainly, not to hide it behind a curated demo grid.
"""

from __future__ import annotations

MONITORED_GRID: list[dict] = [
    {
        "site_id": "bangsaen",
        "name": "Bang Saen, Chonburi",
        "lat": 13.2600,
        "lng": 100.8800,
    },
    {
        "site_id": "siracha",
        "name": "Si Racha, Chonburi",
        "lat": 13.1600,
        "lng": 100.8800,
    },
    {
        "site_id": "thachin_mouth",
        "name": "Tha Chin River mouth, Samut Sakhon",
        "lat": 13.4200,
        "lng": 100.2700,
    },
    {
        "site_id": "chaophraya_mouth",
        "name": "Chao Phraya River mouth, Samut Prakan",
        "lat": 13.4000,
        "lng": 100.5800,
    },
    {
        "site_id": "chaam",
        "name": "Cha-am coast, Phetchaburi",
        "lat": 12.7800,
        "lng": 100.0400,
    },
    {
        "site_id": "bangpakong_mouth",
        "name": "Bang Pakong River mouth, Chachoengsao",
        "lat": 13.4200,
        "lng": 100.9000,
    },
    {
        "site_id": "pattaya",
        "name": "Pattaya Beach, Chonburi",
        "lat": 12.9400,
        "lng": 100.8400,
    },
]
