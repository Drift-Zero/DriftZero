"""Rule-based, evidence-backed root-cause diagnosis for the MVP."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import DimensionScores, EvidenceItem


@dataclass(frozen=True, slots=True)
class DiagnosisResult:
    probable_cause: str
    confidence: float
    evidence: list[EvidenceItem]


def diagnose_change(
    baseline: DimensionScores,
    current: DimensionScores,
) -> DiagnosisResult:
    """Rank a root cause using visible reason codes, never hidden reasoning."""

    changes = {
        name: _change(getattr(baseline, name), getattr(current, name))
        for name in type(baseline).model_fields
    }

    if changes["safety"] is not None and changes["safety"] <= -20:
        return _safety_regression(baseline, current, changes)

    reliability_drop = changes["reliability"] or 0
    latency_drop = changes["latency"] or 0
    if reliability_drop <= -20 or latency_drop <= -20:
        return _operational_failure(baseline, current, changes)

    groundedness_drop = changes["groundedness"] or 0
    semantic_drop = changes["semantic_stability"] or 0
    if groundedness_drop <= -20 and semantic_drop <= -15:
        return _knowledge_freshness_failure(baseline, current, changes)

    temporal_drop = changes["temporal_stability"] or 0
    if semantic_drop <= -15 or temporal_drop <= -15:
        return _model_instability(baseline, current, changes)

    return DiagnosisResult(
        probable_cause="insufficient_evidence",
        confidence=0.30,
        evidence=[
            EvidenceItem(
                reason_code="NO_DOMINANT_FAILURE_PATTERN",
                metric="health_dimensions",
                summary="No supported root-cause pattern crossed its diagnosis threshold.",
                supports_diagnosis=False,
            )
        ],
    )


def _knowledge_freshness_failure(
    baseline: DimensionScores,
    current: DimensionScores,
    changes: dict[str, float | None],
) -> DiagnosisResult:
    groundedness_strength = min(abs(changes["groundedness"] or 0) / 60, 1)
    semantic_strength = min(abs(changes["semantic_stability"] or 0) / 50, 1)
    drift_strength = min(abs(min(changes["drift"] or 0, 0)) / 40, 1)
    support_strength = (groundedness_strength + semantic_strength + drift_strength) / 3
    operations_stable = all(
        abs(changes[name] or 0) < 10 for name in ("safety", "latency", "reliability")
    )
    confidence = min(0.95, 0.55 + 0.32 * support_strength + (0.02 if operations_stable else 0))

    return DiagnosisResult(
        probable_cause="knowledge_freshness_failure",
        confidence=round(confidence, 2),
        evidence=[
            _evidence(
                "GROUNDEDNESS_DETERIORATED",
                "groundedness",
                "Groundedness fell sharply against the healthy baseline.",
                baseline,
                current,
                changes,
                True,
            ),
            _evidence(
                "SEMANTIC_STABILITY_DETERIORATED",
                "semantic_stability",
                "Meaning-equivalent questions no longer produce stable facts.",
                baseline,
                current,
                changes,
                True,
            ),
            _evidence(
                "DRIFT_SIGNAL_DETERIORATED",
                "drift",
                "Retrieval or input-distribution health declined.",
                baseline,
                current,
                changes,
                True,
            ),
            _evidence(
                "SAFETY_REMAINED_STABLE",
                "safety",
                "Safety remained stable, weakening a safety-regression explanation.",
                baseline,
                current,
                changes,
                False,
            ),
            _evidence(
                "LATENCY_REMAINED_STABLE",
                "latency",
                "Latency remained stable, weakening an infrastructure explanation.",
                baseline,
                current,
                changes,
                False,
            ),
        ],
    )


def _safety_regression(
    baseline: DimensionScores,
    current: DimensionScores,
    changes: dict[str, float | None],
) -> DiagnosisResult:
    return DiagnosisResult(
        probable_cause="safety_regression",
        confidence=min(0.92, round(0.55 + abs(changes["safety"] or 0) / 100, 2)),
        evidence=[
            _evidence(
                "SAFETY_SCORE_DETERIORATED",
                "safety",
                "Safety policy compliance deteriorated materially.",
                baseline,
                current,
                changes,
                True,
            )
        ],
    )


def _operational_failure(
    baseline: DimensionScores,
    current: DimensionScores,
    changes: dict[str, float | None],
) -> DiagnosisResult:
    metric = (
        "reliability"
        if (changes["reliability"] or 0) <= (changes["latency"] or 0)
        else "latency"
    )
    return DiagnosisResult(
        probable_cause="operational_reliability_failure",
        confidence=min(0.90, round(0.55 + abs(changes[metric] or 0) / 100, 2)),
        evidence=[
            _evidence(
                "OPERATIONAL_SIGNAL_DETERIORATED",
                metric,
                f"{metric.replace('_', ' ').title()} deteriorated materially.",
                baseline,
                current,
                changes,
                True,
            )
        ],
    )


def _model_instability(
    baseline: DimensionScores,
    current: DimensionScores,
    changes: dict[str, float | None],
) -> DiagnosisResult:
    evidence = [
        _evidence(
            "SEMANTIC_OR_TEMPORAL_INSTABILITY",
            metric,
            f"{metric.replace('_', ' ').title()} deteriorated materially.",
            baseline,
            current,
            changes,
            True,
        )
        for metric in ("semantic_stability", "temporal_stability")
        if (changes[metric] or 0) <= -15
    ]
    worst_drop = min((changes[item.metric] or 0 for item in evidence), default=-15)
    return DiagnosisResult(
        probable_cause="model_or_prompt_instability",
        confidence=min(0.88, round(0.50 + abs(worst_drop) / 100, 2)),
        evidence=evidence,
    )


def _evidence(
    reason_code: str,
    metric: str,
    summary: str,
    baseline: DimensionScores,
    current: DimensionScores,
    changes: dict[str, float | None],
    supports: bool,
) -> EvidenceItem:
    return EvidenceItem(
        reason_code=reason_code,
        metric=metric,
        summary=summary,
        baseline_value=getattr(baseline, metric),
        current_value=getattr(current, metric),
        change=changes[metric],
        supports_diagnosis=supports,
    )


def _change(baseline: float | None, current: float | None) -> float | None:
    if baseline is None or current is None:
        return None
    return round(current - baseline, 1)
