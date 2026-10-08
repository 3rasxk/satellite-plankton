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

Headless/server deploys (no interactive browser to run `earthengine
authenticate` against, e.g. a Render/Fly/Railway web service): set
`GEE_SERVICE_ACCOUNT_KEY_JSON` to the full contents of a GCP service
account's JSON key file (IAM & Admin -> Service Accounts -> Create ->
grant it Earth Engine access -> Keys -> Add key -> JSON, in the same
Cloud project as `EE_PROJECT_ID`). When set, this takes priority over the
interactive-credentials flow below. Optional — every local/dev path that
doesn't set it behaves exactly as before this option was added.
"""

from __future__ import annotations

import os
import threading
from math import isfinite

import ee
import httplib2

_initialized = False
_lock = threading.Lock()

DEFAULT_GEE_REQUEST_TIMEOUT_SECONDS = 120.0
GEE_REQUEST_TIMEOUT_ENV_VAR = "GEE_REQUEST_TIMEOUT_SECONDS"

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
    "https://code.earthengine.google.com (see .env.example).\n"
    "\n"
    "Running on a headless server with no browser to authenticate "
    "against? Set GEE_SERVICE_ACCOUNT_KEY_JSON to a GCP service account's "
    "JSON key contents instead (see this module's docstring)."
)


class GEEAuthError(RuntimeError):
    """Google Earth Engine is not authenticated or failed to initialize.

    Every public function in this package must let this propagate. It must
    never be caught and papered over with placeholder/fabricated satellite
    values — a pipeline that fails loudly here is correct; one that fakes a
    working state is not (CLAUDE.md, "Non-negotiable rules").
    """


class GEEConfigError(ValueError):
    """A GEE-related environment setting is invalid (not an auth failure).

    Subclasses ValueError so existing `except ValueError` / `pytest.raises
    (ValueError)` callers keep working. Callers map it to a configuration
    error that names the variable, never to the "run earthengine
    authenticate" advice carried by GEEAuthError.
    """


def _gee_timeout_seconds() -> float:
    """Return the validated GEE request timeout in seconds.

    Unset or blank uses DEFAULT_GEE_REQUEST_TIMEOUT_SECONDS.

    Raises:
        ValueError: the env var is not a finite positive number.
    """
    value = os.environ.get(GEE_REQUEST_TIMEOUT_ENV_VAR, "").strip()
    if not value:
        return DEFAULT_GEE_REQUEST_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(value)
    except ValueError:
        timeout_seconds = float("nan")
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise GEEConfigError(
            f"{GEE_REQUEST_TIMEOUT_ENV_VAR} must be a finite positive number, "
            f"got {value!r}"
        )
    return timeout_seconds


def initialize_ee(force: bool = False) -> None:
    """Ensure a Google Earth Engine session is initialized.

    Idempotent and thread-safe — safe to call at the top of every public
    function in `sentinel2.py`, `modis.py`, and `rainfall.py`. Pass
    force=True to re-attempt initialization within the same process (e.g.
    the human just finished `earthengine authenticate` in another
    terminal while this process was already running).

    Raises:
        GEEConfigError (a ValueError): GEE_REQUEST_TIMEOUT_SECONDS is set to a value that is not
            a finite positive number (a config error, raised before any
            Earth Engine call).
        GEEAuthError: auth is missing, expired, or the session otherwise
            fails to initialize. The message includes the fix-it steps and
            the original exception for debugging.
    """
    global _initialized
    with _lock:
        if _initialized and not force:
            return

        project = os.environ.get("EE_PROJECT_ID") or None
        # Service-account key takes priority when present -- this is the
        # only path a headless server (no browser for `earthengine
        # authenticate`) can use. Unset (the default everywhere this
        # option wasn't explicitly configured), initialize_ee() behaves
        # exactly as it did before this branch existed.
        service_account_key_json = os.environ.get("GEE_SERVICE_ACCOUNT_KEY_JSON") or None
        # A malformed timeout is a configuration error, not an auth failure:
        # parse it before the try so it is not wrapped in GEEAuthError (whose
        # fix-it text would send the user to `earthengine authenticate`).
        timeout_seconds = _gee_timeout_seconds()
        try:
            # ee.Initialize() itself downloads API discovery metadata and
            # algorithms. Give those cold-start requests a finite socket
            # timeout; ee.data.setDeadline() cannot be called until the
            # Earth Engine data module has initialized its HTTP session.
            initialization_transport = httplib2.Http(timeout=timeout_seconds)
            if service_account_key_json:
                # email is omitted deliberately -- ee.ServiceAccountCredentials
                # reads client_email out of the JSON key itself when key_data
                # is a full service-account key (see its own docstring).
                credentials = ee.ServiceAccountCredentials(key_data=service_account_key_json)
                initialize_kwargs = {
                    "credentials": credentials,
                    "project": project,
                }
            elif project:
                initialize_kwargs = {"project": project}
            else:
                initialize_kwargs = {}
            ee.Initialize(
                **initialize_kwargs,
                http_transport=initialization_transport,
            )
            # Bound every Earth Engine Cloud API request made through
            # getInfo(), getDownloadURL(), and related client methods.
            # Without this, a scheduler worker can remain blocked in an
            # SSL read after application or pytest teardown has begun.
            ee.data.setDeadline(timeout_seconds * 1000)
            # The custom httplib2 transport is needed only to bound the first
            # cold start. Re-initialize through the public API to restore
            # Earth Engine's normal requests-based transport for runtime
            # concurrency while preserving an explicit or credential-derived
            # Cloud project. The rebuild is bounded by the deadline above.
            #
            # Why two Initialize calls (earthengine-api 1.7.47, read from
            # ee/__init__.py, ee/data.py, ee/_cloud_api_utils.py): the only
            # thing that bounds the default requests transport is
            # state.deadline_ms, which _install_cloud_api_resource turns into
            # the _Http(session, timeout). The public setter, setDeadline(),
            # rebuilds the Cloud API resource and asserts a requests session
            # exists, so it fails before the first Initialize; setting the
            # deadline earlier needs the private ee.data._get_state(). A single
            # Initialize(http_transport=None) would therefore fetch discovery
            # and the algorithm list with no timeout at all. Re-initializing
            # with ee.data.initialize() alone would skip the algorithm reload
            # but reset the project to the SDK default unless we re-derive it.
            # Cost, counted offline with build_cloud_resource stubbed: six
            # discovery builds (2 per Initialize, 2 per setDeadline) and two
            # algorithm-list loads per cold start, all bounded by
            # timeout_seconds. Keep both calls unless a supported pre-init
            # deadline setter exists.
            ee.Initialize(**initialize_kwargs, http_transport=None)
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
