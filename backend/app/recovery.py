"""Policy-controlled recovery playbooks and replaceable action adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.schemas import DimensionScores, RecoveryAction, RiskLevel


@dataclass(frozen=True, slots=True)
class Playbook:
    risk: RiskLevel
    actions: list[RecoveryAction]


@dataclass(frozen=True, slots=True)
class RecoveryActionResult:
    """The outcome of applying one action.

    Recorded per action so that a playbook where three steps succeed and one
    times out is represented as exactly that, rather than collapsed into a
    single verdict for the whole plan.
    """

    succeeded: bool
    affected_traffic_pct: float
    detail: dict[str, object]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryExecutionResult:
    dimensions: DimensionScores
    evaluated_requests: int
    coverage: float
    summary: str


class RecoveryAdapter(Protocol):
    """Boundary for integrations that can change a deployed AI system."""

    simulation: bool

    def execute(self, *, model_id: str, plan_id: str) -> RecoveryExecutionResult: ...

    def execute_action(
        self, *, model_id: str, plan_id: str, action: RecoveryAction
    ) -> RecoveryActionResult: ...

    def rollback_action(
        self, *, model_id: str, plan_id: str, action: RecoveryAction
    ) -> RecoveryActionResult: ...


# How much of a model's traffic each safeguard touches. Published so the
# recorded blast radius of an action is inspectable rather than invented.
SIMULATED_TRAFFIC_SHARE: dict[str, float] = {
    # Policy changes that apply to every request.
    "require_citations": 100.0,
    "enable_safe_response_mode": 100.0,
    "refresh_retrieval_index": 100.0,
    # Changes that only bite on the subset of traffic that trips them.
    "suppress_unsupported_generation": 42.0,
    "route_low_confidence": 18.0,
    "route_fallback_model": 22.0,
    "reduce_concurrency": 30.0,
    "queue_human_review": 6.0,
    "route_human_review": 9.0,
}


class SimulatedRecoveryAdapter:
    """Deterministic demo adapter; it never touches an external deployment."""

    simulation = True

    def execute_action(
        self, *, model_id: str, plan_id: str, action: RecoveryAction
    ) -> RecoveryActionResult:
        del model_id, plan_id
        return RecoveryActionResult(
            succeeded=True,
            affected_traffic_pct=SIMULATED_TRAFFIC_SHARE.get(action.code, 100.0),
            detail={"simulated": True, "code": action.code},
        )

    def rollback_action(
        self, *, model_id: str, plan_id: str, action: RecoveryAction
    ) -> RecoveryActionResult:
        del model_id, plan_id
        if not action.reversible:
            return RecoveryActionResult(
                succeeded=False,
                affected_traffic_pct=0.0,
                detail={"simulated": True, "code": action.code},
                error="Action is not reversible.",
            )
        return RecoveryActionResult(
            succeeded=True,
            affected_traffic_pct=SIMULATED_TRAFFIC_SHARE.get(action.code, 100.0),
            detail={"simulated": True, "code": action.code, "rolled_back": True},
        )

    def execute(self, *, model_id: str, plan_id: str) -> RecoveryExecutionResult:
        del model_id, plan_id
        return RecoveryExecutionResult(
            dimensions=DimensionScores(
                quality=84,
                groundedness=78,
                semantic_stability=78,
                temporal_stability=84,
                safety=94,
                drift=80,
                reliability=90,
                latency=94,
                cost=86,
            ),
            evaluated_requests=50,
            coverage=0.98,
            summary="Simulated safeguards restored health after 50 evaluation requests.",
        )


def build_playbook(probable_cause: str) -> Playbook:
    if probable_cause == "knowledge_freshness_failure":
        return Playbook(
            risk=RiskLevel.MEDIUM,
            actions=[
                _action(
                    1,
                    "require_citations",
                    "Require citations",
                    "Only return factual answers backed by an approved retrieved source.",
                    RiskLevel.LOW,
                ),
                _action(
                    2,
                    "suppress_unsupported_generation",
                    "Suppress unsupported generation",
                    "Return a safe fallback when retrieved evidence cannot support the answer.",
                    RiskLevel.MEDIUM,
                ),
                _action(
                    3,
                    "refresh_retrieval_index",
                    "Refresh retrieval index",
                    "Rebuild the index from the latest approved policy documents.",
                    RiskLevel.MEDIUM,
                ),
                _action(
                    4,
                    "route_low_confidence",
                    "Route low-confidence requests",
                    "Send low-confidence queries to the configured fallback model.",
                    RiskLevel.MEDIUM,
                ),
                _action(
                    5,
                    "queue_human_review",
                    "Queue conflicting responses",
                    "Send factual conflicts to the human-review queue.",
                    RiskLevel.LOW,
                ),
            ],
        )

    if probable_cause == "safety_regression":
        return Playbook(
            risk=RiskLevel.HIGH,
            actions=[
                _action(
                    1,
                    "enable_safe_response_mode",
                    "Enable safe response mode",
                    "Apply the approved restrictive safety policy.",
                    RiskLevel.HIGH,
                ),
                _action(
                    2,
                    "route_human_review",
                    "Escalate flagged traffic",
                    "Require human review for affected request classes.",
                    RiskLevel.MEDIUM,
                ),
            ],
        )

    if probable_cause == "operational_reliability_failure":
        return Playbook(
            risk=RiskLevel.MEDIUM,
            actions=[
                _action(
                    1,
                    "route_fallback_model",
                    "Route to fallback model",
                    "Shift affected traffic to the configured healthy fallback.",
                    RiskLevel.MEDIUM,
                ),
                _action(
                    2,
                    "reduce_concurrency",
                    "Reduce concurrency",
                    "Apply the approved concurrency ceiling while the provider recovers.",
                    RiskLevel.LOW,
                ),
            ],
        )

    return Playbook(
        risk=RiskLevel.MEDIUM,
        actions=[
            _action(
                1,
                "queue_human_review",
                "Request human diagnosis",
                "Collect affected traces for operator review before changing production.",
                RiskLevel.LOW,
            )
        ],
    )


def _action(
    order: int,
    code: str,
    title: str,
    description: str,
    risk: RiskLevel,
) -> RecoveryAction:
    return RecoveryAction(
        order=order,
        code=code,
        title=title,
        description=description,
        risk=risk,
        reversible=True,
    )

