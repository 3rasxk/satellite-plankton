"""
backend/ configuration -- env vars only (CLAUDE.md §5: "Config via env
vars + .env.example only -- never commit secrets").

No real Supabase project exists yet (backend/.env.example has empty
SUPABASE_URL/SUPABASE_KEY/DATABASE_URL -- a real gap, not a shortcut).
`DATABASE_URL` is the single switch: unset/empty falls back to a local
SQLite file so the full DB-backed flow (schema, cache writes, scheduler)
can be built and tested now; setting `DATABASE_URL` to a real Postgres/
Supabase connection string (e.g.
`postgresql+psycopg2://...supabase.co:5432/postgres`) is the entire swap
-- nothing in `src/db.py`/`src/db_models.py` branches on "is this
sqlite". See backend/README.md "Swapping to real Supabase" for the exact
steps.
"""

from __future__ import annotations

import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]

# Load backend/.env (never committed -- see .gitignore) without adding a
# python-dotenv dependency, same minimal parser style as
# detection/src/_data_pipeline.py.
_ENV_PATH = _BACKEND_DIR / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            os.environ.setdefault(key, value)


_load_env_file(_ENV_PATH)

# SQLite stand-in DB path -- gitignored (backend/data/ in repo-root
# .gitignore). Used only when DATABASE_URL is unset/blank.
_SQLITE_PATH = _BACKEND_DIR / "data" / "app.db"
_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
_DEFAULT_DATABASE_URL = f"sqlite:///{_SQLITE_PATH}"

DATABASE_URL: str = os.environ.get("DATABASE_URL", "").strip() or _DEFAULT_DATABASE_URL
USING_SQLITE_FALLBACK: bool = DATABASE_URL == _DEFAULT_DATABASE_URL

SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "").strip()

# Scheduler refresh interval for the monitored grid (src/scheduler.py).
# Satellite data itself doesn't update faster than Sentinel-2's ~5-day
# revisit / MODIS daily composite, so a short interval doesn't buy
# fresher pixels -- default is deliberately conservative. Overridable for
# local testing (a short interval was used to prove the job fires -- see
# backend-api's build report).
SCHEDULER_ENABLED: bool = os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() not in {
    "0", "false", "no", "off",
}
SCHEDULER_INTERVAL_MINUTES: int = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "360"))


# TEST seasonal baseline switch (src/baseline_store.py, src/scientific_status.py).
# Off by default. Only the exact value `test` turns it on -- no trimming, no
# case folding, no "true"/"1" -- so a typo leaves it off rather than on. The
# gates read this module attribute at call time (tests monkeypatch it).
# Turning it on never turns on risk evaluation; see scientific_status.py.
def _parse_baseline_mode(raw: str | None) -> str:
    return "test" if raw == "test" else "off"


BASELINE_MODE: str = _parse_baseline_mode(os.environ.get("BASELINE_MODE"))

def as_aware_utc(dt):
    """SQLite round-trips DateTime(timezone=True) columns as naive
    datetimes (it doesn't actually persist tzinfo) -- every timestamp this
    codebase writes is UTC (see scheduler.py, db_models.py `_utcnow`), so
    a naive value read back from the DB is always re-interpreted as UTC,
    never local time. A real Postgres/Supabase DB preserves tzinfo, so
    this is a no-op there. Centralized here so every place that reads a
    DB timestamp (isoformat() for a response, or a timedelta comparison)
    applies the same rule instead of re-deriving it."""
    from datetime import timezone

    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# Date used for the scheduler's "current" grid refresh and any /detect,
# /risk-map call that doesn't pin an explicit date -- always real
# wall-clock UTC date, never fabricated ("today" per CLAUDE.md's
# never-fabricate rule just means "the actual current date").
def today_str() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# Raster scan (src/raster_scan/). Read scale in metres for the
# whole-polygon index composite. Measured live over the study polygon:
# 200 m -> 49,607 valid water cells, ~9.2 MB transferred, ~10 s; 100 m ->
# 196,424 cells, 36.8 MB. 200 is the default because it already resolves
# a bloom patch of a few hundred metres, and a 4x bigger transfer buys
# detail the truth boundary (CLAUDE.md §0) says must not be over-read
# anyway; 100 is available by setting this. Not a staleness setting --
# how old a contributing scene may be stays the one system-wide rule,
# SENTINEL2_MAX_SCENE_AGE_DAYS in data-pipeline.
RASTER_SCAN_SCALE_M: int = int(os.environ.get("RASTER_SCAN_SCALE_M", "200"))
# How long a run's full raster blob is kept on disk before retention
# reduces the run to its stored summary row and deletes the blob
# (src/raster_scan/storage.py). At ~2 MB per stored run a month of
# roughly-daily rasters is tens of megabytes, which is affordable; the
# limit exists so unbounded growth is a decision rather than an accident.
# The run row, its metadata and its summary are never deleted by
# retention -- only the blob is.
RASTER_RETENTION_DAYS: int = int(os.environ.get("RASTER_RETENTION_DAYS", "30"))
# Poll metadata cheaply and build a new raster only when a new candidate
# Sentinel-2 acquisition has appeared and the cooldown has elapsed. The
# legacy REGIONAL_* names are accepted as fallbacks for existing local
# .env files during this transition; new configuration uses RASTER_*.
RASTER_SCAN_POLL_INTERVAL_HOURS: int = int(os.environ.get(
    "RASTER_SCAN_POLL_INTERVAL_HOURS", os.environ.get("REGIONAL_SCAN_POLL_INTERVAL_HOURS", "3")
))
RASTER_SCAN_COOLDOWN_HOURS: int = int(os.environ.get(
    "RASTER_SCAN_COOLDOWN_HOURS", os.environ.get("REGIONAL_SCAN_COOLDOWN_HOURS", "20")
))
RASTER_SCAN_POLL_LOOKBACK_DAYS: int = int(os.environ.get(
    "RASTER_SCAN_POLL_LOOKBACK_DAYS", os.environ.get("REGIONAL_SCAN_POLL_LOOKBACK_DAYS", "10")
))
# Wall-clock budget for a first-install bootstrap search, which walks
# 15-day windows back to the Sentinel-2 SR archive start (~240 sequential
# composite+transfer round trips if no window is usable). Checked between
# windows; when exceeded the run ends status='error' with the searched span
# recorded, never as a complete search. Must stay below
# src/raster_scan/scan.py STALE_RUN_HOURS (1 h), or a second caller would
# presume the live bootstrap dead and start a concurrent one; scan.py
# refuses a value that is not.
# A non-integer value fails at import, like the other int settings above,
# but with a message that names the variable (range is checked by scan.py).
def _env_int(name: str, default: str) -> int:
    raw = os.environ.get(name, default)
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"{name}={raw!r} is not an integer; set it to a whole number "
            f"(default {default}) in backend/.env or the environment."
        ) from None


RASTER_BOOTSTRAP_BUDGET_MINUTES: int = _env_int("RASTER_BOOTSTRAP_BUDGET_MINUTES", "45")
