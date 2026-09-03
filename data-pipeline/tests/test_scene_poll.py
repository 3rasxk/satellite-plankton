"""Import-only test for scene_poll.py -- get_newest_scene_timestamp()
itself requires a live GEE session (it calls initialize_ee()), so it is
not exercised here (no fixture in this suite fakes `ee`, matching the
rest of this project's "GEE-touching functions are exercised live during
manual builds, not against a mocked ee" convention -- see
data-pipeline/README.md). This test only proves the module is importable
and its signature is what the detection/backend bridges expect."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scene_poll import get_newest_scene_timestamp


def test_get_newest_scene_timestamp_signature():
    sig = inspect.signature(get_newest_scene_timestamp)
    assert list(sig.parameters) == ["polygon_latlng", "since_date"]
