"""BASELINE_MODE gate and the TEST-baseline artefact loader.

Offline: every artefact is synthetic and written under pytest's ``tmp_path``,
with ``baseline_store.BASELINE_ROOT`` pointed there. Nothing here reads the
real ``backend/data/baselines`` or touches GEE. The manifest is made by the
real ``detection/src/baseline.py`` (``build_manifest``, ``self_check``) through
the bridge, so the fixture is what the builder would write, not a hand copy.

What is pinned:
  * mode off (anything but the exact string ``test``): the gate is the config
    path alone, byte-for-byte as before, and no artefact is even looked at;
  * mode test: the gate opens only for an artefact that validates against the
    live preprocessing signature and today's date AND passes the unchanged
    ``_signal_anomaly_active`` predicate on its own declaration;
  * risk evaluation never opens from a baseline;
  * neither ``baseline_status()`` nor ``signal_anomaly_active()`` raises.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import median

import pytest

from src import _detection as bridge
from src import baseline_store, config, scientific_status

logic = bridge.baseline_logic

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_BUILT_ON = date(2026, 1, 15)
# Different history lengths so the median is not also the minimum.
_SITE_YEARS = {"alpha": range(2014, 2026), "beta": range(2016, 2026), "gamma": range(2015, 2026)}

_VALID_KEYS = {
    "mode", "valid", "kind", "version", "built_at", "history_start", "history_end",
    "season_rule", "min_independent_dates", "median_independent_dates",
    "preprocessing_signature", "base_rates",
}


# --------------------------------------------------------------------------
# Synthetic artefact
# --------------------------------------------------------------------------


def _site_rows(site: str) -> list[dict]:
    """Two clear-sky dates a month (5th and 20th) over the site's years."""
    offset = sum(map(ord, site))
    rows = []
    for year in _SITE_YEARS[site]:
        for month in range(1, 13):
            for day in (5, 20):
                rows.append({
                    "acquisition_date": f"{year}-{month:02d}-{day:02d}",
                    "ndci": 0.02 + 0.002 * ((year * 12 + month + day + offset) % 13),
                    "cloud_fraction": 0.0,
                    "scene_id": f"scene-{year}{month:02d}{day:02d}",
                })
    return rows


def _min_season_dates(rows: list[dict]) -> int:
    def month_of(row):
        return date.fromisoformat(row["acquisition_date"]).month

    return min(
        len({r["acquisition_date"] for r in rows if month_of(r) in logic.season_months(m)})
        for m in range(1, 13)
    )


def _live_signature() -> str:
    return logic.preprocessing_signature(bridge.preprocessing_params())


@lru_cache(maxsize=None)
def _self_check_total(signature: str) -> str:
    """Summed real self-check over the sites (JSON text, so the cache is immutable)."""
    total = {"assessed": 0, "watch": 0, "high": 0, "no_assessment": 0, "reasons": {}}
    for site in _SITE_YEARS:
        part = logic.self_check(_site_rows(site), location_id=site, preprocessing_signature=signature)["total"]
        for key in ("assessed", "watch", "high", "no_assessment"):
            total[key] += part[key]
        for reason, n in part["reasons"].items():
            total["reasons"][reason] = total["reasons"].get(reason, 0) + n
    return json.dumps(total)


def _artefact(**manifest_overrides) -> tuple[dict, dict[str, list[dict]]]:
    signature = _live_signature()
    rows = {site: _site_rows(site) for site in _SITE_YEARS}
    locations = {
        site: {
            "n_dates": len(site_rows),
            "min_season_dates": _min_season_dates(site_rows),
            "first": site_rows[0]["acquisition_date"],
            "last": site_rows[-1]["acquisition_date"],
        }
        for site, site_rows in rows.items()
    }
    total = json.loads(_self_check_total(signature))
    manifest = logic.build_manifest(
        baseline_version=logic.version_for(_BUILT_ON, signature),
        built_at="2026-01-15T03:00:00+00:00",
        history_start=min(info["first"] for info in locations.values()),
        history_end=max(info["last"] for info in locations.values()),
        preprocessing_signature=signature,
        preprocessing_params=bridge.preprocessing_params(),
        locations=locations,
        self_check={"by_season": {}, "total": total},
        builder_git_sha=None,
    )
    manifest.update(manifest_overrides)
    return manifest, rows


