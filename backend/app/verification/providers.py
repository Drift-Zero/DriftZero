"""Evaluator providers: claim extraction and natural-language verification.

The provider may only *extract* claims and *classify* them against supplied
evidence. It is never asked for a score, and any number it volunteered would be
discarded -- ``app.verification.metrics`` owns every figure the product shows.

Responses are validated against a strict schema and rejected on any deviation.
Provider output is data, never instructions: nothing returned here is executed,
interpolated into a prompt, or used to select code paths.

A rule-based extractor stands in when no key is configured. That keeps the
whole pipeline runnable offline -- useful in CI, and the reason a demo does not
depend on a third-party API being up.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.schemas import ClaimImportance, ClaimType, ClaimVerdictValue

EXTRACTOR_VERSION = "extract-v1"
VERIFIER_VERSION = "verify-v1"

MAX_CLAIMS = 24
MAX_CLAIM_CHARS = 500

EXTRACTION_SYSTEM_PROMPT = """You are a factual claim extractor. Break the assistant response \
into atomic, independently verifiable factual claims.

Rules:
1. Include only claims explicitly made by the response.
2. Never add facts or assumptions.
3. Each claim must contain exactly one independently verifiable proposition.
4. Ignore greetings, opinions, style and conversational filler.
5. Preserve numbers, currencies, units, dates, product names and named entities exactly.
6. Classify future predictions as not currently verifiable.
7. Mark each claim as central, supporting or minor based on its importance to answering the \
user's question.
8. Return valid JSON matching the supplied schema.
9. Do not determine whether claims are true.
10. Do not calculate any metric or score."""

VERIFICATION_SYSTEM_PROMPT = """You are an evidence-constrained claim verifier.

Determine whether the supplied claim is supported by the supplied evidence.

