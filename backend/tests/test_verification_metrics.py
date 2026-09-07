"""The metric formulas must be arithmetic, not judgement.

Every case here pins a rule the design depends on: absent evidence is not a
perfect score, an unsupported claim is not a confirmed hallucination, and a
refuted central claim cannot be averaged away by correct trivia.
"""

from __future__ import annotations

from app.schemas import ClaimImportance, ClaimVerdictValue
from app.verification import (
    CENTRAL_CONTRADICTION_CORRECTNESS_CAP,
    CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP,
    ClaimOutcome,
    CorrectnessConfidence,
    RubricScores,
    score_groundedness,
    score_quality,
)


def claim(importance: ClaimImportance, verdict: ClaimVerdictValue) -> ClaimOutcome:
    return ClaimOutcome(importance=importance, verdict=verdict)


CENTRAL = ClaimImportance.CENTRAL
SUPPORTING = ClaimImportance.SUPPORTING
MINOR = ClaimImportance.MINOR

SUPPORTED = ClaimVerdictValue.SUPPORTED
CONTRADICTED = ClaimVerdictValue.CONTRADICTED
INSUFFICIENT = ClaimVerdictValue.INSUFFICIENT_EVIDENCE
NOT_VERIFIABLE = ClaimVerdictValue.NOT_VERIFIABLE
NOT_APPLICABLE = ClaimVerdictValue.NOT_APPLICABLE


def test_importance_weights_are_three_two_one() -> None:
    assert claim(CENTRAL, SUPPORTED).weight == 3
    assert claim(SUPPORTING, SUPPORTED).weight == 2
    assert claim(MINOR, SUPPORTED).weight == 1


def test_every_claim_supported_scores_one_hundred() -> None:
    result = score_groundedness([claim(CENTRAL, SUPPORTED), claim(MINOR, SUPPORTED)])

    assert result.groundedness == 100.0
    assert result.confirmed_hallucination_rate == 0.0
    assert result.evidence_coverage == 100.0
    assert result.total_factual_weight == 4


def test_groundedness_is_weighted_not_a_plain_count() -> None:
    # One supported central claim (3) against one contradicted minor claim (1).
    # A naive per-claim average would say 50; weighting says 75.
    result = score_groundedness([claim(CENTRAL, SUPPORTED), claim(MINOR, CONTRADICTED)])

    assert result.groundedness == 75.0
    assert result.confirmed_hallucination_rate == 25.0


def test_no_factual_claims_yields_null_not_a_perfect_score() -> None:
    """A response that asserted nothing checkable must not outrank one that did."""

    result = score_groundedness([claim(MINOR, NOT_VERIFIABLE), claim(MINOR, NOT_APPLICABLE)])

    assert result.groundedness is None
    assert result.confirmed_hallucination_rate is None
    assert result.evidence_coverage is None
    assert result.total_factual_weight == 0


def test_empty_claim_list_yields_null() -> None:
    assert score_groundedness([]).groundedness is None


def test_predictions_are_excluded_from_the_denominator() -> None:
    """A model is neither punished nor rewarded for declining to assert a fact."""

    with_prediction = score_groundedness(
        [claim(CENTRAL, SUPPORTED), claim(CENTRAL, NOT_VERIFIABLE)]
    )
    without = score_groundedness([claim(CENTRAL, SUPPORTED)])

    assert with_prediction.groundedness == without.groundedness == 100.0
    assert with_prediction.total_factual_weight == 3
    assert with_prediction.verdict_counts["not_verifiable"] == 1


def test_insufficient_evidence_is_not_counted_as_hallucination() -> None:
    """The distinction the product turns on: unproven is not disproven."""

    result = score_groundedness([claim(CENTRAL, SUPPORTED), claim(CENTRAL, INSUFFICIENT)])

    assert result.confirmed_hallucination_rate == 0.0
    assert result.insufficient_weight == 3
    assert result.contradicted_weight == 0
    # It still lowers groundedness -- an unverifiable claim is not a supported one.
    assert result.groundedness == 50.0


def test_evidence_coverage_excludes_insufficient_evidence() -> None:
    result = score_groundedness(
        [claim(CENTRAL, SUPPORTED), claim(CENTRAL, CONTRADICTED), claim(CENTRAL, INSUFFICIENT)]
    )

    # Six of nine weight units were actually reachable in the corpus.
    assert result.evidence_coverage == round(100.0 * 6 / 9, 1)


