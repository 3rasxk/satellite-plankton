"""/alerts must distinguish 'not evaluated' from 'evaluated, none' (CLAUDE.md §0)."""

from __future__ import annotations

from src.routers import alerts as alerts_module


def test_alerts_reports_not_evaluated_when_risk_gate_off(client, monkeypatch):
    monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: False)
    body = client.get("/alerts").json()
    assert body["evaluation_status"] == "not_evaluated"
    assert body["updated_at"] is None
    assert body["stations"] == []
    assert body["highest_risk_tier"] is None


def test_alerts_reports_active_when_risk_gate_on(client, monkeypatch):
    monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: True)
    body = client.get("/alerts").json()
    assert body["evaluation_status"] == "active"
