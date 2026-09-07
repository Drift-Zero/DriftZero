"""Comparable claims must be settled by arithmetic, not by asking a model."""

from __future__ import annotations

from app.schemas import ClaimVerdictValue, VerificationMethod
from app.verification.deterministic import compare_claim, extract_quantities

RETURNS = (
    "chunk-returns",
    {
        "facts": [
            {
                "key": "electronics_return_window_days",
                "label": "Electronics return window",
                "value": 14,
                "unit": "days",
                "terms": ["return", "electronics"],
            }
        ]
    },
)

SHIPPING = (
    "chunk-shipping",
    {
        "facts": [
            {
                "key": "standard_shipping_days",
                "label": "Standard shipping time",
                "value": 30,
                "unit": "days",
                "terms": ["shipping"],
            }
        ]
    },
)

INVENTORY = (
    "chunk-inventory",
    {
        "facts": [
            {
                "key": "arc_mini_speaker_available",
                "label": "Arc Mini Speaker availability",
                "value": False,
                "terms": ["arc", "mini", "speaker"],
            }
        ]
    },
)

PRICE = (
    "chunk-price",
    {
        "facts": [
            {
                "key": "pulse_smartwatch_price",
                "label": "Pulse Smartwatch price",
                "value": 229,
                "unit": "currency",
                "terms": ["pulse", "smartwatch", "price"],
            }
        ]
    },
)


def test_the_shopassist_stale_policy_claim_is_contradicted() -> None:
    """The scenario the demo turns on, decided without any model call."""

    outcome = compare_claim(
        "Electronics returns are accepted within 30 days.", [RETURNS]
    )

    assert outcome is not None
    assert outcome.verdict is ClaimVerdictValue.CONTRADICTED
    assert outcome.method is VerificationMethod.DETERMINISTIC
    assert outcome.evidence_chunk_id == "chunk-returns"
    assert "14 days" in outcome.explanation
    assert "30 days" in outcome.explanation


def test_the_recovered_answer_is_supported() -> None:
    outcome = compare_claim(
        "Electronics returns are accepted within 14 days.", [RETURNS]
    )

    assert outcome is not None
    assert outcome.verdict is ClaimVerdictValue.SUPPORTED


def test_equivalent_units_compare_equal() -> None:
    """"2 weeks" and "14 days" are the same promise."""

    outcome = compare_claim("Electronics returns are accepted within 2 weeks.", [RETURNS])

    assert outcome is not None
    assert outcome.verdict is ClaimVerdictValue.SUPPORTED


def test_an_unrelated_fact_is_not_compared() -> None:
    """A shipping figure must never settle a returns claim."""

    outcome = compare_claim(
        "Electronics returns are accepted within 30 days.", [SHIPPING]
    )

    assert outcome is None


def test_the_right_fact_is_chosen_when_both_are_retrieved() -> None:
    outcome = compare_claim(
        "Electronics returns are accepted within 30 days.", [SHIPPING, RETURNS]
    )

    assert outcome is not None
    assert outcome.evidence_chunk_id == "chunk-returns"
    assert outcome.verdict is ClaimVerdictValue.CONTRADICTED


def test_an_unsettleable_claim_returns_none_rather_than_guessing() -> None:
    """No comparable fact means fall through to the verifier, not invent a verdict."""

    assert compare_claim("Our support team is very helpful.", [RETURNS]) is None


def test_boolean_availability_is_contradicted() -> None:
    outcome = compare_claim("The Arc Mini Speaker is in stock.", [INVENTORY])

    assert outcome is not None
    assert outcome.verdict is ClaimVerdictValue.CONTRADICTED


def test_boolean_availability_is_supported() -> None:
    outcome = compare_claim("The Arc Mini Speaker is sold out.", [INVENTORY])

    assert outcome is not None
    assert outcome.verdict is ClaimVerdictValue.SUPPORTED


def test_prices_are_compared() -> None:
    wrong = compare_claim("The Pulse Smartwatch price is $199.", [PRICE])
    right = compare_claim("The Pulse Smartwatch price is $229.", [PRICE])

    assert wrong is not None and wrong.verdict is ClaimVerdictValue.CONTRADICTED
    assert right is not None and right.verdict is ClaimVerdictValue.SUPPORTED


def test_quantities_are_extracted_with_units() -> None:
    quantities = extract_quantities("Returns within 30 days, shipping costs $12.50, 15% off.")
    families = sorted({quantity.family for quantity in quantities})

    assert "duration" in families
    assert "currency" in families
    assert "percent" in families


def test_a_fact_with_no_terms_is_ignored() -> None:
    """An unscoped fact could match anything, so it matches nothing."""

    loose = ("chunk-loose", {"facts": [{"key": "x", "value": 5, "unit": "days", "terms": []}]})

    assert compare_claim("Returns within 30 days.", [loose]) is None


def test_malformed_structured_facts_are_survived() -> None:
    for broken in ({}, {"facts": None}, {"facts": ["not-a-dict"]}, {"facts": [{}]}):
        assert compare_claim("Returns within 30 days.", [("chunk", broken)]) is None
