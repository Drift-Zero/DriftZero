"""Policy-controlled recovery playbooks and replaceable action adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.schemas import ActorRole, DimensionScores, RecoveryAction, RiskLevel

if TYPE_CHECKING:
    from app.config import Settings

RECOVERY_POLICY_VERSION = "recovery-v2"


class RecoveryAdapterTransientError(RuntimeError):
    """A retryable control-plane outage with no trustworthy action verdict."""


@dataclass(frozen=True, slots=True)
class RecoveryPolicyDecision:
    allowed: bool
    required_role: ActorRole
    reason: str


class RecoveryPolicy:
    """Small, deterministic authorization policy for privileged recovery actions."""

    version = RECOVERY_POLICY_VERSION
    _ROLE_RANK = {
        ActorRole.VIEWER: 0,
        ActorRole.SERVICE: 1,
        ActorRole.OPERATOR: 2,
        ActorRole.ADMIN: 3,
    }
    _REQUIRED_ROLE = {
        RiskLevel.LOW: ActorRole.OPERATOR,
        RiskLevel.MEDIUM: ActorRole.OPERATOR,
        RiskLevel.HIGH: ActorRole.ADMIN,
    }

    def authorize(self, *, risk: RiskLevel, role: ActorRole) -> RecoveryPolicyDecision:
        required = self._REQUIRED_ROLE[risk]
        allowed = self._ROLE_RANK[role] >= self._ROLE_RANK[required]
        return RecoveryPolicyDecision(
            allowed=allowed,
            required_role=required,
            reason=(
                "authorized"
                if allowed
                else f"{risk.value}-risk recovery requires the {required.value} role"
            ),
        )


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
    external_operation_id: str | None = None
    configuration_verified: bool = True
    config_before: dict[str, object] = field(default_factory=dict)
    config_after: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecoveryExecutionResult:
    dimensions: DimensionScores
    evaluated_requests: int
    coverage: float
    summary: str


class RecoveryAdapter(Protocol):
    """Boundary for integrations that can change a deployed AI system."""

    simulation: bool

    def estimate_traffic_pct(self, *, action: RecoveryAction) -> float: ...

    def execute(self, *, model_id: str, plan_id: str) -> RecoveryExecutionResult | None: ...

    def execute_action(
        self,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str,
    ) -> RecoveryActionResult: ...

    def rollback_action(
        self,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str,
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

    def estimate_traffic_pct(self, *, action: RecoveryAction) -> float:
        return SIMULATED_TRAFFIC_SHARE.get(action.code, 100.0)

    def execute_action(
        self,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str = "simulation",
    ) -> RecoveryActionResult:
        del model_id, plan_id
        return RecoveryActionResult(
            succeeded=True,
            affected_traffic_pct=self.estimate_traffic_pct(action=action),
            detail={"simulated": True, "code": action.code},
            external_operation_id=execution_id,
            config_before={"enabled": False},
            config_after={"enabled": True},
        )

    def rollback_action(
        self,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str = "simulation",
    ) -> RecoveryActionResult:
        del model_id, plan_id
        if not action.reversible:
            return RecoveryActionResult(
                succeeded=False,
                affected_traffic_pct=0.0,
                detail={"simulated": True, "code": action.code},
                error="Action is not reversible.",
                external_operation_id=execution_id,
            )
        return RecoveryActionResult(
            succeeded=True,
            affected_traffic_pct=self.estimate_traffic_pct(action=action),
            detail={"simulated": True, "code": action.code, "rolled_back": True},
            external_operation_id=execution_id,
            config_before={"enabled": True},
            config_after={"enabled": False},
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


class ControlPlaneHttpAdapter:
    """Production adapter for an HTTPS model gateway or feature-flag control plane.

    The remote service must honor ``Idempotency-Key`` and return the resulting
    configuration. DriftZero does not consider an action successful unless the
    remote service explicitly confirms that the desired configuration is active.
    """

    simulation = False

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        allow_insecure_http: bool = False,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Recovery control URL must be an absolute HTTP(S) URL.")
        if parsed.scheme != "https" and not allow_insecure_http:
            raise ValueError("Production recovery control requires HTTPS.")
        if not token:
            raise ValueError("Recovery control token is required.")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout_seconds = timeout_seconds

    def estimate_traffic_pct(self, *, action: RecoveryAction) -> float:
        return SIMULATED_TRAFFIC_SHARE.get(action.code, 100.0)

    def execute_action(
        self,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str,
    ) -> RecoveryActionResult:
        return self._invoke(
            "apply",
            model_id=model_id,
            plan_id=plan_id,
            action=action,
            execution_id=execution_id,
        )

    def rollback_action(
        self,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str,
    ) -> RecoveryActionResult:
        if not action.reversible:
            return RecoveryActionResult(
                succeeded=False,
                affected_traffic_pct=0.0,
                detail={},
                error="Action is not reversible.",
            )
        return self._invoke(
            "rollback",
            model_id=model_id,
            plan_id=plan_id,
            action=action,
            execution_id=f"rollback:{execution_id}",
        )

    def execute(self, *, model_id: str, plan_id: str) -> None:
        del model_id, plan_id
        # Real health evidence must arrive through telemetry. A control-plane
        # acknowledgement must never be fabricated into a healthy score.
        return None

    def _invoke(
        self,
        operation: str,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str,
    ) -> RecoveryActionResult:
        if action.code not in SIMULATED_TRAFFIC_SHARE:
            return RecoveryActionResult(
                succeeded=False,
                affected_traffic_pct=0.0,
                detail={},
                error=f"Action '{action.code}' is not allow-listed.",
            )
        payload = {
            "model_id": model_id,
            "plan_id": plan_id,
            "execution_id": execution_id,
            "action": action.model_dump(mode="json"),
        }
        request = Request(
            f"{self.base_url}/v1/recovery/actions/{action.code}/{operation}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Idempotency-Key": execution_id,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {408, 429} or exc.code >= 500:
                raise RecoveryAdapterTransientError(
                    f"Recovery control plane returned retryable HTTP {exc.code}."
                ) from exc
            return RecoveryActionResult(
                succeeded=False,
                affected_traffic_pct=0.0,
                detail={},
                error=f"Control plane refused the action with HTTP {exc.code}.",
            )
        except (URLError, TimeoutError) as exc:
            raise RecoveryAdapterTransientError(
                f"Recovery control plane is temporarily unavailable ({type(exc).__name__})."
            ) from exc
        except json.JSONDecodeError:
            return RecoveryActionResult(
                succeeded=False,
                affected_traffic_pct=0.0,
                detail={},
                error="Control plane returned an invalid JSON response.",
            )

        verified = body.get("configuration_verified") is True
        succeeded = body.get("succeeded") is True and verified
        return RecoveryActionResult(
            succeeded=succeeded,
            affected_traffic_pct=float(body.get("affected_traffic_pct", 0.0)),
            detail=dict(body.get("detail") or {}),
            error=(None if succeeded else str(body.get("error") or "Configuration not verified.")),
            external_operation_id=(
                str(body["external_operation_id"])
                if body.get("external_operation_id")
                else None
            ),
            configuration_verified=verified,
            config_before=dict(body.get("config_before") or {}),
            config_after=dict(body.get("config_after") or {}),
        )


def build_recovery_adapter(settings: Settings) -> RecoveryAdapter:
    """Select simulation unless an explicit production control plane is configured."""

    if not settings.recovery_control_url:
        return SimulatedRecoveryAdapter()
    return ControlPlaneHttpAdapter(
        settings.recovery_control_url,
        settings.recovery_control_token or "",
        timeout_seconds=settings.recovery_control_timeout_seconds,
        allow_insecure_http=settings.recovery_allow_insecure_http,
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

