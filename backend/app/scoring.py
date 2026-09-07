"""Transparent health scoring and short-horizon trajectory forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import pstdev

from app.metric_formulas import HEALTH_WEIGHTS
from app.schemas import DimensionScores, HealthForecast, HealthState

POLICY_VERSION = "health-v2"

# Higher always means healthier. Weights sum to 1.0 and are intentionally public.
DIMENSION_WEIGHTS: dict[str, float] = dict(HEALTH_WEIGHTS)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: float | None
    state: HealthState
    confidence: float
    missing_dimensions: list[str]
    policy_version: str = POLICY_VERSION


def calculate_health(
    dimensions: DimensionScores,
    *,
    sample_size: int,
    coverage: float,
    minimum_sample_size: int = 20,
    minimum_coverage: float = 0.30,
) -> ScoreResult:
    """Return a weighted score only when the evidence clears coverage gates."""

    values = dimensions.model_dump()
    available = {
        name: value
        for name, value in values.items()
        if value is not None and name in DIMENSION_WEIGHTS
    }
    missing = [name for name in DIMENSION_WEIGHTS if name not in available]
    available_weight = sum(DIMENSION_WEIGHTS[name] for name in available)
    dimension_coverage = available_weight / sum(DIMENSION_WEIGHTS.values())
    confidence = round(
        max(0.0, min(1.0, coverage))
        * min(1.0, sample_size / 100)
        * dimension_coverage,
        2,
    )

    if (
        sample_size < minimum_sample_size
        or coverage < minimum_coverage
        or available_weight < 0.50
    ):
        return ScoreResult(
            score=None,
            state=HealthState.INSUFFICIENT_DATA,
            confidence=confidence,
            missing_dimensions=missing,
        )

    weighted_total = sum(
        float(value) * DIMENSION_WEIGHTS[name] for name, value in available.items()
    )
    score = round(weighted_total / available_weight, 1)
    return ScoreResult(
        score=score,
        state=classify_health(score),
        confidence=confidence,
        missing_dimensions=missing,
    )


def classify_health(score: float) -> HealthState:
    if score >= 80:
        return HealthState.HEALTHY
    if score >= 65:
        return HealthState.WARNING
    return HealthState.CRITICAL


def forecast_health(
    points: list[tuple[datetime, float]],
    *,
    horizon_minutes: int = 30,
) -> HealthForecast | None:
    """Project the latest observed slope and expose a variability-based interval.

    This deliberately simple baseline is inspectable and replaceable once real
    incident labels exist. At least two scored snapshots are required.
    """

    ordered = sorted(points, key=lambda point: point[0])[-6:]
    if len(ordered) < 2:
        return None

    previous_time, previous_score = ordered[-2]
    current_time, current_score = ordered[-1]
    elapsed_minutes = (current_time - previous_time).total_seconds() / 60
    if elapsed_minutes <= 0:
        return None

    latest_slope = (current_score - previous_score) / elapsed_minutes
    predicted = _clamp_score(current_score + latest_slope * horizon_minutes)

    historical_slopes: list[float] = []
    for (start_time, start_score), (end_time, end_score) in zip(
        ordered, ordered[1:], strict=False
    ):
        minutes = (end_time - start_time).total_seconds() / 60
        if minutes > 0:
            historical_slopes.append((end_score - start_score) / minutes)

    interval = 3.0
    if len(historical_slopes) > 1:
        interval = max(interval, pstdev(historical_slopes) * horizon_minutes)

    change_per_hour = round(latest_slope * 60, 1)
    if change_per_hour <= -2:
        direction = "deteriorating"
    elif change_per_hour >= 2:
        direction = "improving"
    else:
        direction = "stable"

    return HealthForecast(
        horizon_minutes=horizon_minutes,
        predicted_score=round(predicted, 1),
        lower_bound=round(_clamp_score(predicted - interval), 1),
        upper_bound=round(_clamp_score(predicted + interval), 1),
        change_per_hour=change_per_hour,
        direction=direction,
    )


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))
