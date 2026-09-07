"""Deterministic, evidence-backed claim verification for connector traffic.

This is deliberately not an LLM judge. It handles auditable lexical support,
numeric conflicts, and negation conflicts. Claims that cannot be decided by
those rules remain unverified rather than being mislabeled as hallucinations.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher

from app.schemas import ClaimEvaluationResponse, EvidenceSearchHit

_CLAIM_BREAK = re.compile(r"(?<=[.!?])\s+|\n+|(?<=;)\s+")
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\w)[+-]?(?:\d[\d,]*(?:\.\d+)?%?)(?!\w)")
_NEGATIONS = frozenset({"no", "not", "never", "none", "without", "cannot", "can't"})
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


def split_claims(answer: str) -> list[str]:
    claims = [part.strip(" \t-*•") for part in _CLAIM_BREAK.split(answer)]
    return [claim for claim in claims if len(_TOKEN.findall(claim)) >= 2][:20]


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(value.casefold()) if token not in _STOPWORDS}


def _token_sequence(value: str) -> list[str]:
    return [token for token in _TOKEN.findall(value.casefold()) if token not in _STOPWORDS]


def _ordered_similarity(claim: str, evidence: str) -> float:
    """Find the best ordered evidence window so long source chunks are not penalized."""

    claim_tokens = _token_sequence(claim)
    evidence_tokens = _token_sequence(evidence)
    if not claim_tokens or not evidence_tokens:
        return 0.0
    if len(evidence_tokens) <= len(claim_tokens) + 2:
        return SequenceMatcher(None, claim_tokens, evidence_tokens).ratio()
    widths = range(max(1, len(claim_tokens) - 2), len(claim_tokens) + 3)
    return max(
        SequenceMatcher(None, claim_tokens, evidence_tokens[start : start + width]).ratio()
        for width in widths
        for start in range(0, max(1, len(evidence_tokens) - width + 1))
    )


def _numbers(value: str) -> set[str]:
    return {number.replace(",", "") for number in _NUMBER.findall(value)}


def _has_negation(value: str) -> bool:
    return bool(_tokens(value) & _NEGATIONS)


def verify_claim(
    claim: str,
    hits: list[EvidenceSearchHit],
) -> ClaimEvaluationResponse:
    claim_tokens = _tokens(claim)
    ranked: list[tuple[float, EvidenceSearchHit, float]] = []
    for hit in hits:
        evidence_tokens = _tokens(hit.evidence_quote)
        coverage = len(claim_tokens & evidence_tokens) / max(1, len(claim_tokens))
        ranked.append((coverage * 0.7 + hit.relevance * 0.3, hit, coverage))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 0.18:
        return ClaimEvaluationResponse(
            claim=claim,
            verdict="unverified",
            confidence=0.0,
            reason="No approved evidence had enough lexical overlap to verify this claim.",
        )

    combined, evidence, coverage = ranked[0]
    claim_numbers = _numbers(claim)
    evidence_numbers = _numbers(evidence.evidence_quote)
    number_conflict = bool(claim_numbers and not claim_numbers <= evidence_numbers)
    negation_conflict = _has_negation(claim) != _has_negation(evidence.evidence_quote)
    ordered_similarity = _ordered_similarity(claim, evidence.evidence_quote)
    confidence = round(min(1.0, combined), 2)

    if coverage >= 0.28 and (number_conflict or negation_conflict):
        conflict = "numeric values differ" if number_conflict else "negation differs"
        return ClaimEvaluationResponse(
            claim=claim,
            verdict="contradicted",
            confidence=max(0.55, confidence),
            reason=f"Relevant evidence was found, but {conflict}.",
            evidence=evidence,
        )
    if (
        coverage >= 0.5
        and ordered_similarity >= 0.78
        and not number_conflict
        and not negation_conflict
    ):
        return ClaimEvaluationResponse(
            claim=claim,
            verdict="supported",
            confidence=max(0.5, confidence),
            reason="The claim's material terms and numeric values occur in approved evidence.",
            evidence=evidence,
        )
    return ClaimEvaluationResponse(
        claim=claim,
        verdict="unverified",
        confidence=confidence,
        reason=(
            "Evidence was related, but deterministic rules could not prove support "
            "or contradiction."
        ),
        evidence=evidence,
    )


def verify_answer(
    answer: str,
    search: Callable[[str], list[EvidenceSearchHit]],
) -> list[ClaimEvaluationResponse]:
    return [verify_claim(claim, search(claim)) for claim in split_claims(answer)]
