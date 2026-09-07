"""Request-facing helpers: shape verification records into API responses.

Kept out of the route module so the aggregation rules -- particularly the
minimum evidence gate -- are testable without an HTTP client.
"""

from __future__ import annotations

from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ClaimVerdict,
    CorpusVersion,
    EvaluationRun,
    ExtractedClaim,
    VerificationChunk,
    VerificationSource,
)
from app.schemas import (
    ClaimEvidenceResponse,
    ClaimVerdictResponse,
    ClaimVerdictValue,
    CorpusVersionResponse,
    EvaluationRunStatus,
    EvaluationSummaryResponse,
    GroundednessBreakdown,
    QualityBreakdown,
    VerificationChunkResponse,
    VerificationSourceResponse,
)
from app.verification.metrics import (
    ClaimOutcome,
    GroundednessResult,
    QualityResult,
    score_groundedness,
)
from app.verification.pipeline import EvaluationResult

# A window smaller than this cannot support a health claim. Configurable, but
# never silently waived.
DEFAULT_MINIMUM_WINDOW = 20


def source_response(session: Session, source: VerificationSource) -> VerificationSourceResponse:
    versions = []
    for version in sorted(source.versions, key=lambda item: item.version):
        chunks = session.scalars(
            select(VerificationChunk).where(VerificationChunk.corpus_version_id == version.id)
        ).all()
        facts = sum(len((chunk.structured_facts or {}).get("facts", []) or []) for chunk in chunks)
        versions.append(
            CorpusVersionResponse(
                id=version.id,
                version=version.version,
                content_hash=version.content_hash,
                effective_from=version.effective_from,
                imported_at=version.imported_at,
                approved_at=version.approved_at,
                approved_by=version.approved_by,
                retired_at=version.retired_at,
                source_metadata=version.source_metadata or {},
                chunk_count=len(chunks),
                fact_count=facts,
            )
        )
    return VerificationSourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        status=source.status,
        description=source.description,
        original_filename=source.original_filename,
        source_url=source.source_url,
        created_at=source.created_at,
        created_by=source.created_by,
        versions=versions,
    )


def evidence_response(
    session: Session, source: VerificationSource, *, include_retired: bool
) -> list[VerificationChunkResponse]:
    query = (
        select(VerificationChunk)
        .join(CorpusVersion, VerificationChunk.corpus_version_id == CorpusVersion.id)
        .where(CorpusVersion.source_id == source.id)
        .order_by(CorpusVersion.version, VerificationChunk.sequence)
    )
    if not include_retired:
        query = query.where(CorpusVersion.retired_at.is_(None))
    return [
        VerificationChunkResponse(
            id=chunk.id,
            text=chunk.text,
            structured_facts=chunk.structured_facts or {},
            sequence=chunk.sequence,
            token_count=chunk.token_count,
        )
        for chunk in session.scalars(query).all()
    ]


def groundedness_breakdown(result: GroundednessResult) -> GroundednessBreakdown:
    return GroundednessBreakdown(
        groundedness=result.groundedness,
        confirmed_hallucination_rate=result.confirmed_hallucination_rate,
        evidence_coverage=result.evidence_coverage,
        supported_weight=result.supported_weight,
        contradicted_weight=result.contradicted_weight,
        insufficient_weight=result.insufficient_weight,
        total_factual_weight=result.total_factual_weight,
        central_contradiction=result.central_contradiction,
        capped=result.capped,
        formula=result.formula,
        verdict_counts=result.verdict_counts,
    )


def quality_breakdown(result: QualityResult) -> QualityBreakdown:
    return QualityBreakdown(
        quality=result.quality,
        correctness=result.correctness,
        correctness_confidence=result.correctness_confidence.value,
        correctness_capped=result.correctness_capped,
        components=result.components,
        missing_components=result.missing_components,
    )


def evaluation_claims(result: EvaluationResult) -> list[ClaimVerdictResponse]:
    return [
        ClaimVerdictResponse(
            text=claim.text,
            claim_type=claim.claim_type,
            importance=claim.importance,
            verdict=claim.verdict,
            method=claim.method,
            explanation=claim.explanation,
            evidence_chunk_id=claim.evidence_chunk_id,
            verifier_confidence=claim.confidence,
            evidence=[
                ClaimEvidenceResponse(
                    chunk_id=item.chunk_id,
                    text=item.text,
                    score=item.score,
                    source_name=item.source_name,
                    version=item.version,
                    exact_fact_match=item.exact_fact_match,
                )
                for item in claim.evidence
            ],
        )
        for claim in result.claims
    ]


