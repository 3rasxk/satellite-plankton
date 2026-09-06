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
SCHEDULER_INTERVAL_MINUTES: int = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "360"))

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


# Regional bloom scan (docs/superpowers/specs/2026-08-31-regional-scan-design.md
# §8). Same env-override convention as SCHEDULER_INTERVAL_MINUTES above.
REGIONAL_SCAN_GRID_SPACING_KM: float = float(os.environ.get("REGIONAL_SCAN_GRID_SPACING_KM", "5"))
REGIONAL_SCAN_POLL_INTERVAL_HOURS: int = int(os.environ.get("REGIONAL_SCAN_POLL_INTERVAL_HOURS", "3"))
REGIONAL_SCAN_COOLDOWN_HOURS: int = int(os.environ.get("REGIONAL_SCAN_COOLDOWN_HOURS", "20"))
# How old a point's imagery may be is NOT configured here: it is one
# system-wide rule owned by data-pipeline (sentinel2.py's
# DEFAULT_MAX_SCENE_AGE_DAYS / SENTINEL2_MAX_SCENE_AGE_DAYS), applying
# equally to the regional scan, /detect and the scheduler's site cache.
# backend reads the effective value through src/_detection.py rather than
# keeping a second copy that could disagree with the one actually used.
# Lookback window for the poll's own Sentinel-2 metadata query (spec §5) --
# bounds the filterDate() query cost; does not affect the cooldown/trigger
# decision itself (that compares timestamps, not window length).
REGIONAL_SCAN_POLL_LOOKBACK_DAYS: int = int(os.environ.get("REGIONAL_SCAN_POLL_LOOKBACK_DAYS", "10"))
