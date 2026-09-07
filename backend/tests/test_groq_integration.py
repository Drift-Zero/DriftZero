from sqlalchemy import select

from app.config import Settings
from app.db import AuditEvent, Trace
from app.groq_evaluation import GroqCompletion
from app.schemas import (
    GroqEvaluationProfileInput,
    GroqEvaluationRequest,
    GroqModelImportRequest,
)
from app.service import DriftZeroService, ExternalProviderError


class FakeGroqClient:
    def list_models(self) -> list[str]:
        return ["llama-test", "other-model"]

    def complete(self, *, model: str, prompt: str, temperature: float) -> GroqCompletion:
        assert model == "llama-test"
        assert prompt
        assert temperature == 0
        return GroqCompletion(
            text="The Premium plan includes 500 GB storage.",
            model=model,
            latency_ms=800,
            input_tokens=20,
            output_tokens=10,
        )


def test_import_and_run_groq_model_with_local_scoring(session) -> None:
    service = DriftZeroService(
        Settings(minimum_sample_size=1),
        groq_client=FakeGroqClient(),  # type: ignore[arg-type]
    )
    model = service.import_groq_model(
        session,
        GroqModelImportRequest(
            name="Groq Shop Assistant",
            model_identifier="llama-test",
            actor="operator@example.com",
        ),
    )

    result = service.evaluate_groq_model(
        session,
        model.id,
        GroqEvaluationRequest(
            prompt="What storage does the Premium plan include?",
            repeat=2,
            profile=GroqEvaluationProfileInput(
                expected_terms=["500 GB"],
                trusted_facts=["Premium plan includes 500 GB"],
                forbidden_terms=["unlimited"],
                latency_target_ms=1000,
            ),
            actor="operator@example.com",
        ),
    )

    assert result.model_identifier == "llama-test"
    assert len(result.responses) == 2
    assert result.dimensions.groundedness == 100
    assert result.dimensions.reliability == 100
    assert result.health_score is not None
    assert result.snapshot.trace_count == 2
    assert len(session.scalars(select(Trace).where(Trace.model_id == model.id)).all()) == 2
    audit = session.scalars(
        select(AuditEvent).where(AuditEvent.event_type == "evaluation.groq_completed")
    ).one()
    assert audit.details["formula"] == "weighted-geometric-mean-v1"


def test_groq_configuration_and_catalog_are_validated(session) -> None:
    unconfigured = DriftZeroService(Settings())
    try:
        unconfigured.groq_models()
    except ExternalProviderError as exc:
        assert "DRIFTZERO_GROQ_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected an unconfigured provider error")

    configured = DriftZeroService(
        Settings(),
        groq_client=FakeGroqClient(),  # type: ignore[arg-type]
    )
    assert configured.groq_models().models == ["llama-test", "other-model"]
