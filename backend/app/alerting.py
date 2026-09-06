"""Alert rule evaluation and lifecycle transitions.

The evaluator is deliberately deterministic: a rule is evaluated against
persisted health snapshots, creates at most one active alert, and records the
evidence used for the decision. Delivery is currently the in-product alert
feed, so a committed alert is considered notified immediately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Alert, AlertRule, HealthSnapshot, Incident, MonitoredModel
from app.schemas import (
    AlertMetric,
    AlertRuleType,
    AlertState,
    Comparator,
    HealthState,
)
from app.scoring import forecast_health


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    evaluated_at: datetime
    evaluated_rules: int
    fired: list[Alert]
    resolved: list[Alert]


@dataclass(frozen=True, slots=True)
class RuleDecision:
    evaluable: bool
    should_fire: bool
    condition_active: bool
    observed_value: float | None
    message: str
    details: dict[str, object]


class AlertEvaluator:
    """Evaluate all enabled rules for one model and persist transitions."""

    _COMPARATORS = {
        Comparator.LT: lambda value, threshold: value < threshold,
        Comparator.LTE: lambda value, threshold: value <= threshold,
        Comparator.GT: lambda value, threshold: value > threshold,
        Comparator.GTE: lambda value, threshold: value >= threshold,
    }
    _COMPARATOR_LABELS = {
        Comparator.LT: "below",
        Comparator.LTE: "at or below",
        Comparator.GT: "above",
        Comparator.GTE: "at or above",
    }

    def evaluate(
        self,
        session: Session,
        model: MonitoredModel,
        *,
        snapshot: HealthSnapshot | None,
        incident: Incident | None,
        evaluated_at: datetime,
    ) -> AlertEvaluation:
        evaluated_at = _as_utc(evaluated_at)
        rules = list(
            session.scalars(
                select(AlertRule)
                .where(AlertRule.model_id == model.id, AlertRule.is_enabled.is_(True))
                .order_by(AlertRule.created_at, AlertRule.id)
            ).all()
        )
        fired: list[Alert] = []
        resolved: list[Alert] = []

        for rule in rules:
            decision = self._decision(
                session,
                model,
                rule,
                snapshot=snapshot,
                evaluated_at=evaluated_at,
            )
            active = self._active_alert(session, rule.id)
            if not decision.evaluable:
                continue

            if active is not None:
                if decision.condition_active:
                    active.snapshot_id = snapshot.id if snapshot else active.snapshot_id
                    active.incident_id = incident.id if incident else active.incident_id
                    active.observed_value = decision.observed_value
                    active.message = decision.message
                    active.details = decision.details
                else:
                    self._resolve(active, evaluated_at, "condition_cleared")
                    resolved.append(active)
                continue

            if not decision.should_fire or self._cooling_down(
                session, rule, evaluated_at=evaluated_at
            ):
                continue

            alert = Alert(
                rule_id=rule.id,
                model_id=model.id,
                snapshot_id=snapshot.id if snapshot else None,
                incident_id=incident.id if incident else None,
                severity=rule.severity,
                message=decision.message,
                observed_value=decision.observed_value,
                details=decision.details,
                fired_at=evaluated_at,
                notified_at=evaluated_at if rule.channel == "in_app" else None,
            )
            session.add(alert)
            session.flush()
            fired.append(alert)

        session.flush()
        return AlertEvaluation(
            evaluated_at=evaluated_at,
            evaluated_rules=len(rules),
            fired=fired,
            resolved=resolved,
        )

    def resolve_rule_alerts(
        self,
        session: Session,
        rule_id: str,
        *,
        evaluated_at: datetime,
        reason: str,
    ) -> list[Alert]:
        records = list(
            session.scalars(
                select(Alert).where(
                    Alert.rule_id == rule_id,
                    Alert.state.in_(
                        [AlertState.FIRING.value, AlertState.ACKNOWLEDGED.value]
                    ),
                )
            ).all()
        )
        for alert in records:
            self._resolve(alert, evaluated_at, reason)
        session.flush()
        return records

    def _decision(
        self,
        session: Session,
        model: MonitoredModel,
        rule: AlertRule,
        *,
        snapshot: HealthSnapshot | None,
        evaluated_at: datetime,
    ) -> RuleDecision:
        rule_type = AlertRuleType(rule.rule_type)
        snapshots = self._snapshots(session, model.id, rule, evaluated_at)
        current = snapshot or (snapshots[-1] if snapshots else None)

        if rule_type is AlertRuleType.EVALUATION_FRESHNESS:
            latest_at = current.observed_at if current is not None else model.created_at
            value = max(0.0, (evaluated_at - _as_utc(latest_at)).total_seconds() / 60)
            return self._numeric_decision(rule, [value], value, extra={"latest_at": latest_at})

        if current is None:
            return self._inconclusive(rule, "No health snapshot is available.")

        if rule_type is AlertRuleType.TRANSITION:
            return self._transition_decision(rule, snapshots, current)
        if rule_type is AlertRuleType.TRAJECTORY:
            return self._trajectory_decision(rule, snapshots)

        values = [self._snapshot_value(item, AlertMetric(rule.metric)) for item in snapshots]
        values = [value for value in values if value is not None]
        current_value = self._snapshot_value(current, AlertMetric(rule.metric))
        if current_value is None:
            return self._inconclusive(rule, f"{rule.metric} is not available.")
        return self._numeric_decision(rule, values, current_value)

    def _numeric_decision(
        self,
        rule: AlertRule,
        values: list[float],
        current_value: float,
        *,
        extra: dict[str, object] | None = None,
    ) -> RuleDecision:
        comparator = Comparator(rule.comparator)
        threshold = float(rule.threshold)
        breached = self._COMPARATORS[comparator]
        required = rule.minimum_consecutive_windows
        recent_values = values[-required:]
        condition_active = breached(current_value, threshold)
        should_fire = (
            len(recent_values) >= required
            and condition_active
            and all(breached(value, threshold) for value in recent_values)
        )
        details: dict[str, object] = {
            "rule_name": rule.name,
            "rule_type": rule.rule_type,
            "metric": rule.metric,
            "comparator": comparator.value,
            "threshold": threshold,
            "window_minutes": rule.window_minutes,
            "minimum_consecutive_windows": required,
            "recent_values": recent_values,
        }
        if extra:
            details.update(extra)
        message = (
            f"{rule.name}: {rule.metric} is {current_value:.2f}, "
            f"{self._COMPARATOR_LABELS[comparator]} {threshold:.2f}."
        )
        return RuleDecision(
            evaluable=True,
            should_fire=should_fire,
            condition_active=condition_active,
            observed_value=round(current_value, 4),
            message=message,
            details=details,
        )

    def _transition_decision(
        self,
        rule: AlertRule,
        snapshots: list[HealthSnapshot],
        current: HealthSnapshot,
    ) -> RuleDecision:
        target = HealthState(rule.target_state)
        required = rule.minimum_consecutive_windows
        recent_states = [HealthState(item.state) for item in snapshots]
        condition_active = HealthState(current.state) is target
        enough = len(recent_states) >= required + 1
        preceding = recent_states[-required - 1] if enough else None
        target_run = recent_states[-required:]
        should_fire = (
            enough
            and condition_active
            and all(state is target for state in target_run)
            and preceding is not target
        )
        previous = recent_states[-2] if len(recent_states) >= 2 else None
        details: dict[str, object] = {
            "rule_name": rule.name,
            "rule_type": rule.rule_type,
            "metric": rule.metric,
            "target_state": target.value,
            "previous_state": previous.value if previous else None,
            "current_state": HealthState(current.state).value,
            "minimum_consecutive_windows": required,
        }
        return RuleDecision(
            evaluable=True,
            should_fire=should_fire,
            condition_active=condition_active,
            observed_value=None,
            message=(
                f"{rule.name}: health transitioned from "
                f"{previous.value if previous else 'unknown'} to {current.state}."
            ),
            details=details,
        )

    def _trajectory_decision(
        self,
        rule: AlertRule,
        snapshots: list[HealthSnapshot],
    ) -> RuleDecision:
        points = [
            (item.observed_at, float(item.score))
            for item in snapshots
            if item.score is not None
        ]
        forecasts = []
        for index in range(2, len(points) + 1):
            forecast = forecast_health(points[:index])
            if forecast is not None:
                forecasts.append(forecast)
        if not forecasts:
            return self._inconclusive(rule, "At least two scored snapshots are required.")

        metric = AlertMetric(rule.metric)
        values = [
            (
                forecast.predicted_score
                if metric is AlertMetric.FORECAST_SCORE
                else forecast.change_per_hour
            )
            for forecast in forecasts
        ]
        current = forecasts[-1]
        return self._numeric_decision(
            rule,
            values,
            values[-1],
            extra={
                "forecast": {
                    "horizon_minutes": current.horizon_minutes,
                    "predicted_score": current.predicted_score,
                    "lower_bound": current.lower_bound,
                    "upper_bound": current.upper_bound,
                    "change_per_hour": current.change_per_hour,
                    "direction": current.direction,
                    "method": current.method,
                }
            },
        )

    @staticmethod
    def _snapshot_value(snapshot: HealthSnapshot, metric: AlertMetric) -> float | None:
        value = getattr(snapshot, metric.value, None)
        return float(value) if value is not None else None

    @staticmethod
    def _snapshots(
        session: Session,
        model_id: str,
        rule: AlertRule,
        evaluated_at: datetime,
    ) -> list[HealthSnapshot]:
        cutoff = evaluated_at - timedelta(minutes=rule.window_minutes)
        return list(
            session.scalars(
                select(HealthSnapshot)
                .where(
                    HealthSnapshot.model_id == model_id,
                    HealthSnapshot.observed_at >= cutoff,
                    HealthSnapshot.observed_at <= evaluated_at,
                )
                .order_by(HealthSnapshot.observed_at, HealthSnapshot.id)
            ).all()
        )

    @staticmethod
    def _active_alert(session: Session, rule_id: str) -> Alert | None:
        return session.scalar(
            select(Alert)
            .where(
                Alert.rule_id == rule_id,
                Alert.state.in_([AlertState.FIRING.value, AlertState.ACKNOWLEDGED.value]),
            )
            .order_by(Alert.fired_at.desc())
            .limit(1)
        )

    @staticmethod
    def _cooling_down(
        session: Session,
        rule: AlertRule,
        *,
        evaluated_at: datetime,
    ) -> bool:
        recent = session.scalar(
            select(Alert).where(Alert.rule_id == rule.id).order_by(Alert.fired_at.desc()).limit(1)
        )
        if recent is None or recent.resolved_at is None:
            return False
        return evaluated_at < _as_utc(recent.resolved_at) + timedelta(
            minutes=rule.cooldown_minutes
        )

    @staticmethod
    def _resolve(alert: Alert, evaluated_at: datetime, reason: str) -> None:
        alert.state = AlertState.RESOLVED.value
        alert.resolved_at = evaluated_at
        alert.resolution_reason = reason

    @staticmethod
    def _inconclusive(rule: AlertRule, reason: str) -> RuleDecision:
        return RuleDecision(
            evaluable=False,
            should_fire=False,
            condition_active=False,
            observed_value=None,
            message=f"{rule.name}: evaluation is inconclusive.",
            details={
                "rule_name": rule.name,
                "rule_type": rule.rule_type,
                "metric": rule.metric,
                "reason": reason,
            },
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