Rules:
1. Use only the supplied evidence.
2. Do not use outside knowledge.
3. Do not assume missing facts.
4. Return supported only when the evidence directly entails the claim.
5. Return contradicted only when the evidence directly conflicts with the claim.
6. Return insufficient_evidence when the evidence neither supports nor contradicts the claim.
7. Return not_verifiable for future predictions or claims whose truth is not currently \
observable.
8. Quote or identify the exact evidence passage supporting the verdict.
9. Do not calculate groundedness, quality or health scores.
10. Return valid JSON matching the supplied schema."""


class EvaluatorError(RuntimeError):
    """A provider call failed. Never carries a credential or prompt content."""


class EvaluatorSchemaError(EvaluatorError):
    """The provider returned something that is not the agreed schema."""


@dataclass(frozen=True, slots=True)
class ExtractedClaimPayload:
    text: str
    claim_type: ClaimType
    importance: ClaimImportance


@dataclass(frozen=True, slots=True)
class VerifierPayload:
    verdict: ClaimVerdictValue
    evidence_id: str | None
    explanation: str
    confidence: float | None


class EvaluatorProvider(Protocol):
    """The transport a provider must offer. Deliberately tiny."""

    name: str
    model: str

    def complete(self, *, system: str, user: str) -> str: ...


# --------------------------------------------------------------------------- #
# Strict response validation
# --------------------------------------------------------------------------- #


def _loads(raw: str) -> Any:
    """Parse provider JSON, tolerating a fenced code block but nothing else."""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvaluatorSchemaError("Evaluator returned invalid JSON.") from exc


def parse_extraction(raw: str) -> list[ExtractedClaimPayload]:
    """Validate an extractor response, rejecting anything off-schema."""

    document = _loads(raw)
    if not isinstance(document, dict):
        raise EvaluatorSchemaError("Extractor response must be a JSON object.")
    claims = document.get("claims")
    if not isinstance(claims, list):
        raise EvaluatorSchemaError("Extractor response must carry a 'claims' array.")
    if len(claims) > MAX_CLAIMS:
        raise EvaluatorSchemaError(f"Extractor returned more than {MAX_CLAIMS} claims.")

    parsed: list[ExtractedClaimPayload] = []
    for entry in claims:
        if not isinstance(entry, dict):
            raise EvaluatorSchemaError("Each claim must be a JSON object.")
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            raise EvaluatorSchemaError("Each claim needs non-empty text.")
        if len(text) > MAX_CLAIM_CHARS:
            raise EvaluatorSchemaError("Claim text exceeded the permitted length.")
        try:
            claim_type = ClaimType(str(entry.get("type", "other")))
            importance = ClaimImportance(str(entry.get("importance", "supporting")))
        except ValueError as exc:
            raise EvaluatorSchemaError("Claim carried an unknown type or importance.") from exc
        parsed.append(
            ExtractedClaimPayload(
                text=text.strip(), claim_type=claim_type, importance=importance
            )
        )
    return parsed


def parse_verification(raw: str) -> VerifierPayload:
    """Validate a verifier response.

    ``not_applicable`` is not offered to the verifier: it is a pipeline
    decision, not a judgement about evidence.
    """

    document = _loads(raw)
    if not isinstance(document, dict):
        raise EvaluatorSchemaError("Verifier response must be a JSON object.")
    try:
        verdict = ClaimVerdictValue(str(document.get("verdict")))
    except ValueError as exc:
        raise EvaluatorSchemaError("Verifier returned an unknown verdict.") from exc
    if verdict is ClaimVerdictValue.NOT_APPLICABLE:
        raise EvaluatorSchemaError("Verifier may not return not_applicable.")

    evidence_id = document.get("evidence_id")
    if evidence_id is not None and not isinstance(evidence_id, str):
        raise EvaluatorSchemaError("evidence_id must be a string or null.")

    explanation = document.get("explanation")
    if not isinstance(explanation, str):
        raise EvaluatorSchemaError("Verifier must supply an explanation.")

    raw_confidence = document.get("confidence")
    confidence: float | None = None
    if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
        confidence = max(0.0, min(1.0, float(raw_confidence)))

    return VerifierPayload(
        verdict=verdict,
        evidence_id=evidence_id,
        explanation=explanation[:1000],
        # Kept as evaluator metadata only. A model's self-reported certainty is
        # never an input to a displayed metric.
        confidence=confidence,
    )


# --------------------------------------------------------------------------- #
# Offline extractor
# --------------------------------------------------------------------------- #

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_FILLER = re.compile(
    r"^(hi|hello|hey|thanks|thank you|sure|of course|certainly|great question|"
    r"i can help|happy to help|let me know|is there anything)",
    re.IGNORECASE,
)
_FUTURE = re.compile(r"\b(will|going to|expects? to|should arrive|by next)\b", re.IGNORECASE)
_FACTUAL_HINT = re.compile(r"\d|\b(policy|return|refund|warranty|stock|price|ship)", re.IGNORECASE)


def _classify(sentence: str) -> ClaimType:
    lowered = sentence.lower()
    for pattern, claim_type in (
        ("return", ClaimType.POLICY),
        ("refund", ClaimType.POLICY),
        ("warrant", ClaimType.POLICY),
        ("ship", ClaimType.POLICY),
        ("stock", ClaimType.INVENTORY),
        ("availab", ClaimType.INVENTORY),
        ("$", ClaimType.PRICE),
        ("price", ClaimType.PRICE),
    ):
        if pattern in lowered:
            return claim_type
    if _FUTURE.search(sentence):
        return ClaimType.PREDICTION
    return ClaimType.OTHER


def extract_claims_offline(answer: str) -> list[ExtractedClaimPayload]:
    """Split a response into candidate claims without calling a provider.

    Sentence-level rather than truly atomic, so it is a weaker extractor than a
    model -- but it is deterministic, free, and lets the whole pipeline run with
    no credential configured.
    """

    claims: list[ExtractedClaimPayload] = []
    for raw in _SENTENCE.split(answer.strip()):
        sentence = raw.strip()
        if len(sentence) < 8 or _FILLER.match(sentence):
            continue
        if not _FACTUAL_HINT.search(sentence):
            continue
        claim_type = _classify(sentence)
        # The first *retained* factual sentence carries the answer. Counting raw
        # sentence position instead would demote it whenever the response opens
        # with a "Yes." that was dropped as filler.
        importance = ClaimImportance.CENTRAL if not claims else ClaimImportance.SUPPORTING
        claims.append(
            ExtractedClaimPayload(
                text=sentence[:MAX_CLAIM_CHARS], claim_type=claim_type, importance=importance
            )
        )
        if len(claims) >= MAX_CLAIMS:
            break
    return claims


# --------------------------------------------------------------------------- #
# HTTP providers
# --------------------------------------------------------------------------- #

RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3


def call_with_retry(provider: EvaluatorProvider, *, system: str, user: str) -> str:
    """Call a provider, retrying only failures that could plausibly succeed.

    A schema error is the provider doing the wrong thing, not a transient
    outage, so it is not retried.
    """

    delay = 0.5
    last: EvaluatorError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return provider.complete(system=system, user=user)
        except EvaluatorSchemaError:
            raise
        except EvaluatorError as exc:
            last = exc
            if attempt == MAX_ATTEMPTS - 1:
                break
            time.sleep(delay)
            delay *= 2
    raise last or EvaluatorError("Evaluator call failed.")
