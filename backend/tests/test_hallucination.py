"""Unit tests for the hallucination (groundedness) estimator."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.hallucination import estimate_trace_groundedness, score_groundedness


@dataclass
class FakeTrace:
    groundedness_score: float | None = None
    citation_count: int = 0
    unsupported_claim_count: int = 0
    retrieved_document_ids: list[str] = field(default_factory=list)


def test_explicit_score_is_trusted_verbatim() -> None:
    trace = FakeTrace(groundedness_score=42.0, citation_count=0, unsupported_claim_count=5)
    assert estimate_trace_groundedness(trace) == 42.0


def test_fully_cited_answer_scores_100() -> None:
    trace = FakeTrace(citation_count=3, unsupported_claim_count=0, retrieved_document_ids=["d1"])
    assert estimate_trace_groundedness(trace) == 100.0


def test_partially_supported_answer_is_ratio_of_supported_claims() -> None:
    trace = FakeTrace(citation_count=1, unsupported_claim_count=1, retrieved_document_ids=["d1"])
    assert estimate_trace_groundedness(trace) == 50.0


def test_unsupported_claim_with_no_retrieval_is_a_hallucination() -> None:
    trace = FakeTrace(citation_count=0, unsupported_claim_count=2, retrieved_document_ids=[])
    assert estimate_trace_groundedness(trace) == 0.0


def test_no_claims_and_no_score_has_no_signal() -> None:
    trace = FakeTrace()
    assert estimate_trace_groundedness(trace) is None


def test_score_groundedness_averages_traces_with_signal() -> None:
    traces = [
        FakeTrace(citation_count=2, unsupported_claim_count=0, retrieved_document_ids=["d1"]),
        FakeTrace(citation_count=0, unsupported_claim_count=2, retrieved_document_ids=[]),
        FakeTrace(),  # no signal, excluded rather than counted as healthy
    ]
    assert score_groundedness(traces) == 50.0


def test_score_groundedness_with_no_traces_is_none() -> None:
    assert score_groundedness([]) is None
