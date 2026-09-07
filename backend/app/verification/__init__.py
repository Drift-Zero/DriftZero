"""Evidence-grounded claim verification.

An evaluator model may extract claims and classify them against supplied
evidence. It never produces a groundedness, quality or health number: every
displayed metric is calculated here, in Python, from documented formulas over
those verdicts. That split is the point of the package -- a score a model
invented cannot be audited, reproduced, or defended to an operator.
"""

from __future__ import annotations

from app.verification.metrics import (
    CENTRAL_CONTRADICTION_CORRECTNESS_CAP,
    CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP,
    IMPORTANCE_WEIGHTS,
    LOW_CONFIDENCE_COVERAGE,
    QUALITY_WEIGHTS,
    ClaimOutcome,
    CorrectnessConfidence,
    GroundednessResult,
    QualityResult,
    RubricScores,
    score_groundedness,
    score_quality,
)

__all__ = [
    "CENTRAL_CONTRADICTION_CORRECTNESS_CAP",
    "CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP",
    "IMPORTANCE_WEIGHTS",
    "LOW_CONFIDENCE_COVERAGE",
    "QUALITY_WEIGHTS",
    "ClaimOutcome",
    "CorrectnessConfidence",
    "GroundednessResult",
    "QualityResult",
    "RubricScores",
    "score_groundedness",
    "score_quality",
]
