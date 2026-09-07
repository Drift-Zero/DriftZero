"""Public, deterministic formulas used by DriftZero's scoring pipelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

QUALITY_WEIGHTS = {
    "correctness": 0.40,
    "relevance": 0.30,
    "completeness": 0.20,
    "feedback": 0.10,
}

HEALTH_WEIGHTS = {
    "quality": 0.25,
    "groundedness": 0.20,
    "reliability": 0.20,
    "semantic_stability": 0.15,
    "safety": 0.10,
    "latency": 0.05,
    "cost": 0.05,
}


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def weighted_score(
    values: Mapping[str, float | None], weights: Mapping[str, float]
) -> float | None:
    """Weighted arithmetic mean, reweighted over explicitly measured values."""

    present = {name: clamp_score(value) for name, value in values.items() if value is not None}
    weight_total = sum(weights[name] for name in present if name in weights)
    if weight_total <= 0:
        return None
    weighted_total = sum(
        weights[name] * value for name, value in present.items() if name in weights
    )
    return weighted_total / weight_total


def quality_score(
    *, correctness: float | None, relevance: float | None,
    completeness: float | None, feedback: float | None
) -> float | None:
    return weighted_score(locals(), QUALITY_WEIGHTS)


def groundedness_score(*, supported_claims: int, total_claims: int) -> float | None:
    if total_claims <= 0:
        return None
    return clamp_score(100.0 * supported_claims / total_claims)


def reliability_score(*, successful_requests: int, total_requests: int) -> float | None:
    if total_requests <= 0:
        return None
    return clamp_score(100.0 * successful_requests / total_requests)


def consistency_score(similarities: Iterable[float]) -> float | None:
    """Average similarities expressed on the conventional 0..1 scale."""

    values = [max(0.0, min(1.0, float(value))) for value in similarities]
    return 100.0 * sum(values) / len(values) if values else None


def safety_score(*, unsafe_responses: int, total_responses: int) -> float | None:
    if total_responses <= 0:
        return None
    return clamp_score((1.0 - unsafe_responses / total_responses) * 100.0)


def latency_score(*, current_ms: float, best_ms: float, worst_ms: float) -> float:
    if worst_ms <= best_ms:
        raise ValueError("worst_ms must be greater than best_ms")
    return clamp_score((1.0 - (current_ms - best_ms) / (worst_ms - best_ms)) * 100.0)


def cost_efficiency_score(*, current_cost: float, maximum_cost: float) -> float:
    if maximum_cost <= 0:
        raise ValueError("maximum_cost must be greater than zero")
    return clamp_score((1.0 - current_cost / maximum_cost) * 100.0)


def health_score(dimensions: Mapping[str, float | None]) -> float | None:
    return weighted_score(dimensions, HEALTH_WEIGHTS)
