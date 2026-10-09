"""Pure-logic tests for detection/src/baseline.py (no GEE, no files)."""
from datetime import date, timedelta
import hashlib
import json
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
    # history cut exactly at the target row (rows[:330] ends the day before it) must give the identical result:
    # the observation's own same-date row is not part of its baseline either
    assert res == b.assess_site(rows[:330], location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig")


def test_assess_site_same_date_rows_never_self_include():
    rows = _rows("2018-01-01", 400, step=7)
    target = rows[330]["acquisition_date"]
    base = b.assess_site(rows[:330], location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig")
    assert base["level"] is not None
    # a duplicate-date row with an extreme (but valid) value on the observation's own date must not count
    dup = rows + [{"acquisition_date": target, "ndci": 0.99}]
    assert b.assess_site(dup, location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig") == base
    # ... nor may a later-dated row inside the same seasonal window
    next_day = (date.fromisoformat(target) + timedelta(days=1)).isoformat()
    later = rows[:330] + [{"acquisition_date": next_day, "ndci": 0.99}]
    assert b.assess_site(later, location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig") == base


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


def test_scoped_history_never_relabels_other_location():
    rows = [
        {"acquisition_date": "2024-07-03", "ndci": 0.1},                          # untagged -> stamped
        {"acquisition_date": "2024-07-04", "ndci": 0.2, "location_id": "x"},      # same location -> kept
        {"acquisition_date": "2024-07-05", "ndci": 0.3, "location_id": "other"},  # other location -> dropped
        {"acquisition_date": "2024-07-06", "ndci": 0.4, "location_id": None},     # None counts as missing -> stamped
    ]
    out = b.scoped_history(rows, "x", 8, "sig")
    assert [r["acquisition_date"] for r in out] == ["2024-07-03", "2024-07-04", "2024-07-06"]
    assert all(r["location_id"] == "x" and r["season_key"] == "m08+-1" and r["preprocessing_signature"] == "sig" for r in out)
    assert rows[2]["location_id"] == "other" and "season_key" not in rows[0]  # inputs untouched


def test_scoped_history_drops_rows_tagged_for_another_season():
    rows = [{"acquisition_date": "2024-07-03", "ndci": 0.1, "season_key": "m09+-1"}]
    assert b.scoped_history(rows, "x", 8, "sig") == []


def test_scoped_history_keeps_foreign_signature_tag():
    rows = [{"acquisition_date": "2024-07-03", "ndci": 0.1, "preprocessing_signature": "old"},
            {"acquisition_date": "2024-07-04", "ndci": 0.2}]
    out = b.scoped_history(rows, "x", 8, "sig")
    assert [r["preprocessing_signature"] for r in out] == ["old", "sig"]


def test_assess_site_reports_incompatible_preprocessing_for_old_signature_rows():
    rows = [{**r, "preprocessing_signature": "old"} for r in _rows("2018-01-01", 400, step=7)]
    res = b.assess_site(rows, location_id="x", current_ndci=0.5, actual_date="2026-01-10", target_date="2026-01-12", preprocessing_signature="sig")
    assert res["level"] is None and res["reason"] == "incompatible_preprocessing"
    # mixed: the old-signature rows are ignored, the untagged ones (re-stamped) still count
    mixed = rows[:200] + _rows("2018-01-02", 400, step=7)
    ok = b.assess_site(mixed, location_id="x", current_ndci=0.5, actual_date="2026-01-10", target_date="2026-01-12", preprocessing_signature="sig")
    only_new = b.assess_site(_rows("2018-01-02", 400, step=7), location_id="x", current_ndci=0.5, actual_date="2026-01-10", target_date="2026-01-12", preprocessing_signature="sig")
    assert ok["level"] is not None and ok == only_new


def test_assess_site_ignores_rows_of_other_locations():
    rows = [{**r, "location_id": "other"} for r in _rows("2018-01-01", 400, step=7)]
    res = b.assess_site(rows, location_id="x", current_ndci=0.5, actual_date="2026-01-10", target_date="2026-01-12", preprocessing_signature="sig")
    assert res["level"] is None and res["reason"] == "insufficient_independent_dates" and res["independent_date_count"] == 0


def _dated_months(*months, years=(2023, 2024)):
    return [{"acquisition_date": f"{y}-{m:02d}-15", "ndci": 0.1} for y in years for m in months]


def test_scoped_history_year_wrap_january():
    rows = _dated_months(11, 12, 1, 2, 3)
    kept = {r["acquisition_date"][5:7] for r in b.scoped_history(rows, "x", 1, "sig")}
    assert kept == {"12", "01", "02"}  # Dec and Feb in, Nov and Mar out


def test_scoped_history_year_wrap_december():
    rows = _dated_months(10, 11, 12, 1, 2)
    kept = {r["acquisition_date"][5:7] for r in b.scoped_history(rows, "x", 12, "sig")}
    assert kept == {"11", "12", "01"}  # Nov and Jan in, Oct and Feb out


def test_assess_site_season_comes_from_target_date_not_actual_date():
    # History only in March. target_date (Feb) has a Jan..Mar window; actual_date (Jan) would have Dec..Feb.
    d0 = date(2024, 3, 1)
    rows = [{"acquisition_date": (d0 + timedelta(days=i)).isoformat(), "ndci": 0.05 + (i % 7) * 0.002} for i in range(31)]
    rows += [{"acquisition_date": f"2025-03-{i + 1:02d}", "ndci": 0.05 + (i % 7) * 0.002} for i in range(10)]
    res = b.assess_site(rows, location_id="x", current_ndci=0.5, actual_date="2026-01-30", target_date="2026-02-02", preprocessing_signature="sig")
    assert res["level"] is not None and res["independent_date_count"] == 41
    # same observation targeted at January has no March in its window
    res_jan = b.assess_site(rows, location_id="x", current_ndci=0.5, actual_date="2026-01-30", target_date="2026-01-31", preprocessing_signature="sig")
    assert res_jan["level"] is None and res_jan["independent_date_count"] == 0


def test_preprocessing_signature_golden_digest():
    params = {"collection": "COPERNICUS/S2_SR_HARMONIZED", "buffer_m": 30, "nested": {"label": "\u0e17\u0e30\u0e40\u0e25", "scale": 0.1, "list": [1, 2.5]}}
    canonical = '{"buffer_m":30,"collection":"COPERNICUS/S2_SR_HARMONIZED","nested":{"label":"\\u0e17\\u0e30\\u0e40\\u0e25","list":[1,2.5],"scale":0.1}}'
    assert json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=True) == canonical  # canonical form is pinned
    assert hashlib.sha256(canonical.encode("ascii")).hexdigest()[:16] == "fc987d8ba3dc1c11"
    assert b.preprocessing_signature(params) == "fc987d8ba3dc1c11"


def test_self_check_row_outcomes_use_only_strictly_earlier_rows(monkeypatch):
    """Per-row spy: each replayed row equals an assessment on the history cut just before it."""
    rows = _rows("2018-01-01", 400, step=7)
    k = 300

    def per_row(data):
        seen = []
        real = b.assess_site

        def spy(*args, **kwargs):
            seen.append(real(*args, **kwargs))
            return seen[-1]

        monkeypatch.setattr(b, "assess_site", spy)
        try:
            b.self_check(data, location_id="x", preprocessing_signature="sig")
        finally:
            monkeypatch.setattr(b, "assess_site", real)
        return seen

    original = per_row(rows)
    assert len(original) == len(rows)
    # (1) rewriting every later row (even to extreme values) cannot change an earlier row's outcome
    mutated = rows[:k] + [{**r, "ndci": 0.95} for r in rows[k:]]
    assert per_row(mutated)[:k] == original[:k]
    # (2) each row equals an independent assessment against only the rows before it (never itself)
    for i in (150, 250, 299, 399):
        cut = b.assess_site(rows[:i], location_id="x", current_ndci=rows[i]["ndci"], actual_date=rows[i]["acquisition_date"],
                            target_date=rows[i]["acquisition_date"], preprocessing_signature="sig")
        assert original[i] == cut
    assert any(r["level"] is not None for r in original[150:])  # the assessed path is really exercised


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


_LIVE = "abcd1234abcd1234"
_TODAY = date(2026, 10, 9)


@pytest.mark.parametrize("name,value", [
    ("minimum_independent_dates", float("nan")),
    ("minimum_independent_dates", float("inf")),
    ("max_observation_age_days", float("nan")),
    ("max_observation_age_days", float("inf")),
    ("minimum_independent_dates", True),
    ("minimum_independent_dates", "35"),
])
def test_validate_rejects_non_finite_or_non_numeric_floors(name, value):
    m = _manifest()
    m["signal_anomaly"][name] = value
    with pytest.raises(b.BaselineInvalid, match="below_floor"):
        b.validate_manifest(m, live_signature=_LIVE, today=_TODAY)


def test_validate_rejects_season_rule_mismatch():
    with pytest.raises(b.BaselineInvalid, match="season_rule_mismatch"):
        b.validate_manifest(_manifest(season_rule="calendar-month window, target month only"), live_signature=_LIVE, today=_TODAY)


def test_validate_rejects_inactive_declaration():
    m = _manifest()
    m["signal_anomaly"]["status"] = "inactive_no_consistent_sentinel2_baseline"
    with pytest.raises(b.BaselineInvalid, match="inactive_declaration"):
        b.validate_manifest(m, live_signature=_LIVE, today=_TODAY)


@pytest.mark.parametrize("name,value", [
    ("mad_scale", 1.0),
    ("watch_at_z", 1.5),
    ("high_at_z", 2.5),
    ("high_at_z", float("nan")),
])
def test_validate_rejects_changed_thresholds(name, value):
    m = _manifest()
    m["signal_anomaly"][name] = value
    with pytest.raises(b.BaselineInvalid, match="threshold_mismatch"):
        b.validate_manifest(m, live_signature=_LIVE, today=_TODAY)


@pytest.mark.parametrize("name", ["preprocessing_signature", "baseline_version"])
def test_validate_rejects_inconsistent_nested_declaration(name):
    m = _manifest()
    m["signal_anomaly"][name] = "something-else"
    with pytest.raises(b.BaselineInvalid, match="inconsistent_declaration"):
        b.validate_manifest(m, live_signature=_LIVE, today=_TODAY)


@pytest.mark.parametrize("name", ["status", "mad_scale", "watch_at_z", "high_at_z", "preprocessing_signature", "baseline_version"])
def test_validate_requires_full_declaration(name):
    m = _manifest()
    del m["signal_anomaly"][name]
    with pytest.raises(b.BaselineInvalid, match=f"missing_field:signal_anomaly.{name}"):
        b.validate_manifest(m, live_signature=_LIVE, today=_TODAY)


def test_validate_keeps_earlier_reasons_first():
    # below_floor still wins over the appended checks
    m = _manifest(season_rule="other")
    m["signal_anomaly"]["minimum_independent_dates"] = 5
    with pytest.raises(b.BaselineInvalid, match="below_floor"):
        b.validate_manifest(m, live_signature=_LIVE, today=_TODAY)
