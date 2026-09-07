"""Deterministic claim decisions stay conservative and evidence-linked."""

from app.claim_verification import split_claims, verify_claim
from app.schemas import EvidenceSearchHit


def hit(quote: str, *, relevance: float = 0.9) -> EvidenceSearchHit:
    return EvidenceSearchHit(
        chunk_id="chunk-1",
        source_id="source-1",
        source_name="Policies",
        filename="policies.json",
        corpus_version="evidence-v1",
        text=quote,
        evidence_quote=quote,
        locator={"json_path": "$.returns"},
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
