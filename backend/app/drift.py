"""Transparent input/retrieval drift detection.

The ``drift`` health dimension is meant to capture a shift in what the model
is being asked, or what it retrieves to answer -- as distinct from
groundedness (whether an answer is supported) or stability (whether repeated
questions get consistent answers). This module gives that dimension a real,
inspectable computation instead of leaving it as a value only a caller can
ever supply: it compares the retrieved-document distribution of the current
window against a preceding baseline window and reports how much it moved.
"""

from __future__ import annotations

from collections import Counter
from typing import Protocol


class RetrievalSignal(Protocol):
    retrieved_document_ids: list[str]


def _document_distribution(traces: list[RetrievalSignal]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for trace in traces:
        counts.update(trace.retrieved_document_ids)
    return counts


def total_variation_distance(current: Counter[str], baseline: Counter[str]) -> float:
    """Return how far two document-frequency distributions have moved, in [0, 1].

    0 means the two windows retrieved the same documents in the same
    proportions; 1 means they share nothing. This is the standard total
    variation distance between the two normalized frequency vectors.
    """

    current_total = sum(current.values())
    baseline_total = sum(baseline.values())
    if current_total == 0 or baseline_total == 0:
        return 0.0

    documents = set(current) | set(baseline)
    deviation = sum(
        abs(current[doc] / current_total - baseline[doc] / baseline_total) for doc in documents
    )
    return min(1.0, deviation / 2)


def score_drift(
    current_traces: list[RetrievalSignal],
    baseline_traces: list[RetrievalSignal],
) -> float | None:
    """Return a 0-100 drift dimension where 100 means no detected movement.

    Both windows need at least one trace with retrieval evidence, or there is
    nothing to compare and the result is left unscored rather than assumed
    stable.
    """

    current_distribution = _document_distribution(current_traces)
    baseline_distribution = _document_distribution(baseline_traces)
    if not current_distribution or not baseline_distribution:
        return None

    distance = total_variation_distance(current_distribution, baseline_distribution)
    return round(100.0 * (1 - distance), 1)
