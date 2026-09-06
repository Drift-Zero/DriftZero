"""Model versions and the two signature stability evaluations."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import (
    EvaluatorVersion,
    ModelVersion,
    MonitoredModel,
    StabilityClaim,
    StabilityVariant,
)
from app.evaluation import CURRENT_CORPUS_VERSION
from app.schemas import (
    ModelVersionCreate,
    StabilityKind,
    StabilityRunRequest,
    StabilityVerdict,
)
from app.service import DriftZeroService

QUESTION = StabilityRunRequest(question="When is the examination fee deadline?", variants=4)
SUPERSEDED_CORPUS = "2026-01-14"


def _service() -> DriftZeroService:
    return DriftZeroService(Settings())


def _version(corpus: str | None, label: str = "v1") -> ModelVersionCreate:
    return ModelVersionCreate(
        label=label,
        model_identifier="campus-gpt",
        prompt_version="v1",
        corpus_version=corpus,
    )


class TestFingerprint:
    def test_identical_inputs_produce_one_fingerprint(self) -> None:
        inputs = {"model_identifier": "m", "prompt_version": "v1", "corpus_version": "c"}

        assert ModelVersion.fingerprint_for(**inputs) == ModelVersion.fingerprint_for(**inputs)

    def test_a_changed_controlled_input_changes_the_fingerprint(self) -> None:
        base = {"model_identifier": "m", "prompt_version": "v1", "corpus_version": "c1"}
        moved = {**base, "corpus_version": "c2"}

        assert ModelVersion.fingerprint_for(**base) != ModelVersion.fingerprint_for(**moved)

    def test_uncontrolled_fields_are_ignored(self) -> None:
        """Widening the fingerprint would make every run incomparable."""

        base = {"model_identifier": "m", "prompt_version": "v1"}

        assert ModelVersion.fingerprint_for(**base) == ModelVersion.fingerprint_for(
            **base, label="a different label"
        )


class TestVersionRegistration:
    def test_registering_retires_the_previous_version(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        first = service.register_model_version(session, model.id, _version("c1"))
        service.register_model_version(session, model.id, _version("c2", label="v2"))

        retired = session.get(ModelVersion, first.id)
        assert retired.active_to is not None
        assert service._active_model_version(session, model.id).corpus_version == "c2"

    def test_re_registering_identical_inputs_does_not_duplicate(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """A service that re-declares its config on boot must not fragment history."""

        service = _service()
        first = service.register_model_version(session, model.id, _version("c1"))
        again = service.register_model_version(session, model.id, _version("c1"))

        assert first.id == again.id
        assert session.scalar(sa.select(sa.func.count()).select_from(ModelVersion)) == 1


class TestSemanticStability:
    def test_a_current_corpus_answers_consistently(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))

        result = service.run_semantic_stability(session, model.id, QUESTION)

        assert result.stability_score == 100.0
        assert result.verdict is StabilityVerdict.STABLE
        assert len(result.variants) == 4

    def test_a_superseded_corpus_makes_stability_critical(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """Paraphrases disagree when some retrievals surface the stale document."""

        service = _service()
        service.register_model_version(session, model.id, _version(SUPERSEDED_CORPUS))

        result = service.run_semantic_stability(session, model.id, QUESTION)

        assert result.stability_score is not None
        assert result.stability_score < 70.0
        assert result.verdict is StabilityVerdict.CRITICAL

    def test_disagreements_are_recorded_against_the_claim(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(SUPERSEDED_CORPUS))

        service.run_semantic_stability(session, model.id, QUESTION)

        claims = session.scalars(sa.select(StabilityClaim)).all()
        disagreeing = [claim for claim in claims if claim.agrees_with_baseline is False]
        assert disagreeing
        # Agreement is judged on the extracted fact, not the wording.
        assert all(claim.claim_key == "exam_fee_deadline" for claim in claims)
        assert all(claim.disagreement_note for claim in disagreeing)

    def test_variants_are_persisted_with_a_baseline(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))

        service.run_semantic_stability(session, model.id, QUESTION)

        variants = session.scalars(
            sa.select(StabilityVariant).order_by(StabilityVariant.variant_index)
        ).all()
        assert variants[0].is_baseline
        assert not any(variant.is_baseline for variant in variants[1:])


class TestTemporalStability:
    def test_the_first_run_has_nothing_to_compare_against(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))

        result = service.run_temporal_stability(session, model.id, QUESTION)

        assert result.verdict is StabilityVerdict.INCONCLUSIVE
        assert result.stability_score is None
        assert result.inputs_changed is False

    def test_unchanged_inputs_allow_a_real_comparison(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))
        service.run_temporal_stability(session, model.id, QUESTION)

        result = service.run_temporal_stability(session, model.id, QUESTION)

        assert result.inputs_changed is False
        assert result.stability_score == 100.0
        assert result.verdict is StabilityVerdict.STABLE

    def test_a_changed_input_is_attributed_not_called_drift(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """The mistake the product exists to avoid: blaming the model for a
        changed corpus."""

        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))
        service.run_temporal_stability(session, model.id, QUESTION)

        service.register_model_version(session, model.id, _version(SUPERSEDED_CORPUS, "v2"))
        result = service.run_temporal_stability(session, model.id, QUESTION)

        assert result.inputs_changed is True
        assert "corpus_version" in result.changed_inputs
        assert result.changed_inputs["corpus_version"] == [
            CURRENT_CORPUS_VERSION,
            SUPERSEDED_CORPUS,
        ]
        # Explicitly not "drifting": the comparison was never valid.
        assert result.verdict is StabilityVerdict.INCONCLUSIVE
        assert result.stability_score is None


class TestEvaluatorVersioning:
    def test_each_judgement_kind_gets_its_own_pinned_evaluator(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))

        service.run_semantic_stability(session, model.id, QUESTION)
        service.run_temporal_stability(session, model.id, QUESTION)

        kinds = session.scalars(sa.select(EvaluatorVersion.kind)).all()
        assert sorted(kinds) == ["semantic_stability", "temporal_stability"]

    def test_the_evaluator_is_reused_across_runs(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))

        for _ in range(3):
            service.run_semantic_stability(session, model.id, QUESTION)

        assert (
            session.scalar(sa.select(sa.func.count()).select_from(EvaluatorVersion)) == 1
        )

    def test_results_reference_the_evaluator_that_produced_them(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))

        result = service.run_semantic_stability(session, model.id, QUESTION)

        assert result.evaluator_version_id is not None
        assert result.confidence_label == "estimated"


class TestReads:
    def test_tests_can_be_filtered_by_kind(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        service.register_model_version(session, model.id, _version(CURRENT_CORPUS_VERSION))
        service.run_semantic_stability(session, model.id, QUESTION)
        service.run_temporal_stability(session, model.id, QUESTION)

        semantic = service.list_stability_tests(session, model.id, kind=StabilityKind.SEMANTIC)
        everything = service.list_stability_tests(session, model.id)

        assert len(semantic) == 1
        assert len(everything) == 2
