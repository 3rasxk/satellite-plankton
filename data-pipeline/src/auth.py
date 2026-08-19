"""
Google Earth Engine authentication guard.

Data source: N/A — this module manages the GEE session used by every other
module in this package (`sentinel2.py`, `modis.py`, `rainfall.py`); it does
not itself pull imagery.
Resolution: N/A.
Limitation: GEE now requires a registered Cloud project for most accounts
(`ee.Initialize(project=...)`), not just the legacy anonymous flow. Set
`EE_PROJECT_ID` in `data-pipeline/.env` (see `.env.example`) if your account
needs it. SSL certificate errors during `earthengine authenticate` mean the
active Python resolves to a non-system toolchain (e.g. a PlatformIO/Arduino
bundled Python with an old LibreSSL build) — see CLAUDE.md §4.1 and
`data-pipeline/README.md`. Do not work around this silently; the fix is to
use the Homebrew/system Python that ships current OpenSSL.

Every public function in `sentinel2.py`, `modis.py`, and `rainfall.py` calls
`initialize_ee()` before making any GEE request. If auth is missing or
initialization fails for any reason, this raises `GEEAuthError` with an
actionable fix-it message — callers must let it propagate rather than
catching it and substituting fabricated data.
"""

from __future__ import annotations

import os
import threading

import ee

_initialized = False
_lock = threading.Lock()

FIX_IT_MESSAGE = (
    "Google Earth Engine is not authenticated (or the session failed to "
    "initialize).\n"
    "Fix:\n"
    "  1. cd data-pipeline\n"
    "  2. /opt/homebrew/bin/python3 -m venv venv   # if venv doesn't exist yet\n"
    "  3. source venv/bin/activate\n"
    "  4. pip install -r requirements.txt\n"
    "  5. earthengine authenticate\n"
    "\n"
    "If step 5 fails with an SSL certificate error: the `python3` on PATH "
    "is resolving to a non-system toolchain (e.g. PlatformIO/Arduino, which "
    "bundles an old LibreSSL). Run `which python3` to check. Recreate the "
    "venv with /opt/homebrew/bin/python3 instead (confirmed clean on this "
    "machine: OpenSSL 3.x). Do not silently work around this — see "
    "CLAUDE.md §4.1.\n"
    "\n"
    "Newer GEE accounts also require a registered Cloud project: set "
    "EE_PROJECT_ID in data-pipeline/.env to the project id registered at "
    "https://code.earthengine.google.com (see .env.example)."
)


class GEEAuthError(RuntimeError):
    """Google Earth Engine is not authenticated or failed to initialize.

    Every public function in this package must let this propagate. It must
    never be caught and papered over with placeholder/fabricated satellite
    values — a pipeline that fails loudly here is correct; one that fakes a
    working state is not (CLAUDE.md, "Non-negotiable rules").
    """


def initialize_ee(force: bool = False) -> None:
    """Ensure a Google Earth Engine session is initialized.

    Idempotent and thread-safe — safe to call at the top of every public
    function in `sentinel2.py`, `modis.py`, and `rainfall.py`. Pass
    force=True to re-attempt initialization within the same process (e.g.
    the human just finished `earthengine authenticate` in another
    terminal while this process was already running).

    Raises:
        GEEAuthError: auth is missing, expired, or the session otherwise
            fails to initialize. The message includes the fix-it steps and
            the original exception for debugging.
    """
    global _initialized
    with _lock:
        if _initialized and not force:
            return

        project = os.environ.get("EE_PROJECT_ID") or None
        try:
            if project:
                ee.Initialize(project=project)
            else:
                ee.Initialize()
            # ee.Initialize() can succeed even with a stale/invalid
            # credential file — it only builds the client, it does not
            # necessarily contact the server. Force one cheap round-trip
            # so a bad or missing credential surfaces here, not on the
            # caller's first real (and much more expensive) request.
            ee.Number(1).getInfo()
        except Exception as exc:  # noqa: BLE001 - deliberately broad; re-raised as a typed error
            _initialized = False
            raise GEEAuthError(
                f"{FIX_IT_MESSAGE}\n\nOriginal error ({type(exc).__name__}): {exc}"
            ) from exc

        _initialized = True


def reset() -> None:
    """Test/debug hook: forget cached initialization state.

    Not called by normal pipeline code. Useful for a long-lived process
    (or an interactive session) to re-check auth after the human runs
    `earthengine authenticate` without restarting the interpreter.
    """
    global _initialized
    with _lock:
        _initialized = False
