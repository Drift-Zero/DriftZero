"""Find the approved evidence a claim should be judged against.

Two rules make this trustworthy rather than merely useful:

* **Only approved, unretired, same-tenant corpus versions are searched.** A
  superseded policy stays readable as history but can never be cited as current
  truth, and one tenant's corpus can never answer another's claim.
* **Nothing is fetched at verification time.** Retrieval reads the imported
  corpus only. A verifier that could reach the open web would be checking a
  claim against something nobody approved.

Ranking is lexical and computed in Python rather than in the database, so the
behaviour is identical on SQLite and PostgreSQL and needs no search extension.
That is a deliberate trade for a bounded corpus; a large one would want a real
index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CorpusVersion, VerificationChunk, VerificationSource
from app.schemas import VerificationSourceStatus
from app.verification.text import stems

DEFAULT_EVIDENCE_LIMIT = 3

# A chunk carrying a structured fact the claim actually names is worth more
# than one that merely shares vocabulary, because it can settle the claim
# deterministically.
_EXACT_FACT_BONUS = 1.0


@dataclass(frozen=True, slots=True)
class RetrievedEvidence:
    """One candidate passage, with the provenance an operator needs to judge it."""

    chunk_id: str
    text: str
    structured_facts: dict[str, Any]
    score: float
    exact_fact_match: bool
    corpus_version_id: str
    version: int
    source_id: str
    source_name: str
    retired: bool

    def as_pair(self) -> tuple[str, dict[str, Any]]:
        """The shape the deterministic comparator consumes."""

        return self.chunk_id, self.structured_facts


def _fact_terms(structured: dict[str, Any]) -> list[set[str]]:
    facts = structured.get("facts") if isinstance(structured, dict) else None
    if not isinstance(facts, list):
        return []
    groups: list[set[str]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        terms = fact.get("terms")
        if isinstance(terms, list) and terms:
            groups.append({s for term in terms for s in stems(str(term))})
    return groups


def score_chunk(claim_stems: set[str], text: str, structured: dict[str, Any]) -> tuple[float, bool]:
    """Rank one chunk against a claim.

    Returns the score and whether a structured fact fully matched, which the
    caller uses to prefer deterministically-settleable evidence.
    """

    chunk_stems = stems(text, drop_stopwords=True)
    if not claim_stems:
        return 0.0, False
    overlap = len(claim_stems & chunk_stems)
    lexical = overlap / len(claim_stems)

    exact = any(terms and terms <= claim_stems for terms in _fact_terms(structured))
    return round(lexical + (_EXACT_FACT_BONUS if exact else 0.0), 4), exact


def retrieve_evidence(
    session: Session,
    *,
    tenant_id: str,
    claim_text: str,
    limit: int = DEFAULT_EVIDENCE_LIMIT,
    include_retired: bool = False,
) -> list[RetrievedEvidence]:
    """Return at most ``limit`` approved passages relevant to the claim.

    ``include_retired`` exists only for an operator explicitly asking for a
    historical comparison -- "what did the old policy say?" -- and is never set
    by the verification path.
    """

    query = (
        select(VerificationChunk, CorpusVersion, VerificationSource)
        .join(CorpusVersion, VerificationChunk.corpus_version_id == CorpusVersion.id)
        .join(VerificationSource, CorpusVersion.source_id == VerificationSource.id)
        .where(
            VerificationSource.tenant_id == tenant_id,
            VerificationSource.status == VerificationSourceStatus.APPROVED,
            CorpusVersion.approved_at.is_not(None),
        )
    )
    if not include_retired:
        query = query.where(CorpusVersion.retired_at.is_(None))

    claim_stems = stems(claim_text, drop_stopwords=True)
    candidates: list[RetrievedEvidence] = []
    for chunk, version, source in session.execute(query).all():
        structured = chunk.structured_facts or {}
        score, exact = score_chunk(claim_stems, chunk.text, structured)
        if score <= 0:
            continue
        candidates.append(
            RetrievedEvidence(
                chunk_id=chunk.id,
                text=chunk.text,
                structured_facts=structured,
                score=score,
                exact_fact_match=exact,
                corpus_version_id=version.id,
                version=version.version,
                source_id=source.id,
                source_name=source.name,
                retired=version.retired_at is not None,
            )
        )

    # Exact structured matches first, then lexical score, then a stable
    # tie-break so the same claim always cites the same passage.
    candidates.sort(key=lambda item: (not item.exact_fact_match, -item.score, item.chunk_id))
    return candidates[: max(0, limit)]