def _edit_manifest(path: Path, mutate) -> None:
    """A hand edit of manifest.json, in place (same inode); NaN allowed on purpose."""
    target = path / baseline_store.MANIFEST_NAME
    manifest = json.loads(target.read_text(encoding="utf-8"))
    mutate(manifest)
    target.write_text(json.dumps(manifest, indent=2, allow_nan=True) + "\n", encoding="utf-8")


def _keep_mtime(path: Path, mtime_ns: int) -> None:
    os.utime(path, ns=(mtime_ns, mtime_ns))


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Point the store at an empty tmp root, start with no cache, mode off."""
    root = tmp_path / "baselines"
    monkeypatch.setattr(baseline_store, "BASELINE_ROOT", root)
    monkeypatch.setattr(baseline_store, "_artifact_cache", None)
    monkeypatch.setattr(scientific_status, "_last_baseline_warning", None)
    monkeypatch.setattr(config, "BASELINE_MODE", "off")
    return root


@pytest.fixture()
def root(_isolated) -> Path:
    return _isolated


@pytest.fixture()
def test_mode(monkeypatch):
    monkeypatch.setattr(config, "BASELINE_MODE", "test")


@pytest.fixture()
def valid(root) -> tuple[Path, dict, dict]:
    manifest, rows = _artefact()
    path = baseline_store.write_artifact(root, manifest, rows)
    return path, manifest, rows


def _invalid(reason: str) -> dict:
    return {"mode": "test", "valid": False, "kind": "test", "reason": reason}


# --------------------------------------------------------------------------
# BASELINE_MODE parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "off"), ("", "off"), ("off", "off"), ("test", "test"),
        ("TEST", "off"), ("Test", "off"), (" test", "off"), ("test ", "off"),
        ("true", "off"), ("1", "off"), ("on", "off"), ("tests", "off"),
    ],
)
def test_only_the_exact_value_test_enables_baseline_mode(raw, expected):
    assert config._parse_baseline_mode(raw) == expected


@pytest.mark.parametrize("env_value,expected", [("", "off"), ("test", "test"), ("TEST", "off")])
def test_baseline_mode_is_read_from_the_environment(env_value, expected):
    probe = (
        "import sys; sys.path.insert(0, {backend_dir!r})\n"
        "from src.config import BASELINE_MODE\n"
        "print(BASELINE_MODE)\n"
    ).format(backend_dir=str(_BACKEND_DIR))
    env = dict(os.environ)
    # An explicit (even blank) value wins over backend/.env's setdefault.
    env["BASELINE_MODE"] = env_value
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        env=env, check=True, cwd=str(_BACKEND_DIR),
    ).stdout.strip()
    assert out == expected


def test_env_example_documents_baseline_mode_off_by_default():
    text = (_BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    assert "BASELINE_MODE=off" in lines
    assert "provisional" in text.lower() and "uncalibrated" in text.lower()


# --------------------------------------------------------------------------
# Mode off: exactly the old gate, artefact never consulted
# --------------------------------------------------------------------------


def test_mode_off_keeps_the_gate_closed_even_with_a_valid_artefact(valid, monkeypatch):
    def must_not_be_called(*_a, **_k):
        raise AssertionError("mode off must not look at the baseline artefact")

    monkeypatch.setattr(baseline_store, "latest_artifact_path", must_not_be_called)
    monkeypatch.setattr(baseline_store, "read_artifact", must_not_be_called)

    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.risk_evaluation_active() is False
    assert scientific_status.baseline_status() == {"mode": "off"}
    assert baseline_store.load_active_baseline() is None


@pytest.mark.parametrize("mode", ["off", "TEST", "true", "", None])
def test_any_value_but_test_is_off_at_call_time(valid, monkeypatch, mode):
    monkeypatch.setattr(config, "BASELINE_MODE", mode)
    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.baseline_status() == {"mode": "off"}
    assert baseline_store.load_active_baseline() is None


def _config_declaring(signal_active: bool, risk_active: bool) -> dict:
    return {
        "risk_evaluation": {"active": risk_active},
        "signal_anomaly": {
            "status": "active" if signal_active else "inactive",
            "minimum_independent_dates": 30,
            "max_observation_age_days": 14,
            "location_specific": True,
            "season_specific": True,
            "history_before_target_only": True,
            "baseline_version": "v1",
            "preprocessing_signature": "sig",
        },
    }


@pytest.mark.parametrize(
    "signal_active,risk_active,expected_signal,expected_risk",
    [(False, False, False, False), (True, False, True, False), (True, True, True, True), (False, True, False, False)],
)
def test_mode_off_gate_is_the_config_path_alone(
    valid, monkeypatch, signal_active, risk_active, expected_signal, expected_risk,
):
    cfg = _config_declaring(signal_active, risk_active)
    monkeypatch.setattr(scientific_status.bridge, "load_prediction_config", lambda: cfg)
    assert scientific_status.signal_anomaly_active() is expected_signal
    assert scientific_status.risk_evaluation_active() is expected_risk


# --------------------------------------------------------------------------
# Test mode with a valid artefact
# --------------------------------------------------------------------------


def test_valid_artefact_opens_the_signal_gate_and_describes_itself(valid, test_mode):
    _, manifest, _ = valid
    assert scientific_status.signal_anomaly_active() is True

    status = scientific_status.baseline_status()
    assert set(status) == _VALID_KEYS
    assert status["mode"] == "test"
    assert status["valid"] is True
    assert status["kind"] == "test"
    assert status["version"] == manifest["baseline_version"]
    assert status["version"].startswith("TEST-20260115-")
    assert status["built_at"] == manifest["built_at"]
    assert status["history_start"] == "2014-01-05"
    assert status["history_end"] == "2025-12-20"
    assert status["season_rule"] == logic.SEASON_RULE
    assert status["preprocessing_signature"] == _live_signature()
    # Declared floor = weakest season anywhere (beta: 10 years x 3 months x 2).
    assert status["min_independent_dates"] == manifest["signal_anomaly"]["minimum_independent_dates"] == 60
    # Median over the locations' n_dates: alpha 288, gamma 264, beta 240.
    assert status["median_independent_dates"] == median([288, 264, 240]) == 264
    assert status["base_rates"] == manifest["self_check"]["total"]
    assert status["base_rates"]["assessed"] + status["base_rates"]["no_assessment"] == 288 + 264 + 240


def test_risk_evaluation_stays_false_in_test_mode(valid, test_mode, monkeypatch):
    assert scientific_status.signal_anomaly_active() is True
    assert scientific_status.risk_evaluation_active() is False

    # Even a config that switches risk on cannot borrow the baseline's
    # declaration: risk still needs the config's own signal declaration.
    cfg = _config_declaring(signal_active=False, risk_active=True)
    monkeypatch.setattr(scientific_status.bridge, "load_prediction_config", lambda: cfg)
    assert scientific_status.signal_anomaly_active() is True
    assert scientific_status.risk_evaluation_active() is False


def test_load_active_baseline_returns_a_frozen_validated_copy(valid, test_mode):
    _, manifest, rows = valid
    active = baseline_store.load_active_baseline()
    assert isinstance(active, baseline_store.ActiveBaseline)
    assert active.version == manifest["baseline_version"]
    assert active.manifest == manifest
    assert active.rows_by_location == rows
    with pytest.raises(dataclasses.FrozenInstanceError):
        active.version = "other"  # type: ignore[misc]

    # Mutating what a caller got never reaches the cached gate inputs.
    active.manifest["signal_anomaly"]["minimum_independent_dates"] = 5
    active.rows_by_location["alpha"].clear()
    again = baseline_store.load_active_baseline()
    assert again.manifest == manifest
    assert again.rows_by_location == rows
    status = scientific_status.baseline_status()
    status["base_rates"]["assessed"] = -1
    assert scientific_status.baseline_status()["base_rates"] == manifest["self_check"]["total"]
    assert scientific_status.signal_anomaly_active() is True


def test_newest_version_directory_is_the_one_used(root, test_mode):
    old, rows = _artefact()
    baseline_store.write_artifact(root, old, rows)
    newer, _ = _artefact()
    newer["baseline_version"] = newer["signal_anomaly"]["baseline_version"] = "TEST-20260201-" + _live_signature()[:8]
    baseline_store.write_artifact(root, newer, rows)
    assert scientific_status.baseline_status()["version"] == newer["baseline_version"]
    assert baseline_store.load_active_baseline().version == newer["baseline_version"]


# --------------------------------------------------------------------------
# Test mode, refused artefacts: gate closed, reason stated
# --------------------------------------------------------------------------


def _assert_refused(reason: str) -> None:
    assert scientific_status.baseline_status() == _invalid(reason)
    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.risk_evaluation_active() is False


def test_no_artefact_is_reported_as_no_artifact(root, test_mode):
    assert not root.exists()
    _assert_refused("no_artifact")
    root.mkdir()
    (root / "TEST-20260115-deadbeef").mkdir()  # incomplete: no files
    _assert_refused("no_artifact")
    assert baseline_store.load_active_baseline() is None


@pytest.mark.parametrize("name", [baseline_store.MANIFEST_NAME, baseline_store.SITES_NAME])
def test_corrupt_json_is_unreadable_not_an_error(valid, test_mode, name, caplog):
    path, _, _ = valid
    assert scientific_status.signal_anomaly_active() is True  # cached as valid first
    (path / name).write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=scientific_status.__name__):
        _assert_refused("unreadable")
    assert any("unreadable" in record.getMessage() for record in caplog.records)
    with pytest.raises(ValueError):  # the loader itself is strict; only the gate swallows
        baseline_store.load_active_baseline()


def test_corrupt_artefact_in_test_mode_leaves_the_app_serving(valid, test_mode, client):
    path, _, _ = valid
    (path / baseline_store.MANIFEST_NAME).write_text("not json at all", encoding="utf-8")
    risk_map = client.get("/risk-map")
    assert risk_map.status_code == 200
    for feature in risk_map.json()["features"]:
        assert feature["properties"]["signal_anomaly_level"] is None
        assert feature["properties"]["risk_level"] is None
    assert client.get("/summary").status_code == 200


@pytest.mark.parametrize(
    "sites_payload",
    [{"rows": []}, {"rows": {"alpha": "nope"}}, {"nothing": {}}, {"rows": {"alpha": [], "beta": [], "zeta": []}}],
)
def test_structurally_wrong_rows_are_unreadable(valid, test_mode, sites_payload):
    path, _, _ = valid
    (path / baseline_store.SITES_NAME).write_text(json.dumps(sites_payload), encoding="utf-8")
    _assert_refused("unreadable")


def test_signature_mismatch_when_live_preprocessing_changes(valid, test_mode, monkeypatch):
    real = bridge.preprocessing_params
    monkeypatch.setattr(bridge, "preprocessing_params", lambda: {**real(), "buffer_m": 999})
    _assert_refused("signature_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_independent_dates", 5),
        ("minimum_independent_dates", 29),
        ("minimum_independent_dates", float("nan")),
        ("max_observation_age_days", 90),
        ("max_observation_age_days", float("nan")),
        ("max_observation_age_days", -1),
    ],
)
def test_hand_loosened_floors_are_rejected(valid, test_mode, field, value):
    path, _, _ = valid
    _edit_manifest(path, lambda m: m["signal_anomaly"].__setitem__(field, value))
    _assert_refused("below_floor")


def test_the_unchanged_predicate_rejects_loose_floors_even_if_validation_is_bypassed(
    valid, test_mode, monkeypatch,
):
    """Defence in depth: the same predicate as the config path, on the declaration."""
    path, _, _ = valid
    monkeypatch.setattr(logic, "validate_manifest", lambda *_a, **_k: None)
    for field, value in (("minimum_independent_dates", 5), ("max_observation_age_days", 90)):
        _edit_manifest(path, lambda m: m["signal_anomaly"].update(minimum_independent_dates=60, max_observation_age_days=14))
        assert scientific_status.signal_anomaly_active() is True
        _edit_manifest(path, lambda m: m["signal_anomaly"].__setitem__(field, value))
        assert scientific_status.signal_anomaly_active() is False
        assert scientific_status.baseline_status() == _invalid("inactive_declaration")


@pytest.mark.parametrize("field", ["location_specific", "season_specific", "history_before_target_only"])
def test_declaration_failing_the_gate_predicate_is_not_valid(valid, test_mode, field):
    path, _, _ = valid
    _edit_manifest(path, lambda m: m["signal_anomaly"].__setitem__(field, False))
    _assert_refused("inactive_declaration")


def test_history_end_in_the_future_is_refused(root, test_mode):
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    manifest, rows = _artefact(history_end=tomorrow)
    baseline_store.write_artifact(root, manifest, rows)
    _assert_refused("history_in_future")


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda m: m.__setitem__("baseline_kind", "calibrated"), "not_test_kind"),
        (lambda m: m.pop("built_at"), "missing_field:built_at"),
        (lambda m: m.__setitem__("season_rule", "whole year"), "season_rule_mismatch"),
        (lambda m: m["signal_anomaly"].__setitem__("status", "inactive"), "inactive_declaration"),
        (lambda m: m["signal_anomaly"].__setitem__("high_at_z", 2.5), "threshold_mismatch"),
        (lambda m: m["signal_anomaly"].__setitem__("baseline_version", "TEST-other"), "inconsistent_declaration"),
    ],
)
def test_other_validation_reasons_pass_through(valid, test_mode, mutate, reason):
    path, _, _ = valid
    _edit_manifest(path, mutate)
    _assert_refused(reason)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.pop("locations"),
        lambda m: m.__setitem__("locations", {}),
        lambda m: m["locations"]["alpha"].__setitem__("n_dates", "288"),
        lambda m: m.pop("self_check"),
    ],
)
def test_manifest_missing_what_the_status_reports_is_unreadable(valid, test_mode, mutate):
    path, _, _ = valid
    _edit_manifest(path, mutate)
    _assert_refused("unreadable")


def test_neither_entry_point_raises_on_an_unexpected_error(valid, test_mode, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(baseline_store, "latest_artifact_path", boom)
    with caplog.at_level(logging.WARNING, logger=scientific_status.__name__):
        _assert_refused("unreadable")
    assert any("disk on fire" in (record.exc_text or "") + record.getMessage() for record in caplog.records)


def test_repeated_failures_log_one_warning(root, test_mode, caplog):
    with caplog.at_level(logging.WARNING, logger=scientific_status.__name__):
        for _ in range(5):
            scientific_status.baseline_status()
            scientific_status.signal_anomaly_active()
    ours = [r for r in caplog.records if r.name == scientific_status.__name__ and r.levelno == logging.WARNING]
    assert len(ours) == 1


# --------------------------------------------------------------------------
# Cache: parse once per file state; any change is seen at once
# --------------------------------------------------------------------------


def test_artefact_is_parsed_once_per_file_state(valid, test_mode, monkeypatch):
    reads = []
    real = baseline_store.read_artifact
    monkeypatch.setattr(baseline_store, "read_artifact", lambda p: reads.append(p) or real(p))

    for _ in range(4):
        assert scientific_status.signal_anomaly_active() is True
        assert scientific_status.baseline_status()["valid"] is True
        assert baseline_store.load_active_baseline() is not None
    assert len(reads) == 1


def test_same_mtime_rewrite_with_a_different_size_is_picked_up(valid, test_mode):
    path, _, _ = valid
    target = path / baseline_store.MANIFEST_NAME
    assert scientific_status.signal_anomaly_active() is True
    before = os.stat(target)

    _edit_manifest(path, lambda m: m["signal_anomaly"].__setitem__("minimum_independent_dates", 5))
    _keep_mtime(target, before.st_mtime_ns)
    after = os.stat(target)
    assert (after.st_mtime_ns, after.st_ino) == (before.st_mtime_ns, before.st_ino)
    assert after.st_size != before.st_size
    _assert_refused("below_floor")

    # And back again: the safety-critical direction is not the only one seen.
    _edit_manifest(path, lambda m: m["signal_anomaly"].__setitem__("minimum_independent_dates", 60))
    _keep_mtime(target, before.st_mtime_ns)
    assert scientific_status.signal_anomaly_active() is True


def test_same_mtime_same_size_replacement_is_picked_up_by_inode(valid, test_mode):
    path, _, _ = valid
    target = path / baseline_store.MANIFEST_NAME
    assert scientific_status.signal_anomaly_active() is True
    before = os.stat(target)

    text = target.read_text(encoding="utf-8")
    edited = text.replace('"watch_at_z": 2.0', '"watch_at_z": 2.5')
    assert edited != text and len(edited) == len(text)
    scratch = path / "manifest.json.new"
    scratch.write_text(edited, encoding="utf-8")
    os.replace(scratch, target)
    _keep_mtime(target, before.st_mtime_ns)
    after = os.stat(target)
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)
    assert after.st_ino != before.st_ino
    _assert_refused("threshold_mismatch")


def test_a_corrupted_sites_file_is_seen_after_a_valid_load(valid, test_mode):
    path, _, _ = valid
    assert scientific_status.signal_anomaly_active() is True
    (path / baseline_store.SITES_NAME).write_text("{}", encoding="utf-8")
    _assert_refused("unreadable")


def test_validation_is_rechecked_on_every_call_not_cached(valid, test_mode, monkeypatch):
    """Today's date and the live signature are not part of the file key."""
    assert scientific_status.signal_anomaly_active() is True
    real = bridge.preprocessing_params
    monkeypatch.setattr(bridge, "preprocessing_params", lambda: {**real(), "scale_m": 60})
    _assert_refused("signature_mismatch")
    monkeypatch.setattr(bridge, "preprocessing_params", real)
    assert scientific_status.signal_anomaly_active() is True
    monkeypatch.setattr(baseline_store, "_utc_today", lambda: date(2025, 12, 19))
    _assert_refused("history_in_future")
