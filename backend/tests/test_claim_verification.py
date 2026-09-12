"""Deterministic claim decisions stay conservative and evidence-linked."""

from app.claim_verification import split_claims, verify_claim
from app.schemas import EvidenceSearchHit


def hit(
    quote: str,
    *,
    relevance: float = 0.9,
    validation_status: str = "deterministic",
) -> EvidenceSearchHit:
    return EvidenceSearchHit(
        chunk_id="chunk-1",
        source_id="source-1",
        source_name="Policies",
        filename="policies.json",
        corpus_version="evidence-v1",
        text=quote,
        evidence_quote=quote,
        locator={"json_path": "$.returns"},
        validation_status=validation_status,
        relevance=relevance,
    )


def test_supported_claim_keeps_evidence_provenance() -> None:
    result = verify_claim(
        "Electronics can be returned within 14 days.",
        [hit("Electronics can be returned within 14 days.")],
    )

    assert result.verdict == "supported"
    assert result.evidence is not None
    assert result.evidence.locator == {"json_path": "$.returns"}


def test_numeric_conflict_is_contradicted() -> None:
    result = verify_claim(
        "Electronics can be returned within 30 days.",
        [hit("Electronics can be returned within 14 days.")],
    )

    assert result.verdict == "contradicted"
    assert "numeric" in result.reason


def test_numeric_match_uses_relevant_entity_context() -> None:
    result = verify_claim(
        "The Nimbus Adapter costs $119.",
        [hit("The Nimbus Adapter costs $119, while the Cirrus Hub costs $149.")],
    )

    assert result.verdict == "supported"


def test_wrong_number_for_same_entity_remains_contradicted() -> None:
    result = verify_claim(
        "The Nimbus Adapter costs $149.",
        [hit("The Nimbus Adapter costs $119, while the Cirrus Hub costs $149.")],
    )

    assert result.verdict == "contradicted"
    assert "numeric" in result.reason


def test_inventory_synonyms_are_supported() -> None:
    result = verify_claim(
        "There are 18 Nimbus Headphones in stock.",
        [hit("Nimbus Headphones $ 149 · 18 available", validation_status="exact_match")],
    )

    assert result.verdict == "supported"


def test_sold_out_item_is_supported() -> None:
    result = verify_claim(
        "The Cirrus Speaker is currently out of stock.",
        [hit("Cirrus Speaker $ 79 · Sold out", validation_status="exact_match")],
    )

    assert result.verdict == "supported"


def test_product_name_number_is_not_a_false_numeric_contradiction() -> None:
    result = verify_claim(
        "We sell a Nimbus 3-in-1 Charger and a Cirrus Speaker.",
        [hit("Catalog: Nimbus 3-in-1 Charger, Cirrus Speaker, and Harbor Lamp.")],
    )

    assert result.verdict != "contradicted"


def test_weak_or_missing_evidence_stays_unverified() -> None:
    result = verify_claim("The moon is made of cheese.", [])

    assert result.verdict == "unverified"
    assert result.confidence == 0


def test_reversed_relationship_is_not_supported_by_bag_of_words() -> None:
    result = verify_claim(
        "Alice defeated Bob in the final.",
        [hit("Bob defeated Alice in the final.")],
    )

    assert result.verdict == "unverified"


def test_claim_splitter_is_bounded() -> None:
    claims = split_claims(". ".join(f"Claim number {index}" for index in range(30)))

    assert len(claims) == 20
