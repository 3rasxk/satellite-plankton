"""
Live test of the auth guard itself: this one DOES attempt a real
`ee.Initialize()` (no mocking) because the guard's entire job is to turn
that specific failure into a clean, typed error instead of a raw
stack trace. If GEE happens to be authenticated when this runs, that is
also a valid pass (see the success branch below) — this test asserts
"never a raw/uncaught exception", not "always unauthenticated".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.auth import GEEAuthError, initialize_ee, reset


def test_initialize_ee_either_succeeds_or_raises_typed_error():
    reset()  # don't reuse cached state from a previous test/process
    try:
        initialize_ee(force=True)
    except GEEAuthError as exc:
        # This is the expected path on an unauthenticated machine: a
        # clean, actionable error, not a bare ee.EEException/stack trace.
        message = str(exc)
        assert "earthengine authenticate" in message
        assert "Original error" in message  # wraps the real ee exception, doesn't hide it
    else:
        # GEE was authenticated on this machine when the test ran.
        # Nothing further to assert here beyond "did not raise".
        pass
