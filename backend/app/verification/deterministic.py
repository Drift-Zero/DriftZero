"""Settle checkable claims by comparison, before any model is consulted.

A claim like "returned within 30 days" against an approved fact of 14 days is
arithmetic, not interpretation. Deciding it here means the verdict is
reproducible, costs nothing, and cannot be argued with -- and it keeps the LLM
verifier for the genuinely linguistic cases it is actually needed for.

Structured facts are supplied by the importer in this shape::

    {"facts": [
        {"key": "return_window_days", "value": 14, "unit": "days",
         "terms": ["return", "electronics"], "label": "Electronics return window"}
    ]}

A fact is only considered when every one of its ``terms`` appears in the claim,
so a shipping figure is never compared against a returns claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas import ClaimVerdictValue, VerificationMethod
from app.verification.text import WORD as _WORD_SHARED
from app.verification.text import stems as _stems

_WORD = _WORD_SHARED

# Durations are normalized to days so "2 weeks" and "14 days" compare equal.
_DURATION_DAYS: dict[str, float] = {
    "day": 1.0,
    "days": 1.0,
    "week": 7.0,
    "weeks": 7.0,
    "month": 30.0,
    "months": 30.0,
    "year": 365.0,
    "years": 365.0,
    "hour": 1.0 / 24.0,
    "hours": 1.0 / 24.0,
}

_UNIT_FAMILIES: dict[str, str] = {
    **{name: "duration" for name in _DURATION_DAYS},
    "%": "percent",
    "percent": "percent",
    "usd": "currency",
    "$": "currency",
}

# "in stock" style claims resolve to a boolean rather than a quantity.
_TRUE_TERMS = ("in stock", "available", "in-stock")
_FALSE_TERMS = ("sold out", "out of stock", "unavailable", "no longer available")

_NUMBER = re.compile(
    r"(?P<currency>[$£€])?\s*(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>%|[a-z]+)?",
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(r"\b([A-Z]{2,}-\d{3,})\b")


@dataclass(frozen=True, slots=True)
class Quantity:
    value: float
    unit: str | None
    family: str

    def comparable_with(self, other: Quantity) -> bool:
        return self.family == other.family

    def normalized(self) -> float:
        if self.family == "duration" and self.unit:
            return self.value * _DURATION_DAYS.get(self.unit, 1.0)
        return self.value


@dataclass(frozen=True, slots=True)
class DeterministicOutcome:
    """A verdict reached without a model, plus the fact that settled it."""

    verdict: ClaimVerdictValue
    evidence_chunk_id: str | None
    explanation: str
    matched_fact: str | None
    method: VerificationMethod = VerificationMethod.DETERMINISTIC


def _quantity_from(value: str, unit: str | None, currency: str | None) -> Quantity | None:
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    key = (unit or "").lower()
    if currency:
        return Quantity(number, "currency", "currency")
    family = _UNIT_FAMILIES.get(key)
    if family is None:
        # A bare number still compares against a bare fact.
        return Quantity(number, key or None, "number")
    return Quantity(number, key, family)


def extract_quantities(text: str) -> list[Quantity]:
    """Pull every comparable number out of a claim."""

    found: list[Quantity] = []
    for match in _NUMBER.finditer(text):
        quantity = _quantity_from(
            match.group("value"), match.group("unit"), match.group("currency")
        )
        if quantity is not None:
            found.append(quantity)
    return found


def extract_identifiers(text: str) -> list[str]:
    return _IDENTIFIER.findall(text.upper())


def _fact_quantity(fact: dict[str, Any]) -> Quantity | None:
    raw = fact.get("value")
    if isinstance(raw, bool) or raw is None:
        return None
    if not isinstance(raw, (int, float)):
        return None
    unit = str(fact.get("unit") or "").lower()
    family = _UNIT_FAMILIES.get(unit, "number" if not unit else "number")
    if unit == "currency":
        family = "currency"
    return Quantity(float(raw), unit or None, family)


def _fact_applies(fact: dict[str, Any], claim_words: set[str]) -> bool:
    """A fact is only relevant when the claim mentions everything it is about.

    Without this, a 14-day returns window would be compared against a claim
    about 30-day shipping simply because both contain a number.
    """

    terms = fact.get("terms") or []
    if not isinstance(terms, list) or not terms:
        return False
    return all(_stems(str(term)) <= claim_words for term in terms)


def _boolean_in(text: str) -> bool | None:
    lowered = text.lower()
    if any(term in lowered for term in _FALSE_TERMS):
        return False
    if any(term in lowered for term in _TRUE_TERMS):
        return True
    return None


def compare_claim(
    claim_text: str,
    evidence: list[tuple[str, dict[str, Any]]],
) -> DeterministicOutcome | None:
    """Try to settle a claim against structured facts.

    ``evidence`` is ``(chunk_id, structured_facts)`` for each retrieved chunk.
    Returns ``None`` when nothing comparable lines up, which is the signal to
    fall through to the LLM verifier rather than to guess.
    """

    claim_words = _stems(claim_text)
    claim_quantities = extract_quantities(claim_text)
    claim_identifiers = set(extract_identifiers(claim_text))
    claim_boolean = _boolean_in(claim_text)

    for chunk_id, structured in evidence:
        facts = structured.get("facts") if isinstance(structured, dict) else None
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if not isinstance(fact, dict) or not _fact_applies(fact, claim_words):
                continue
            label = str(fact.get("label") or fact.get("key") or "fact")
            outcome = _compare_one(
                fact,
                label,
                chunk_id,
                claim_quantities=claim_quantities,
                claim_identifiers=claim_identifiers,
                claim_boolean=claim_boolean,
            )
            if outcome is not None:
                return outcome
    return None


def _compare_one(
    fact: dict[str, Any],
    label: str,
    chunk_id: str,
    *,
    claim_quantities: list[Quantity],
    claim_identifiers: set[str],
    claim_boolean: bool | None,
) -> DeterministicOutcome | None:
    raw = fact.get("value")

    if isinstance(raw, bool):
        if claim_boolean is None:
            return None
        agrees = claim_boolean is raw
        return DeterministicOutcome(
            verdict=(
                ClaimVerdictValue.SUPPORTED if agrees else ClaimVerdictValue.CONTRADICTED
            ),
            evidence_chunk_id=chunk_id,
            explanation=(
                f"{label} is {'available' if raw else 'not available'} in the approved source;"
                f" the claim states {'available' if claim_boolean else 'not available'}."
            ),
            matched_fact=label,
        )

    if isinstance(raw, str):
        # Exact enumerated policy values and identifiers.
        expected = raw.strip().upper()
        if expected in claim_identifiers:
            return DeterministicOutcome(
                verdict=ClaimVerdictValue.SUPPORTED,
                evidence_chunk_id=chunk_id,
                explanation=f"{label} matches the approved value {raw}.",
                matched_fact=label,
            )
        if claim_identifiers:
            return DeterministicOutcome(
                verdict=ClaimVerdictValue.CONTRADICTED,
                evidence_chunk_id=chunk_id,
                explanation=(
                    f"{label} is {raw} in the approved source, but the claim cites "
                    f"{', '.join(sorted(claim_identifiers))}."
                ),
                matched_fact=label,
            )
        return None

    fact_quantity = _fact_quantity(fact)
    if fact_quantity is None:
        return None
    for quantity in claim_quantities:
        if not quantity.comparable_with(fact_quantity):
            continue
        claimed = quantity.normalized()
        approved = fact_quantity.normalized()
        if abs(claimed - approved) < 1e-9:
            return DeterministicOutcome(
                verdict=ClaimVerdictValue.SUPPORTED,
                evidence_chunk_id=chunk_id,
                explanation=(
                    f"{label} is {_render(fact_quantity)} in the approved source, "
                    f"matching the claim."
                ),
                matched_fact=label,
            )
        return DeterministicOutcome(
            verdict=ClaimVerdictValue.CONTRADICTED,
            evidence_chunk_id=chunk_id,
            explanation=(
                f"{label} is {_render(fact_quantity)} in the approved source, "
                f"but the claim states {_render(quantity)}."
            ),
            matched_fact=label,
        )
    return None


def _render(quantity: Quantity) -> str:
    value = quantity.value
    rendered = f"{value:.0f}" if float(value).is_integer() else f"{value}"
    if quantity.family == "currency":
        return f"{rendered}"
    if quantity.unit and quantity.unit != "currency":
        return f"{rendered} {quantity.unit}"
    return rendered
