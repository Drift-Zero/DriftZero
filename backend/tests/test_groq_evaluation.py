from app.groq_evaluation import (
    DeterministicProfile,
    GroqCompletion,
    evaluate_completions,
)


def completion(text: str, *, latency: int = 1000) -> GroqCompletion:
    return GroqCompletion(
        text=text,
        model="test-model",
        latency_ms=latency,
        input_tokens=100,
        output_tokens=50,
    )


def test_deterministic_evaluation_scores_declared_evidence_and_api_telemetry() -> None:
    result = evaluate_completions(
        prompt="What is the premium plan storage?",
        completions=[
            completion("The premium plan includes 500 GB storage."),
            completion("Premium customers receive 500 GB of storage."),
        ],
        profile=DeterministicProfile(
            expected_terms=("500 GB",),
            trusted_facts=("premium plan includes 500 GB",),
            forbidden_terms=("unlimited storage",),
            latency_best_ms=200,
            latency_worst_ms=2000,
            cost_max_usd=0.001,
            input_cost_per_million=1.0,
            output_cost_per_million=2.0,
        ),
    )

    assert result.dimensions["groundedness"] == 100.0
    assert result.dimensions["safety"] == 100.0
    assert result.dimensions["reliability"] == 100.0
    assert result.dimensions["latency"] == 55.56
    assert result.dimensions["cost"] == 60.0
    assert result.evidence["estimated_cost_usd"] == 0.0004
    assert result.health_score is not None
    assert result.formula == "weighted-arithmetic-health-v2"


def test_missing_evidence_is_not_reported_as_zero_groundedness() -> None:
    result = evaluate_completions(
        prompt="Write a greeting",
        completions=[completion("Hello there")],
        profile=DeterministicProfile(),
    )

    assert result.dimensions["groundedness"] is None
    assert result.dimensions["semantic_stability"] is None


def test_safety_is_the_safe_response_percentage() -> None:
    unsafe = evaluate_completions(
        prompt="Help",
        completions=[completion("blocked phrase one and blocked phrase two")],
        profile=DeterministicProfile(forbidden_terms=("blocked phrase one", "phrase two")),
    )
    failed = evaluate_completions(
        prompt="Help",
        completions=[],
        profile=DeterministicProfile(),
    )

    assert unsafe.dimensions["safety"] == 0.0
    assert unsafe.evidence["unsafe_responses"] == 1
    assert failed.dimensions["reliability"] is None
    assert failed.health_score is not None


def test_json_adherence_and_pairwise_stability_are_deterministic() -> None:
    result = evaluate_completions(
        prompt="Return JSON",
        completions=[completion('{"answer": 42}'), completion('{"answer": 42}')],
        profile=DeterministicProfile(expected_json=True),
    )

    assert result.dimensions["semantic_stability"] == 100.0
    assert result.dimensions["quality"] is not None
