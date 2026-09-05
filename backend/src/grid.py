"""
The monitored grid -- a small, fixed set of points across the upper Gulf
of Thailand that `/risk-map`, `/summary`, and the scheduler operate over.

This is NOT the validation set (`data/validation/events.csv`, 14
historical events, seven with recorded coordinates -- see
`src/_detection.py` / the `/validation` router). These are new,
deliberately chosen monitoring points, picked to be representative of the
study area CLAUDE.md §0/§4 describes (upper Gulf of Thailand, focus sites
e.g. Chonburi/Bang Saen) -- not tied to any historical bloom's exact
pixel. The validation coordinates remain separate from this monitoring grid.

Seven points. Five of them were live-tested against real Sentinel-2/MODIS
during this build (2026-08-22, detect() at date 2024-03-15):
  - bangsaen              -> no_imagery on that date (no cloud-free S2 scene
                              in the search window -- a real, expected gap)
  - siracha                -> no_water_pixels (buffer catches shoreline/
                              JRC-GSW-uncovered pixels at this coastal point)
  - thachin_mouth          -> formerly no_climatology (MODIS day-of-year window had
                              too few archive observations at this river-
                              mouth point)
  - chaophraya_mouth       -> Sentinel-2 index reading available
  - chaam                  -> Sentinel-2 index reading available

Those historical statuses are not current detection results. The former
anomaly values mixed incompatible units and are withdrawn; detect() now
returns index readings and scene dates without consulting climatology.

bangpakong_mouth and pattaya were added later (commit b15af00) and were
NOT part of that 2026-08-22 live test -- no per-site result is claimed
for them here rather than one being assumed from the others.

A sixth site, upper_gulf_open_water, was in this grid when the list above
was written and has since been removed. thresholds.py still defines its
own upper_gulf_open_water_1/_2 regional-proxy coordinates for th_001;
those are hardcoded there and never read from this module, so they are
unaffected by that removal.

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
