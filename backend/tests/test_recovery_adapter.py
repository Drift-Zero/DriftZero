"""Production recovery adapter safety boundary."""

from __future__ import annotations

import json

import pytest

from app.recovery import ControlPlaneHttpAdapter
from app.schemas import RecoveryAction, RiskLevel

ACTION = RecoveryAction(
    order=1,
    code="require_citations",
    title="Require citations",
    description="Require evidence.",
    risk=RiskLevel.LOW,
    reversible=True,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "succeeded": True,
                "configuration_verified": True,
                "affected_traffic_pct": 10,
                "external_operation_id": "flag-change-42",
                "config_before": {"citation_required": False},
                "config_after": {"citation_required": True},
            }
        ).encode()


def test_production_adapter_requires_https() -> None:
    with pytest.raises(ValueError, match="requires HTTPS"):
        ControlPlaneHttpAdapter("http://control.internal", "secret")


def test_adapter_sends_stable_idempotency_key_and_records_config(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("app.recovery.urlopen", fake_urlopen)
    adapter = ControlPlaneHttpAdapter("https://control.example", "secret", timeout_seconds=3)

    result = adapter.execute_action(
        model_id="model-1",
        plan_id="plan-1",
        action=ACTION,
        execution_id="execution-1",
    )

    assert result.succeeded is True
    assert result.configuration_verified is True
    assert result.external_operation_id == "flag-change-42"
    assert result.config_before == {"citation_required": False}
    assert result.config_after == {"citation_required": True}
    assert captured["request"].headers["Idempotency-key"] == "execution-1"
    assert captured["timeout"] == 3


def test_unknown_action_is_blocked_before_network(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.recovery.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network should not be called"),
    )
    adapter = ControlPlaneHttpAdapter("https://control.example", "secret")
    unknown = ACTION.model_copy(update={"code": "run_arbitrary_shell"})

    result = adapter.execute_action(
        model_id="model-1",
        plan_id="plan-1",
        action=unknown,
        execution_id="execution-1",
    )

    assert result.succeeded is False
    assert "not allow-listed" in result.error
