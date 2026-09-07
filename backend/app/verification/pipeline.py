"""Run one response through verification and persist the reasoning chain.

The order is deliberate. Deterministic comparison runs first, so anything
settleable by arithmetic never reaches a model; the verifier is consulted only
for genuinely linguistic claims; and metrics are computed last, in Python, from
the stored verdicts. Every intermediate step is written to the database, which
is what lets the dashboard answer "why is groundedness 63?" with the actual
claims and passages rather than a restatement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import ClaimVerdict, EvaluationRun, ExtractedClaim
from app.schemas import (
    ClaimVerdictValue,
    EvaluationRunStatus,
    VerificationMethod,
)
from app.verification.deterministic import compare_claim
from app.verification.metrics import (
    ClaimOutcome,
    GroundednessResult,
    QualityResult,
    RubricScores,
    score_groundedness,
    score_quality,
)
from app.verification.providers import (
    EXTRACTOR_VERSION,
    VERIFICATION_SYSTEM_PROMPT,
    VERIFIER_VERSION,
    EvaluatorError,
    EvaluatorProvider,
    ExtractedClaimPayload,
    call_with_retry,
    extract_claims_offline,
    parse_verification,
)
from app.verification.retrieval import DEFAULT_EVIDENCE_LIMIT, RetrievedEvidence, retrieve_evidence


@dataclass(frozen=True, slots=True)
class ClaimEvaluation:
    """One claim with everything needed to explain its verdict."""

    text: str
    claim_type: str
    importance: str
    verdict: ClaimVerdictValue
    method: VerificationMethod
    explanation: str
    evidence: list[RetrievedEvidence]
    evidence_chunk_id: str | None
    confidence: float | None


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    run_id: str
    claims: list[ClaimEvaluation]
    groundedness: GroundednessResult
    quality: QualityResult
    evaluator_provider: str | None
    evaluator_model: str | None
    corpus_versions: list[str]


def _verify_with_provider(
    provider: EvaluatorProvider,
    *,
    question: str,
    answer: str,
    claim: ExtractedClaimPayload,
    evidence: list[RetrievedEvidence],
) -> tuple[ClaimVerdictValue, str, str | None, float | None]:
    """Ask the verifier about one claim, constrained to the retrieved passages."""

    payload = {
        "question": question,
        "answer": answer,
        "claim": claim.text,
        "evidence": [
            {
                "evidence_id": item.chunk_id,
                "source": item.source_name,
                "version": item.version,
                "text": item.text,
            }
            for item in evidence
        ],
    }
    raw = call_with_retry(
        provider, system=VERIFICATION_SYSTEM_PROMPT, user=json.dumps(payload, ensure_ascii=False)
    )
    verdict = parse_verification(raw)
    allowed = {item.chunk_id for item in evidence}
    # A verifier citing a passage it was not given is not evidence.
    evidence_id = verdict.evidence_id if verdict.evidence_id in allowed else None
    return verdict.verdict, verdict.explanation, evidence_id, verdict.confidence


def evaluate_response(
    session: Session,
    *,
    tenant_id: str,
    model_id: str,
    question: str,
    answer: str,
    trace_id: str | None = None,
    provider: EvaluatorProvider | None = None,
    rubric: RubricScores | None = None,
    evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
) -> EvaluationResult:
    """Verify one response end to end and record the run.

    ``provider`` is optional: without one, claims are extracted by rule and only
    deterministically-settleable claims get a verdict. Everything else is
    ``insufficient_evidence``, which is honest -- we could not check it.
    """

    run = EvaluationRun(
        model_id=model_id,
        trace_id=trace_id,
        evaluator_provider=getattr(provider, "name", None),
        evaluator_model=getattr(provider, "model", None),
        extractor_version=EXTRACTOR_VERSION,
        verifier_version=VERIFIER_VERSION,
        status=EvaluationRunStatus.RUNNING,
    )
    run.tenant_id = tenant_id
    session.add(run)
    session.flush()

    try:
        claims = extract_claims_offline(answer)
        evaluations: list[ClaimEvaluation] = []
        corpus_versions: set[str] = set()

        for sequence, claim in enumerate(claims):
            evidence = retrieve_evidence(
                session, tenant_id=tenant_id, claim_text=claim.text, limit=evidence_limit
            )
            corpus_versions.update(item.corpus_version_id for item in evidence)

            verdict, explanation, chunk_id, confidence, method = _decide(
                provider=provider,
                question=question,
                answer=answer,
                claim=claim,
                evidence=evidence,
            )

            record = ExtractedClaim(
                evaluation_run_id=run.id,
                text=claim.text,
                claim_type=claim.claim_type,
                importance=claim.importance,
                sequence=sequence,
            )
            session.add(record)
            session.flush()
            session.add(
                ClaimVerdict(
                    claim_id=record.id,
                    verdict=verdict,
                    evidence_chunk_id=chunk_id,
                    explanation=explanation,
                    verifier_confidence=confidence,
                    deterministic_match=method is VerificationMethod.DETERMINISTIC,
                    method=method,
                )
            )
            evaluations.append(
                ClaimEvaluation(
                    text=claim.text,
                    claim_type=claim.claim_type.value,
                    importance=claim.importance.value,
                    verdict=verdict,
                    method=method,
                    explanation=explanation,
                    evidence=evidence,
                    evidence_chunk_id=chunk_id,
                    confidence=confidence,
                )
            )

        groundedness = score_groundedness(
            [
                ClaimOutcome(importance=claim.importance, verdict=item.verdict)
                for claim, item in zip(claims, evaluations, strict=True)
            ]
        )
        quality = score_quality(rubric or RubricScores(), groundedness)

        run.status = EvaluationRunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.corpus_versions = sorted(corpus_versions)
        session.flush()

        return EvaluationResult(
            run_id=run.id,
            claims=evaluations,
            groundedness=groundedness,
            quality=quality,
            evaluator_provider=run.evaluator_provider,
            evaluator_model=run.evaluator_model,
            corpus_versions=sorted(corpus_versions),
        )
    except Exception as exc:
        # A failed evaluation is recorded as failed. It never reuses an old
        # score and never invents one.
        run.status = EvaluationRunStatus.FAILED
        run.completed_at = datetime.now(UTC)
        run.error = f"{type(exc).__name__}: {exc}"[:500]
        session.flush()
        raise


def _decide(
    *,
    provider: EvaluatorProvider | None,
    question: str,
    answer: str,
    claim: ExtractedClaimPayload,
    evidence: list[RetrievedEvidence],
) -> tuple[ClaimVerdictValue, str, str | None, float | None, VerificationMethod]:
    """Settle one claim: arithmetic first, model second, honesty last."""

    if not evidence:
        return (
            ClaimVerdictValue.INSUFFICIENT_EVIDENCE,
            "No approved evidence covers this claim.",
            None,
            None,
            VerificationMethod.NO_EVIDENCE,
        )

    deterministic = compare_claim(claim.text, [item.as_pair() for item in evidence])
    if deterministic is not None:
        return (
            deterministic.verdict,
            deterministic.explanation,
            deterministic.evidence_chunk_id,
            None,
            VerificationMethod.DETERMINISTIC,
        )

    if provider is None:
        return (
            ClaimVerdictValue.INSUFFICIENT_EVIDENCE,
            "No evaluator is configured, so this claim could not be checked against the "
            "retrieved evidence.",
            None,
            None,
            VerificationMethod.NO_EVIDENCE,
        )

    try:
        verdict, explanation, chunk_id, confidence = _verify_with_provider(
            provider, question=question, answer=answer, claim=claim, evidence=evidence
        )
    except EvaluatorError as exc:
        return (
            ClaimVerdictValue.INSUFFICIENT_EVIDENCE,
            f"The evaluator could not verify this claim ({type(exc).__name__}).",
            None,
            None,
            VerificationMethod.NO_EVIDENCE,
        )
    return verdict, explanation, chunk_id, confidence, VerificationMethod.LLM_VERIFIER
