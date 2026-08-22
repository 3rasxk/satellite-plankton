"""GET /validation must never emit a percentage anywhere in its response
body (CLAUDE.md truth boundary: n=14 cannot support a percentage claim),
and `calibration_status` must read "uncalibrated" -- the real, live
finding from Phase 2 (0/14 events have a coordinate precise enough to
match a satellite reading).

`bridge.threshold_run()` makes a real, slow GEE call (the th_001
regional-proxy attempt), so it is mocked here with a payload shaped like
the real 0-matchable-events outcome documented in
detection/src/thresholds.py's own module docstring, rather than hit live
-- keeps this test fast and independent of GEE credentials, per the
per-test-file convention this suite otherwise follows."""

from __future__ import annotations

import re

from src.routers import validation as validation_router

_PERCENT_LIKE = re.compile(r"\d+(\.\d+)?\s*%")


def _fake_threshold_run_result() -> dict:
    """Mirrors the real, documented outcome: 14 events, 0 matchable (no
    events.csv row has a lat/lng), 0 with a real satellite reading (the
    one live attempt, th_001's regional proxy, returned no usable
    scene)."""
    rows = []
    for i in range(1, 15):
        event_id = f"th_{i:03d}"
        rows.append(
            {
                "event_id": event_id,
                "date_display": "2020-01-01",
                "location_name": "some named place",
                "location_precision": "named_site",
                "species": "Noctiluca scintillans",
                "cell_count": {"raw": None, "lower": None, "upper": None, "representative": None},
                "matchable": False,
                "match_method": "none",
                "match_reason": "No lat/lng in events.csv.",
                "low_weight": event_id in ("th_012", "th_013", "th_014"),
                "index_values": None,
                "z_scores": None,
                "flagged": None,
            }
        )

    return {
        "config": {"indices": {"primary": "ndci"}},
        "rows": rows,
        "n_events": 14,
        "n_matchable": 0,
        "n_with_real_reading": 0,
        "th001_proxy": None,
        "matched_pairs": [],
        "loo_results": [
            {
                "label": "th_001",
                "held_out_ids": ["th_001"],
                "caught": None,
                "reason": "no real satellite reading for any held-out member",
            }
        ],
        "sweep": {},
    }


def _walk_keys_and_values(obj):
    """Yield (is_key: bool, item) for every dict key and every leaf
    value in a JSON-decoded structure, so the scans below can tell "this
    is a field name" apart from "this is prose that's allowed to *say*
    the word percentage while explaining why one isn't reported" (the
    calibration caveat text does exactly that -- CLAUDE.md requires
    stating the truth boundary, which necessarily means using the word)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield True, key
            yield from _walk_keys_and_values(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys_and_values(item)
    else:
        yield False, obj


def test_validation_never_emits_a_percentage(client, monkeypatch):
    monkeypatch.setattr(
        validation_router.bridge, "threshold_run", _fake_threshold_run_result
    )

    resp = client.get("/validation")
    assert resp.status_code == 200
    body = resp.json()

    # No *value* anywhere in the payload is a percentage-formatted
    # number (e.g. "50%", "12.5 %") -- prose values (disclaimer,
    # calibration_caveat, notes, reason) are allowed to discuss the
    # concept in English, just never report a computed ratio as one.
    for is_key, item in _walk_keys_and_values(body):
        if is_key or not isinstance(item, str):
            continue
        assert not _PERCENT_LIKE.search(item), f"percentage-shaped value found: {item!r}"

    # No *field name* anywhere in the payload is percentage/ratio-shaped
    # -- schemas.py's ValidationResponse and its nested models
    # deliberately carry no such field (counts are plain ints, results
    # are lists, never a computed accuracy/hit-rate).
    banned_key_fragments = ("percent", "pct", "accuracy", "success_rate", "hit_rate")
    for is_key, item in _walk_keys_and_values(body):
        if not is_key:
            continue
        lowered = item.lower()
        for fragment in banned_key_fragments:
            assert fragment not in lowered, f"percentage-shaped key found: {item!r}"


def test_validation_calibration_status_is_uncalibrated(client, monkeypatch):
    monkeypatch.setattr(
        validation_router.bridge, "threshold_run", _fake_threshold_run_result
    )

    resp = client.get("/validation")
    assert resp.status_code == 200
    body = resp.json()

    assert body["calibration_status"] == "uncalibrated"
    assert body["n_events"] == 14
    assert body["n_matchable"] == 0
    assert body["n_with_real_satellite_reading"] == 0
    assert isinstance(body["events"], list) and len(body["events"]) == 14
