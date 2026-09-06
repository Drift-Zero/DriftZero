from datetime import UTC, datetime, timedelta

from app.diagnosis import diagnose_change
from app.schemas import DimensionScores, HealthState
from app.scoring import calculate_health, forecast_health


def all_dimensions(value: float) -> DimensionScores:
    return DimensionScores(
        quality=value,
        groundedness=value,
        semantic_stability=value,
        temporal_stability=value,
        safety=value,
        drift=value,
        reliability=value,
        latency=value,
        cost=value,
    )


def test_health_score_is_weighted_and_reports_confidence() -> None:
    result = calculate_health(all_dimensions(80), sample_size=100, coverage=0.80)

    assert result.score == 80
    assert result.state == HealthState.HEALTHY
    assert result.confidence == 0.80
    assert result.missing_dimensions == []


def test_health_score_refuses_false_precision_for_small_samples() -> None:
    result = calculate_health(all_dimensions(90), sample_size=5, coverage=1)

    assert result.score is None
    assert result.state == HealthState.INSUFFICIENT_DATA
    assert result.confidence == 0.05


def test_forecast_projects_latest_trajectory_with_bounds() -> None:
    now = datetime.now(UTC)
    forecast = forecast_health(
        [
            (now - timedelta(minutes=90), 92),
            (now - timedelta(minutes=60), 87),
            (now - timedelta(minutes=30), 74),
            (now, 61),
        ],
        horizon_minutes=30,
    )

    assert forecast is not None
    assert forecast.predicted_score == 48
    assert forecast.lower_bound < forecast.predicted_score < forecast.upper_bound
    assert forecast.direction == "deteriorating"


def test_knowledge_freshness_diagnosis_exposes_evidence() -> None:
    baseline = DimensionScores(
        quality=90.4,
        groundedness=92,
        semantic_stability=92,
        temporal_stability=92,
        safety=94,
        drift=92,
        reliability=92,
        latency=94,
        cost=91,
    )
    current = DimensionScores(
        quality=61,
        groundedness=30,
        semantic_stability=35,
        temporal_stability=61,
        safety=94,
        drift=58,
        reliability=88,
        latency=94,
        cost=85,
    )

    diagnosis = diagnose_change(baseline, current)

    assert diagnosis.probable_cause == "knowledge_freshness_failure"
    assert diagnosis.confidence == 0.87
    assert {item.reason_code for item in diagnosis.evidence} >= {
        "GROUNDEDNESS_DETERIORATED",
        "SEMANTIC_STABILITY_DETERIORATED",
        "SAFETY_REMAINED_STABLE",
    }