def stored_evaluation_claims(session: Session, run: EvaluationRun) -> list[ClaimVerdictResponse]:
    """Rebuild the reasoning chain from storage, for a run fetched later."""

    claims = session.scalars(
        select(ExtractedClaim)
        .where(ExtractedClaim.evaluation_run_id == run.id)
        .order_by(ExtractedClaim.sequence)
    ).all()
    responses: list[ClaimVerdictResponse] = []
    for claim in claims:
        verdict = session.scalar(select(ClaimVerdict).where(ClaimVerdict.claim_id == claim.id))
        if verdict is None:
            continue
        evidence: list[ClaimEvidenceResponse] = []
        if verdict.evidence_chunk_id:
            chunk = session.get(VerificationChunk, verdict.evidence_chunk_id)
            if chunk is not None:
                version = session.get(CorpusVersion, chunk.corpus_version_id)
                source = (
                    session.get(VerificationSource, version.source_id) if version else None
                )
                evidence.append(
                    ClaimEvidenceResponse(
                        chunk_id=chunk.id,
                        text=chunk.text,
                        score=1.0,
                        source_name=source.name if source else "unknown",
                        version=version.version if version else 0,
                        exact_fact_match=verdict.deterministic_match,
                    )
                )
        responses.append(
            ClaimVerdictResponse(
                text=claim.text,
                claim_type=claim.claim_type.value,
                importance=claim.importance.value,
                verdict=verdict.verdict,
                method=verdict.method,
                explanation=verdict.explanation or "",
                evidence_chunk_id=verdict.evidence_chunk_id,
                verifier_confidence=verdict.verifier_confidence,
                evidence=evidence,
            )
        )
    return responses


def _percentile10(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, round(0.10 * (len(ordered) - 1)))
    return round(ordered[index], 1)


def evaluation_summary(
    session: Session,
    *,
    model_id: str,
    minimum_window: int = DEFAULT_MINIMUM_WINDOW,
    limit: int = 200,
) -> EvaluationSummaryResponse:
    """Aggregate recent runs without ever inventing a score.

    Below ``minimum_window`` completed evaluations the distribution figures are
    still reported, but ``meets_minimum`` is false -- the caller must not turn
    this into a health state.
    """

    runs = session.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.model_id == model_id)
        .order_by(EvaluationRun.created_at.desc())
        .limit(limit)
    ).all()

    completed = [run for run in runs if run.status is EvaluationRunStatus.COMPLETED]
    failed = [run for run in runs if run.status is EvaluationRunStatus.FAILED]

    groundedness_values: list[float] = []
    coverage_values: list[float] = []
    counts = dict.fromkeys(
        (
            ClaimVerdictValue.SUPPORTED.value,
            ClaimVerdictValue.CONTRADICTED.value,
            ClaimVerdictValue.INSUFFICIENT_EVIDENCE.value,
            ClaimVerdictValue.NOT_VERIFIABLE.value,
        ),
        0,
    )

    for run in completed:
        outcomes: list[ClaimOutcome] = []
        for claim in session.scalars(
            select(ExtractedClaim).where(ExtractedClaim.evaluation_run_id == run.id)
        ).all():
            verdict = session.scalar(
                select(ClaimVerdict).where(ClaimVerdict.claim_id == claim.id)
            )
            if verdict is None:
                continue
            if verdict.verdict.value in counts:
                counts[verdict.verdict.value] += 1
            outcomes.append(
                ClaimOutcome(importance=claim.importance, verdict=verdict.verdict)
            )
        scored = score_groundedness(outcomes)
        if scored.groundedness is not None:
            groundedness_values.append(scored.groundedness)
        if scored.evidence_coverage is not None:
            coverage_values.append(scored.evidence_coverage)

    total = len(runs)
    return EvaluationSummaryResponse(
        model_id=model_id,
        evaluated_interactions=len(completed),
        minimum_window=minimum_window,
        meets_minimum=len(completed) >= minimum_window,
        groundedness_mean=(
            round(sum(groundedness_values) / len(groundedness_values), 1)
            if groundedness_values
            else None
        ),
        groundedness_median=(
            round(median(groundedness_values), 1) if groundedness_values else None
        ),
        groundedness_p10=_percentile10(groundedness_values),
        evidence_coverage_mean=(
            round(sum(coverage_values) / len(coverage_values), 1) if coverage_values else None
        ),
        evaluator_error_rate=round(100.0 * len(failed) / total, 1) if total else 0.0,
        supported_claims=counts[ClaimVerdictValue.SUPPORTED.value],
        contradicted_claims=counts[ClaimVerdictValue.CONTRADICTED.value],
        insufficient_claims=counts[ClaimVerdictValue.INSUFFICIENT_EVIDENCE.value],
        not_verifiable_claims=counts[ClaimVerdictValue.NOT_VERIFIABLE.value],
    )
