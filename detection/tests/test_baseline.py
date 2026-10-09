"""Pure-logic tests for detection/src/baseline.py (no GEE, no files)."""
from datetime import date, timedelta
import sys
from pathlib import Path

import pytest

# detection/src holds loose modules (see src/climatology.py's header); put it on
# sys.path so ``import baseline`` works from detection/tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import baseline as b  # noqa: E402


def _rows(start, n, value=0.05, step=5):
    d0 = date.fromisoformat(start)
    return [{"acquisition_date": (d0 + timedelta(days=i * step)).isoformat(), "ndci": value + (i % 7) * 0.002} for i in range(n)]


def test_season_months_cyclic():
    assert b.season_months(1) == (12, 1, 2)
    assert b.season_months(12) == (11, 12, 1)
    assert b.season_months(8) == (7, 8, 9)


def test_season_key_ascii():
    assert b.season_key(8) == "m08+-1"


def test_signature_stable_and_sensitive():
    p = {"collection": "COPERNICUS/S2_SR_HARMONIZED", "buffer_m": 30}
    assert b.preprocessing_signature(p) == b.preprocessing_signature(dict(reversed(list(p.items()))))
    assert b.preprocessing_signature(p) != b.preprocessing_signature({**p, "buffer_m": 31})
    assert len(b.preprocessing_signature(p)) == 16


def test_scoped_history_filters_month_and_sets_scope():
    rows = [{"acquisition_date": "2024-07-03", "ndci": 0.1}, {"acquisition_date": "2024-10-03", "ndci": 0.2}]
    out = b.scoped_history(rows, "x", 8, "sig")
    assert [r["acquisition_date"] for r in out] == ["2024-07-03"]
    assert out[0]["location_id"] == "x" and out[0]["season_key"] == "m08+-1" and out[0]["preprocessing_signature"] == "sig"
    assert "location_id" not in rows[0]  # input untouched


def test_assess_site_no_future_leakage():
    # >= 30 earlier dates fall in the season window, so the robust-z path is
    # really exercised (80 rows from 2019-06 left only 9 and always hit the floor).
    rows = _rows("2018-01-01", 400, step=7)
    # observation inside history range: only strictly earlier rows may count
    target = rows[330]["acquisition_date"]
    res = b.assess_site(rows, location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig")
    assert res["level"] is not None  # past the 30-date floor
    late = b.assess_site(rows + _rows("2030-01-01", 50, value=0.9), location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig")
    assert res == late  # later rows are invisible


def test_assess_site_insufficient_dates_reason():
    res = b.assess_site(_rows("2024-07-01", 5), location_id="x", current_ndci=0.1, actual_date="2024-08-20", target_date="2024-08-20", preprocessing_signature="sig")
    assert res["level"] is None and res["reason"] == "insufficient_independent_dates"


def test_assess_site_flags_outlier_and_respects_floor():
    rows = _rows("2018-01-01", 400, step=7)
    res = b.assess_site(rows, location_id="x", current_ndci=0.9, actual_date="2026-01-10", target_date="2026-01-12", preprocessing_signature="sig")
    assert res["level"] == "high" and res["robust_z"] >= 3


def test_self_check_shape_and_counts():
    rows = _rows("2018-01-01", 400, step=7)
    sc = b.self_check(rows, location_id="x", preprocessing_signature="sig")
    assert set(sc) == {"by_season", "total"}
    t = sc["total"]
    assert t["assessed"] + t["no_assessment"] == sum(1 for _ in rows)
    assert t["watch"] + t["high"] <= t["assessed"]


def test_self_check_counts_flagged_rows_and_unparseable_dates():
    rows = _rows("2018-01-01", 400, step=7)
    rows[350] = {**rows[350], "ndci": 0.9}  # a spike late enough to have a full season of earlier history
    rows.append({"acquisition_date": "not-a-date", "ndci": 0.1})
    sc = b.self_check(rows, location_id="x", preprocessing_signature="sig")
    t = sc["total"]
    assert t["high"] >= 1
    assert t["assessed"] + t["no_assessment"] == len(rows)
    assert t["reasons"]["invalid_acquisition_date"] == 1
    # every parseable row is counted once, in its own month's bucket
    assert sum(s["assessed"] + s["no_assessment"] for s in sc["by_season"].values()) == len(rows) - 1


def test_build_manifest_requires_a_location():
    with pytest.raises(ValueError):
        b.build_manifest(
            baseline_version="v", built_at="t", history_start="2017-01-01", history_end="2026-01-01",
            preprocessing_signature="s", preprocessing_params={}, locations={}, self_check={}, builder_git_sha=None)


def _manifest(**over):
    m = b.build_manifest(
        baseline_version="TEST-20261009-abcd1234", built_at="2026-10-09T00:00:00Z", history_start="2017-12-13", history_end="2026-10-07",
        preprocessing_signature="abcd1234abcd1234", preprocessing_params={"k": 1},
        locations={"a": {"n_dates": 300, "min_season_dates": 35, "first": "2017-12-13", "last": "2026-10-07"}, "b": {"n_dates": 280, "min_season_dates": 41, "first": "2017-12-23", "last": "2026-09-29"}},
        self_check={"total": {}}, builder_git_sha="deadbee")
    m.update(over)
    return m


def test_manifest_declares_min_over_locations():
    m = _manifest()
    assert m["baseline_kind"] == "test" and m["signal_anomaly"]["minimum_independent_dates"] == 35
    b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


@pytest.mark.parametrize("over,reason", [
    ({"baseline_kind": "prod"}, "not_test_kind"),
    ({"history_end": "2030-01-01"}, "history_in_future"),
])
def test_validate_rejects(over, reason):
    with pytest.raises(b.BaselineInvalid, match=reason):
        b.validate_manifest(_manifest(**over), live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


def test_validate_signature_mismatch():
    with pytest.raises(b.BaselineInvalid, match="signature_mismatch"):
        b.validate_manifest(_manifest(), live_signature="other", today=date(2026, 10, 9))


def test_validate_rejects_below_floor_even_if_hand_edited():
    m = _manifest()
    m["signal_anomaly"]["minimum_independent_dates"] = 5
    with pytest.raises(b.BaselineInvalid, match="below_floor"):
        b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))
    m = _manifest()
    m["signal_anomaly"]["max_observation_age_days"] = 90
    with pytest.raises(b.BaselineInvalid, match="below_floor"):
        b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


def test_validate_missing_field():
    m = _manifest(); del m["season_rule"]
    with pytest.raises(b.BaselineInvalid, match="missing_field:season_rule"):
        b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


def test_version_for():
    assert b.version_for(date(2026, 10, 9), "abcd1234ffff0000") == "TEST-20261009-abcd1234"
