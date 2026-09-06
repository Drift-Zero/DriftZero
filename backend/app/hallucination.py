"""Transparent hallucination (groundedness) detection from trace-level signal.

A trace already carries an authoritative ``groundedness_score`` when an
upstream evaluator produced one. This module exists for the traces that
don't: it turns ``citation_count``, ``unsupported_claim_count`` and
``retrieved_document_ids`` into the same 0-100 groundedness scale, so a
caller that only ships raw counts still gets a real hallucination signal
instead of a missing dimension.
"""

from __future__ import annotations

from typing import Protocol


class GroundednessSignal(Protocol):
    groundedness_score: float | None
    citation_count: int
    unsupported_claim_count: int
    retrieved_document_ids: list[str]


def estimate_trace_groundedness(trace: GroundednessSignal) -> float | None:
    """Return one trace's groundedness, computed if not already scored.

    A claim is "supported" if it carries a citation. The ratio of supported to
    total claims is the estimate; a claim asserted with no retrieval at all is
    the clearest hallucination signal available and is scored at 0 rather than
    left unscored.
    """

    if trace.groundedness_score is not None:
        return trace.groundedness_score

    total_claims = trace.citation_count + trace.unsupported_claim_count
    if total_claims == 0:
        return None

    if not trace.retrieved_document_ids and trace.unsupported_claim_count > 0:
        return 0.0

    return round(100.0 * trace.citation_count / total_claims, 1)


def score_groundedness(traces: list[GroundednessSignal]) -> float | None:
    """Aggregate a window of traces into one groundedness dimension score.

    Traces with no usable signal (no citations, no unsupported claims, and no
    explicit score) are excluded rather than counted as perfectly grounded --
    silence is not evidence of grounding.
    """

    estimates = [
        estimate for trace in traces if (estimate := estimate_trace_groundedness(trace)) is not None
    ]
    if not estimates:
        return None
    return round(sum(estimates) / len(estimates), 1)
