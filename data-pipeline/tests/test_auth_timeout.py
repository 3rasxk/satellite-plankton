"""Offline regression coverage for the Earth Engine request deadline."""

from __future__ import annotations

import pytest

from src import auth


class _SuccessfulProbe:
    def getInfo(self):
        return 1


def _record_successful_initialization(monkeypatch):
    events = []

    def initialize(**kwargs):
        transport = kwargs["http_transport"]
        events.append(
            (
                "initialize",
                None if transport is None else transport.timeout,
                kwargs.get("project"),
            )
        )

    monkeypatch.setattr(auth.ee, "Initialize", initialize)
    monkeypatch.setattr(
        auth.ee.data,
        "setDeadline",
        lambda milliseconds: events.append(("deadline", milliseconds)),
    )
    monkeypatch.setattr(
        auth.ee,
        "Number",
        lambda _value: events.append("probe") or _SuccessfulProbe(),
    )
    auth.reset()
    return events


def test_initialize_ee_sets_a_finite_deadline_before_the_network_probe(monkeypatch):
    monkeypatch.setenv("GEE_REQUEST_TIMEOUT_SECONDS", "17.5")
    monkeypatch.delenv("EE_PROJECT_ID", raising=False)
    monkeypatch.delenv("GEE_SERVICE_ACCOUNT_KEY_JSON", raising=False)
    events = _record_successful_initialization(monkeypatch)

    auth.initialize_ee(force=True)

    assert events == [
        ("initialize", 17.5, None),
        ("deadline", 17_500.0),
        ("initialize", None, None),
        "probe",
    ]


def test_blank_request_timeout_uses_the_finite_default(monkeypatch):
    monkeypatch.setenv("GEE_REQUEST_TIMEOUT_SECONDS", "")
    monkeypatch.setenv("EE_PROJECT_ID", "configured-project")
    monkeypatch.delenv("GEE_SERVICE_ACCOUNT_KEY_JSON", raising=False)
    events = _record_successful_initialization(monkeypatch)

    auth.initialize_ee(force=True)

    assert events == [
        (
            "initialize",
            auth.DEFAULT_GEE_REQUEST_TIMEOUT_SECONDS,
            "configured-project",
        ),
        ("deadline", auth.DEFAULT_GEE_REQUEST_TIMEOUT_SECONDS * 1000),
        ("initialize", None, "configured-project"),
        "probe",
    ]


@pytest.mark.parametrize("bad_value", ["abc", "0", "-1", "nan", "inf"])
def test_invalid_request_timeout_is_a_config_error_not_an_auth_error(
    monkeypatch, bad_value
):
    monkeypatch.setenv("GEE_REQUEST_TIMEOUT_SECONDS", bad_value)
    monkeypatch.delenv("EE_PROJECT_ID", raising=False)
    monkeypatch.delenv("GEE_SERVICE_ACCOUNT_KEY_JSON", raising=False)
    events = _record_successful_initialization(monkeypatch)

    with pytest.raises(ValueError, match="GEE_REQUEST_TIMEOUT_SECONDS") as excinfo:
        auth.initialize_ee(force=True)

    assert not isinstance(excinfo.value, auth.GEEAuthError)
    # Typed so the backend can map it to a config 503 (still a ValueError).
    assert isinstance(excinfo.value, auth.GEEConfigError)
    assert "authenticate" not in str(excinfo.value)
    assert events == []
    assert auth._initialized is False