def test_contradicted_central_claim_caps_groundedness() -> None:
    """Correct supporting detail cannot redeem being wrong about the question."""

    outcomes = [claim(CENTRAL, CONTRADICTED)] + [claim(MINOR, SUPPORTED) for _ in range(20)]
    result = score_groundedness(outcomes)

    assert result.central_contradiction is True
    assert result.capped is True
    assert result.groundedness == CENTRAL_CONTRADICTION_GROUNDEDNESS_CAP


def test_cap_never_raises_a_lower_score() -> None:
    """The cap is a ceiling, not a floor."""

    result = score_groundedness([claim(CENTRAL, CONTRADICTED)])

    assert result.groundedness == 0.0
    assert result.capped is False


def test_a_contradicted_supporting_claim_does_not_trigger_the_cap() -> None:
    result = score_groundedness(
        [claim(CENTRAL, SUPPORTED), claim(CENTRAL, SUPPORTED), claim(SUPPORTING, CONTRADICTED)]
    )

    assert result.central_contradiction is False
    assert result.capped is False
    assert result.groundedness == 75.0


def test_formula_string_shows_the_arithmetic() -> None:
    result = score_groundedness([claim(CENTRAL, SUPPORTED), claim(CENTRAL, INSUFFICIENT)])

    assert "100 x 3 / 6" in result.formula


def test_formula_string_explains_the_cap() -> None:
    outcomes = [claim(CENTRAL, CONTRADICTED)] + [claim(MINOR, SUPPORTED) for _ in range(20)]

    assert "capped at 40" in score_groundedness(outcomes).formula


def test_quality_is_the_documented_weighted_mean() -> None:
    grounded = score_groundedness([claim(CENTRAL, SUPPORTED)])
    result = score_quality(
        RubricScores(correctness=4, relevance=4, completeness=4, instruction_adherence=4),
        grounded,
    )

    assert result.quality == 100.0
    assert result.correctness_confidence is CorrectnessConfidence.NORMAL


def test_quality_weights_correctness_at_forty_percent() -> None:
    grounded = score_groundedness([claim(CENTRAL, SUPPORTED)])
    result = score_quality(
        RubricScores(correctness=0, relevance=4, completeness=4, instruction_adherence=4),
        grounded,
    )

    # 0.4*0 + 0.2*100 + 0.2*100 + 0.2*100
    assert result.quality == 60.0


def test_contradicted_central_claim_caps_correctness() -> None:
    grounded = score_groundedness([claim(CENTRAL, CONTRADICTED)])
    result = score_quality(
        RubricScores(correctness=4, relevance=4, completeness=4, instruction_adherence=4),
        grounded,
    )

    assert result.correctness == CENTRAL_CONTRADICTION_CORRECTNESS_CAP
    assert result.correctness_capped is True
    # 0.4*50 + 0.2*100 * 3
    assert result.quality == 80.0


def test_thin_evidence_coverage_marks_correctness_low_confidence() -> None:
    # Two of three weight units are unreachable, so coverage is 33% -- below 60.
    grounded = score_groundedness([claim(CENTRAL, INSUFFICIENT), claim(SUPPORTING, SUPPORTED)])
    result = score_quality(RubricScores(correctness=3), grounded)

    assert grounded.evidence_coverage is not None
    assert grounded.evidence_coverage < 60
    assert result.correctness_confidence is CorrectnessConfidence.LOW


def test_unassessed_correctness_is_null_not_zero() -> None:
    grounded = score_groundedness([claim(CENTRAL, SUPPORTED)])
    result = score_quality(RubricScores(relevance=4, completeness=4), grounded)

    assert result.correctness is None
    assert result.correctness_confidence is CorrectnessConfidence.UNAVAILABLE
    # The missing component is dropped from the mean rather than scored zero.
    assert result.quality == 100.0
    assert "correctness" in result.missing_components


def test_quality_is_null_when_nothing_was_assessed() -> None:
    grounded = score_groundedness([claim(CENTRAL, SUPPORTED)])

    assert score_quality(RubricScores(), grounded).quality is None


def test_rubric_points_normalize_onto_the_zero_to_hundred_scale() -> None:
    grounded = score_groundedness([claim(CENTRAL, SUPPORTED)])
    scores = [
        score_quality(RubricScores(correctness=point), grounded).correctness for point in range(5)
    ]

    assert scores == [0.0, 25.0, 50.0, 75.0, 100.0]
