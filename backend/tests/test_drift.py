"""Unit tests for retrieval-distribution drift detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.drift import score_drift, total_variation_distance


@dataclass
class FakeTrace:
    retrieved_document_ids: list[str] = field(default_factory=list)


def test_identical_distributions_have_no_drift() -> None:
    current = [FakeTrace(["d1", "d2"]), FakeTrace(["d1"])]
    baseline = [FakeTrace(["d1", "d2"]), FakeTrace(["d1"])]
    assert score_drift(current, baseline) == 100.0


def test_disjoint_distributions_score_zero() -> None:
    current = [FakeTrace(["d1"]), FakeTrace(["d1"])]
    baseline = [FakeTrace(["d2"]), FakeTrace(["d2"])]
    assert score_drift(current, baseline) == 0.0


def test_partial_shift_scores_between_extremes() -> None:
    current = [FakeTrace(["d1"]), FakeTrace(["d2"])]
    baseline = [FakeTrace(["d1"]), FakeTrace(["d1"])]
    score = score_drift(current, baseline)
    assert score is not None
    assert 0.0 < score < 100.0


def test_missing_retrieval_evidence_on_either_side_is_unscored() -> None:
    current = [FakeTrace(["d1"])]
    assert score_drift(current, []) is None
    assert score_drift([], current) is None
    assert score_drift([FakeTrace([])], [FakeTrace([])]) is None


def test_total_variation_distance_is_symmetric() -> None:
    from collections import Counter

    a = Counter({"d1": 3, "d2": 1})
    b = Counter({"d1": 1, "d2": 3})
    assert total_variation_distance(a, b) == total_variation_distance(b, a)
