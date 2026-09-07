import pytest

from app.metric_formulas import (
    consistency_score,
    cost_efficiency_score,
    groundedness_score,
    health_score,
    latency_score,
    quality_score,
    reliability_score,
    safety_score,
)


def test_documented_quality_formula() -> None:
    assert quality_score(
        correctness=95, relevance=90, completeness=80, feedback=85
    ) == pytest.approx(89.5)


def test_documented_ratio_and_average_formulas() -> None:
    assert groundedness_score(supported_claims=10, total_claims=12) == pytest.approx(83.3333)
    assert reliability_score(successful_requests=980, total_requests=1000) == 98
    assert consistency_score([0.96, 0.94, 0.91]) == pytest.approx(93.6667)
    assert safety_score(unsafe_responses=4, total_responses=500) == pytest.approx(99.2)


def test_documented_latency_and_cost_formulas_are_bounded() -> None:
    assert latency_score(current_ms=800, best_ms=200, worst_ms=2000) == pytest.approx(66.6667)
    assert cost_efficiency_score(current_cost=0.03, maximum_cost=0.05) == pytest.approx(40)
    assert latency_score(current_ms=3000, best_ms=200, worst_ms=2000) == 0
    assert cost_efficiency_score(current_cost=0.06, maximum_cost=0.05) == 0


def test_documented_health_formula() -> None:
    assert health_score({
        "quality": 90,
        "groundedness": 84,
        "reliability": 95,
        "semantic_stability": 88,
        "safety": 99,
        "latency": 72,
        "cost": 80,
    }) == pytest.approx(89)
