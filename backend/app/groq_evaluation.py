"""Groq inference boundary and transparent, deterministic response evaluation.

Groq is used only to obtain model output.  Every score in this module is a
pure calculation over the captured response, declared expectations, and API
telemetry; evaluating a response never makes a second provider call.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.metric_formulas import (
    consistency_score,
    cost_efficiency_score,
    groundedness_score,
    health_score,
    latency_score,
    quality_score,
    reliability_score,
    safety_score,
)

GROQ_API_ROOT = "https://api.groq.com/openai/v1"
_WORD = re.compile(r"[a-z0-9]+")


class GroqEvaluationError(Exception):
    """A bounded Groq operation failed without exposing its credential."""


@dataclass(frozen=True, slots=True)
class GroqCompletion:
    text: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class DeterministicProfile:
    expected_terms: tuple[str, ...] = ()
    trusted_facts: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    expected_json: bool = False
    feedback_score: float | None = None
    latency_best_ms: int = 200
    latency_worst_ms: int = 2000
    cost_max_usd: float | None = None
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


@dataclass(frozen=True, slots=True)
class DeterministicResult:
    dimensions: dict[str, float | None]
    health_score: float | None
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    formula: str = "weighted-arithmetic-health-v2"


class GroqClient:
    """Small server-side client for the fixed Groq API origin."""

    def __init__(self, api_key: str, *, timeout_seconds: float = 15.0) -> None:
        if not api_key.strip():
            raise GroqEvaluationError("A Groq API key is not configured.")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def list_models(self) -> list[str]:
        payload = self._request("GET", "/models")
        records = payload.get("data", [])
        return sorted(
            str(record["id"])
            for record in records
            if isinstance(record, dict) and record.get("id")
        )

    def complete(self, *, model: str, prompt: str, temperature: float = 0.0) -> GroqCompletion:
        started = time.perf_counter()
        payload = self._request(
            "POST",
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
        )
        latency_ms = max(1, round((time.perf_counter() - started) * 1000))
        try:
            text = str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise GroqEvaluationError(
                "Groq returned a response without assistant content."
            ) from exc
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return GroqCompletion(
            text=text,
            model=str(payload.get("model") or model),
            latency_ms=latency_ms,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        encoded = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{GROQ_API_ROOT}{path}",
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "DriftZero-Groq/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise GroqEvaluationError("Groq response exceeded 1 MiB.")
        except urllib.error.HTTPError as exc:
            raise GroqEvaluationError(f"Groq returned HTTP {exc.code}.") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise GroqEvaluationError(
                "Groq could not be reached within the configured timeout."
            ) from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GroqEvaluationError("Groq returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise GroqEvaluationError("Groq returned an unexpected response shape.")
        return parsed


def evaluate_completions(
    *, prompt: str, completions: list[GroqCompletion], profile: DeterministicProfile
) -> DeterministicResult:
    """Calculate auditable scores without using an LLM evaluator."""

    successful = [item for item in completions if item.text.strip()]
    total = len(completions)
    reliability = reliability_score(
        successful_requests=len(successful), total_requests=total
    )
    joined = "\n".join(item.text for item in successful)
    normalized = _normalize(joined)

    expected_hits = [_normalize(term) in normalized for term in profile.expected_terms]
    fact_hits = [_normalize(fact) in normalized for fact in profile.trusted_facts]
    correctness = _percentage(expected_hits)
    groundedness = groundedness_score(
        supported_claims=sum(fact_hits), total_claims=len(fact_hits)
    )
    relevance = _token_overlap(prompt, joined) if successful else 0.0
    completeness = _json_adherence(successful) if profile.expected_json else 100.0
    quality = quality_score(
        correctness=correctness,
        relevance=relevance,
        completeness=completeness,
        feedback=profile.feedback_score,
    )

    unsafe_outputs = [
        item.text
        for item in successful
        if any(_normalize(term) in _normalize(item.text) for term in profile.forbidden_terms)
    ]
    safety_hits = [term for term in profile.forbidden_terms if _normalize(term) in normalized]
    safety = safety_score(unsafe_responses=len(unsafe_outputs), total_responses=total)
    measured_latencies = [item.latency_ms for item in completions if item.latency_ms > 0]
    average_latency = (
        sum(measured_latencies) / len(measured_latencies) if measured_latencies else 0.0
    )
    latency = latency_score(
        current_ms=average_latency,
        best_ms=profile.latency_best_ms,
        worst_ms=profile.latency_worst_ms,
    ) if measured_latencies else None
    cost = sum(
        item.input_tokens * profile.input_cost_per_million / 1_000_000
        + item.output_tokens * profile.output_cost_per_million / 1_000_000
        for item in completions
    )
    cost_score = (
        cost_efficiency_score(current_cost=cost, maximum_cost=profile.cost_max_usd)
        if profile.cost_max_usd is not None
        else None
    )
    stability = _semantic_stability([item.text for item in successful])

    dimensions: dict[str, float | None] = {
        "quality": _round(quality),
        "groundedness": _round(groundedness),
        "semantic_stability": _round(stability),
        "safety": _round(safety),
        "reliability": _round(reliability),
        "latency": _round(latency),
        "cost": _round(cost_score),
    }
    health = health_score(dimensions)
    available = sum(value is not None for value in dimensions.values())
    evidence_items = len(profile.expected_terms) + len(profile.trusted_facts)
    confidence = min(1.0, 0.35 + 0.08 * available + 0.03 * min(evidence_items, 3))
    return DeterministicResult(
        dimensions=dimensions,
        health_score=_round(health),
        confidence=round(confidence, 2),
        evidence={
            "expected_terms": {
                term: hit
                for term, hit in zip(profile.expected_terms, expected_hits, strict=True)
            },
            "trusted_facts": {
                fact: hit for fact, hit in zip(profile.trusted_facts, fact_hits, strict=True)
            },
            "forbidden_terms_found": safety_hits,
            "unsafe_responses": len(unsafe_outputs),
            "average_latency_ms": round(average_latency),
            "estimated_cost_usd": round(cost, 8),
            "responses_compared": len(successful),
        },
    )


def _normalize(value: str) -> str:
    return " ".join(_WORD.findall(value.lower()))


def _percentage(values: list[bool]) -> float | None:
    return 100.0 * sum(values) / len(values) if values else None


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(_WORD.findall(left.lower()))
    right_tokens = set(_WORD.findall(right.lower()))
    if not left_tokens:
        return 100.0
    return 100.0 * len(left_tokens & right_tokens) / len(left_tokens)


def _json_adherence(completions: list[GroqCompletion]) -> float:
    valid = 0
    for item in completions:
        try:
            json.loads(item.text)
            valid += 1
        except json.JSONDecodeError:
            pass
    return 100.0 * valid / max(1, len(completions))


def _semantic_stability(outputs: list[str]) -> float | None:
    if len(outputs) < 2:
        return None
    scores: list[float] = []
    for index, left in enumerate(outputs):
        left_tokens = set(_WORD.findall(left.lower()))
        for right in outputs[index + 1 :]:
            right_tokens = set(_WORD.findall(right.lower()))
            union = left_tokens | right_tokens
            scores.append(len(left_tokens & right_tokens) / len(union) if union else 1.0)
    return consistency_score(scores)


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None
