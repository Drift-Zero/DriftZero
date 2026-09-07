"""Deterministic metric calculation over claim verdicts.

Every formula here is public and reproducible from the stored verdicts, so an
operator asking "why is groundedness 63?" gets arithmetic rather than an
assertion. Nothing in this module calls a model.

Two distinctions do the real work:

* **Contradicted is not the same as unsupported.** A claim the evidence
  actively refutes is a confirmed hallucination. A claim the corpus simply
  does not cover is ``insufficient_evidence`` -- reported separately, and never
  presented as a hallucination.
* **Absent evidence is not a perfect score.** With no factual claims to check,
  groundedness is ``None``. Returning 100 would let a response full of opinion
  outrank one that made checkable claims and got them right.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.schemas import ClaimImportance, ClaimVerdictValue

# A claim's contribution is weighted by how much the answer depends on it.
IMPORTANCE_WEIGHTS: dict[ClaimImportance, int] = {
    ClaimImportance.CENTRAL: 3,
    ClaimImportance.SUPPORTING: 2,
    ClaimImportance.MINOR: 1,
}

# Only these verdicts describe a factual claim that could be checked. A
# prediction or a non-factual statement is excluded from the denominator
# rather than counted against the model.
FACTUAL_VERDICTS: frozenset[ClaimVerdictValue] = frozenset(
    {
        ClaimVerdictValue.SUPPORTED,
        ClaimVerdictValue.CONTRADICTED,
        ClaimVerdictValue.INSUFFICIENT_EVIDENCE,
    }
)

# A refuted central claim means the answer was wrong about the thing it was
# asked. Supporting detail being right cannot redeem that, so the aggregate is
# capped rather than averaged.
CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP = 40.0
CENTRAL_CONTRADICTION_CORRECTNESS_CAP = 50.0

# Below this share of claims actually reachable in the corpus, correctness is
# still reported but flagged: it rests on too little evidence to lean on.
LOW_CONFIDENCE_COVERAGE = 60.0

QUALITY_WEIGHTS: dict[str, float] = {
    "correctness": 0.40,
    "relevance": 0.20,
    "completeness": 0.20,
    "instruction_adherence": 0.20,
}

# Anchored rubric: 0 complete failure, 1 major problems, 2 partially
# acceptable, 3 mostly correct, 4 fully correct.
RUBRIC_MAX = 4


class CorrectnessConfidence(StrEnum):
    NORMAL = "normal"
    LOW = "low"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ClaimOutcome:
    """One verified claim, reduced to what the formulas need."""

    importance: ClaimImportance
    verdict: ClaimVerdictValue

    @property
    def weight(self) -> int:
        return IMPORTANCE_WEIGHTS[self.importance]


@dataclass(frozen=True, slots=True)
class GroundednessResult:
    """A groundedness figure together with everything needed to re-derive it."""

    groundedness: float | None
    confirmed_hallucination_rate: float | None
    evidence_coverage: float | None
    supported_weight: int
    contradicted_weight: int
    insufficient_weight: int
    total_factual_weight: int
    central_contradiction: bool
    capped: bool
    verdict_counts: dict[str, int]

    @property
    def formula(self) -> str:
        """The exact arithmetic, for display beside the number."""

        if self.total_factual_weight == 0:
            return "No factual claims to verify, so groundedness is unavailable."
        base = (
            f"100 x {self.supported_weight} / {self.total_factual_weight}"
            f" = {self._raw():.1f}"
        )
        if self.capped:
            return (
                f"{base}, capped at {CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP:.0f}"
                " because a central claim is contradicted."
            )
        return base

    def _raw(self) -> float:
        return 100.0 * self.supported_weight / self.total_factual_weight


def score_groundedness(outcomes: list[ClaimOutcome]) -> GroundednessResult:
    """Reduce a response's claim verdicts to groundedness and its companions.

    ``not_verifiable`` and ``not_applicable`` claims are counted for display but
    excluded from every denominator: a model should not be penalised for
    declining to assert a checkable fact, nor rewarded for it.
    """

    counts = {verdict.value: 0 for verdict in ClaimVerdictValue}
    for outcome in outcomes:
        counts[outcome.verdict.value] += 1

    def weight_of(verdict: ClaimVerdictValue) -> int:
        return sum(item.weight for item in outcomes if item.verdict is verdict)

    supported = weight_of(ClaimVerdictValue.SUPPORTED)
    contradicted = weight_of(ClaimVerdictValue.CONTRADICTED)
    insufficient = weight_of(ClaimVerdictValue.INSUFFICIENT_EVIDENCE)
    total = supported + contradicted + insufficient

    central_contradiction = any(
        item.importance is ClaimImportance.CENTRAL
        and item.verdict is ClaimVerdictValue.CONTRADICTED
        for item in outcomes
    )

    if total == 0:
        # No checkable claim was made. Silence is not grounding.
        return GroundednessResult(
            groundedness=None,
            confirmed_hallucination_rate=None,
            evidence_coverage=None,
            supported_weight=0,
            contradicted_weight=0,
            insufficient_weight=0,
            total_factual_weight=0,
            central_contradiction=central_contradiction,
            capped=False,
            verdict_counts=counts,
        )

    raw = 100.0 * supported / total
    capped = central_contradiction and raw > CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP
    groundedness = CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP if capped else raw

    return GroundednessResult(
        groundedness=round(groundedness, 1),
        confirmed_hallucination_rate=round(100.0 * contradicted / total, 1),
        evidence_coverage=round(100.0 * (supported + contradicted) / total, 1),
        supported_weight=supported,
        contradicted_weight=contradicted,
        insufficient_weight=insufficient,
        total_factual_weight=total,
        central_contradiction=central_contradiction,
        capped=capped,
        verdict_counts=counts,
    )


@dataclass(frozen=True, slots=True)
class RubricScores:
    """Anchored 0-4 judgements. ``None`` means not assessed, never zero."""

    correctness: int | None = None
    relevance: int | None = None
    completeness: int | None = None
    instruction_adherence: int | None = None


@dataclass(frozen=True, slots=True)
class QualityResult:
    quality: float | None
    correctness: float | None
    correctness_confidence: CorrectnessConfidence
    correctness_capped: bool
    components: dict[str, float | None]
    missing_components: list[str]


def _normalize(score: int | None) -> float | None:
    """Map an anchored 0-4 rubric point onto 0-100."""

    if score is None:
        return None
    bounded = max(0, min(RUBRIC_MAX, score))
    return round(100.0 * bounded / RUBRIC_MAX, 1)


def score_quality(rubric: RubricScores, groundedness: GroundednessResult) -> QualityResult:
    """Combine the rubric into one quality figure, constrained by verification.

    Correctness cannot outrun the evidence: a contradicted central claim caps
    it, and thin evidence coverage marks it low-confidence rather than silently
    passing it off as reliable. A component that was not assessed is dropped
    from the weighted mean instead of being treated as a zero, which would turn
    "not measured" into "measured badly".
    """

    correctness = _normalize(rubric.correctness)
    correctness_capped = False
    if (
        correctness is not None
        and groundedness.central_contradiction
        and correctness > CENTRAL_CONTRADICTION_CORRECTNESS_CAP
    ):
        correctness = CENTRAL_CONTRADICTION_CORRECTNESS_CAP
        correctness_capped = True

    if correctness is None:
        confidence = CorrectnessConfidence.UNAVAILABLE
    elif (
        groundedness.evidence_coverage is None
        or groundedness.evidence_coverage < LOW_CONFIDENCE_COVERAGE
    ):
        confidence = CorrectnessConfidence.LOW
    else:
        confidence = CorrectnessConfidence.NORMAL

    components: dict[str, float | None] = {
        "correctness": correctness,
        "relevance": _normalize(rubric.relevance),
        "completeness": _normalize(rubric.completeness),
        "instruction_adherence": _normalize(rubric.instruction_adherence),
    }
    missing = sorted(name for name, value in components.items() if value is None)

    available = {name: value for name, value in components.items() if value is not None}
    if not available:
        return QualityResult(
            quality=None,
            correctness=correctness,
            correctness_confidence=confidence,
            correctness_capped=correctness_capped,
            components=components,
            missing_components=missing,
        )

    weight_total = sum(QUALITY_WEIGHTS[name] for name in available)
    weighted = sum(QUALITY_WEIGHTS[name] * value for name, value in available.items())
    return QualityResult(
        quality=round(weighted / weight_total, 1),
        correctness=correctness,
        correctness_confidence=confidence,
        correctness_capped=correctness_capped,
        components=components,
        missing_components=missing,
    )
