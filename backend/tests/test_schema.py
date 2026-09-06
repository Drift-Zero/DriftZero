"""Behaviour the schema is responsible for enforcing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db import (
    Database,
    Diagnosis,
    DiagnosisEvidence,
    HealthSnapshot,
    HealthState,
    MonitoredModel,
    RecoveryPlan,
    RiskLevel,
    Trace,
    TraceStatus,
    utc_now,
)
from tests.conftest import make_snapshot


class TestTimestamps:
    """SQLite silently drops timezone offsets; UtcDateTime must not."""

    def test_round_trips_as_aware_utc(self, database: Database, session: Session) -> None:
        model = MonitoredModel(name="CampusGPT")
        session.add(model)
        session.commit()

        observed = datetime(2026, 3, 1, 12, 30, tzinfo=UTC)
        session.add(make_snapshot(model.id, observed_at=observed))
        session.commit()

        with database.session_factory() as fresh:
            loaded = fresh.execute(sa.select(HealthSnapshot)).scalar_one()
            assert loaded.observed_at.tzinfo is not None
            assert loaded.observed_at == observed

    def test_loaded_timestamps_are_comparable_with_utc_now(
        self, database: Database, session: Session
    ) -> None:
        """The failure that would otherwise surface inside forecast_health."""

        model = MonitoredModel(name="CampusGPT")
        session.add(model)
        session.commit()
        session.add(make_snapshot(model.id, observed_at=utc_now() - timedelta(minutes=10)))
        session.commit()

        with database.session_factory() as fresh:
            loaded = fresh.execute(sa.select(HealthSnapshot)).scalar_one()
            # Raises TypeError if the stored value comes back naive.
            assert utc_now() - loaded.observed_at > timedelta(0)

    def test_naive_input_is_treated_as_utc(self, session: Session, model: MonitoredModel) -> None:
        naive = datetime(2026, 3, 1, 12, 30)
        session.add(make_snapshot(model.id, observed_at=naive))
        session.commit()

        loaded = session.execute(sa.select(HealthSnapshot)).scalar_one()
        assert loaded.observed_at == naive.replace(tzinfo=UTC)


class TestConstraints:
    def test_score_above_range_is_rejected(self, session: Session, model: MonitoredModel) -> None:
        session.add(make_snapshot(model.id, score=150.0))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_coverage_above_one_is_rejected(self, session: Session, model: MonitoredModel) -> None:
        snapshot = make_snapshot(model.id)
        snapshot.coverage = 1.5
        session.add(snapshot)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_unknown_enum_value_is_rejected(self, session: Session, model: MonitoredModel) -> None:
        snapshot = make_snapshot(model.id)
        snapshot.state = "degraded-ish"
        session.add(snapshot)
        with pytest.raises((LookupError, StatementError)):
            session.commit()

    def test_model_name_is_unique_within_a_tenant(self, session: Session) -> None:
        session.add_all([MonitoredModel(name="CampusGPT"), MonitoredModel(name="CampusGPT")])
        with pytest.raises(IntegrityError):
            session.commit()

    def test_recovery_plan_idempotency_key_is_unique(
        self, session: Session, model: MonitoredModel
    ) -> None:
        snapshot = make_snapshot(model.id)
        session.add(snapshot)
        session.commit()
        diagnosis = Diagnosis(
            model_id=model.id,
            snapshot_id=snapshot.id,
            probable_cause="knowledge_freshness",
            confidence=0.87,
        )
        session.add(diagnosis)
        session.commit()

        for _ in range(2):
            session.add(
                RecoveryPlan(
                    model_id=model.id,
                    diagnosis_id=diagnosis.id,
                    risk=RiskLevel.MEDIUM,
                    idempotency_key="replay-me",
                )
            )
        with pytest.raises(IntegrityError):
            session.commit()

    def test_diagnosis_confidence_must_be_a_probability(
        self, session: Session, model: MonitoredModel
    ) -> None:
        snapshot = make_snapshot(model.id)
        session.add(snapshot)
        session.commit()
        session.add(
            Diagnosis(
                model_id=model.id,
                snapshot_id=snapshot.id,
                probable_cause="knowledge_freshness",
                confidence=87.0,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


class TestCascades:
    def test_orm_delete_removes_dependent_rows(
        self, session: Session, model: MonitoredModel
    ) -> None:
        session.add(make_snapshot(model.id))
        session.add(
            Trace(model_id=model.id, occurred_at=utc_now(), status=TraceStatus.OK)
        )
        session.commit()

        session.delete(model)
        session.commit()

        assert session.execute(sa.select(sa.func.count()).select_from(HealthSnapshot)).scalar() == 0
        assert session.execute(sa.select(sa.func.count()).select_from(Trace)).scalar() == 0

    def test_database_enforces_cascade_without_the_orm(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """Proves the SQLite foreign-key pragma is actually applied."""

        session.add(make_snapshot(model.id))
        session.commit()

        session.execute(sa.delete(MonitoredModel).where(MonitoredModel.id == model.id))
        session.commit()

        assert session.execute(sa.select(sa.func.count()).select_from(HealthSnapshot)).scalar() == 0

    def test_foreign_keys_are_enforced(self, session: Session) -> None:
        session.add(make_snapshot("does-not-exist"))
        with pytest.raises(IntegrityError):
            session.commit()


class TestMutableJson:
    def test_in_place_list_mutation_is_persisted(
        self, database: Database, session: Session, model: MonitoredModel
    ) -> None:
        snapshot = make_snapshot(model.id, score=None, state=HealthState.INSUFFICIENT_DATA)
        session.add(snapshot)
        session.commit()

        snapshot.missing_dimensions.append("groundedness")
        session.commit()

        with database.session_factory() as fresh:
            loaded = fresh.execute(sa.select(HealthSnapshot)).scalar_one()
            assert loaded.missing_dimensions == ["groundedness"]


class TestEvidenceDrilldown:
    def test_evidence_links_to_the_traces_behind_it(
        self, session: Session, model: MonitoredModel
    ) -> None:
        snapshot = make_snapshot(model.id)
        traces = [
            Trace(model_id=model.id, occurred_at=utc_now(), unsupported_claim_count=2)
            for _ in range(3)
        ]
        session.add_all([snapshot, *traces])
        session.commit()

        diagnosis = Diagnosis(
            model_id=model.id,
            snapshot_id=snapshot.id,
            probable_cause="knowledge_freshness",
            confidence=0.87,
        )
        evidence = DiagnosisEvidence(
            diagnosis=diagnosis,
            reason_code="unsupported_claims_rising",
            metric="unsupported_claim_rate",
            summary="Unsupported claims rose from 2% to 19%.",
            supports_diagnosis=True,
            traces=traces,
        )
        session.add_all([diagnosis, evidence])
        session.commit()

        loaded = session.execute(sa.select(Diagnosis)).scalar_one()
        assert len(loaded.evidence_items) == 1
        assert len(loaded.evidence_items[0].traces) == 3
