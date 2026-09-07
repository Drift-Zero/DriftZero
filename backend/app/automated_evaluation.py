"""Generate and run deterministic health checks from approved JSON evidence.

The monitored model is only used to answer generated questions. Expected
answers, pass/fail verdicts, dimensions, and the final health score are all
calculated locally so the result remains reproducible and auditable.
"""

from __future__ import annotations

import copy
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.config import Settings
from app.connections import ConnectionCheckError, CredentialVault, validate_target_url
from app.db import EvidenceSource, ModelConnection, ModelVersion, MonitoredModel
from app.groq_evaluation import GroqClient, GroqEvaluationError
from app.metric_formulas import consistency_score, latency_score, reliability_score
from app.schemas import DimensionScores

_WORD = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w.])")
_SUBJECT_KEYS = ("name", "title", "product", "model", "item", "label")
_SKIP_KEYS = {
    "id",
    "created_at",
    "updated_at",
    "timestamp",
    "metadata",
    "evidence_quote",
    "source_url",
    "content_hash",
}
_QUESTION_TEMPLATES = (
    "What is the {field} for {subject}?",
    "Tell me the {field} of {subject}.",
    "For {subject}, what should the {field} be?",
    "According to the approved data, what is {subject}'s {field}?",
    "Can you confirm the {field} for {subject}?",
)


class AutomatedEvaluationError(Exception):
    """A safe error that can be shown to an operator."""


@dataclass(frozen=True, slots=True)
class GeneratedCase:
    assertion_id: str
    question: str
    expected: str
    expected_value: object
    field: str
    source_id: str
    source_name: str
    locator: dict[str, object]


@dataclass(frozen=True, slots=True)
class ModelAnswer:
    text: str
    latency_ms: int


@dataclass(frozen=True, slots=True)
class ExecutedCase:
    case: GeneratedCase
    actual: str
    passed: bool
    latency_ms: int
    failure_reason: str | None


def _friendly(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip()


def _render_expected(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return "Not specified"
    return str(value)


def _records_from_chunk(text: str) -> list[dict[str, object]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def generate_cases(
    sources: Iterable[EvidenceSource], *, max_questions: int, variants: int
) -> list[GeneratedCase]:
    """Turn approved JSON records into plain-language factual questions."""

    assertions: list[tuple[str, object, str, EvidenceSource, dict[str, object]]] = []
    for source in sources:
        if source.status != "approved" or not source.filename.lower().endswith(".json"):
            continue
        for chunk in source.chunks:
            for record in _records_from_chunk(chunk.text):
                subject_key = next(
                    (key for key in _SUBJECT_KEYS if record.get(key) not in (None, "")), None
                )
                subject = str(record.get(subject_key)) if subject_key else source.name
                candidates = [
                    (str(key), value)
                    for key, value in record.items()
                    if key != subject_key
                    and key.lower() not in _SKIP_KEYS
                    and not isinstance(value, (dict, list))
                    and value is not None
                ]
                if not candidates and subject_key:
                    candidates = [(subject_key, record[subject_key])]
                    subject = source.name
                for field, expected in candidates:
                    assertions.append((field, expected, subject, source, dict(chunk.locator)))

    cases: list[GeneratedCase] = []
    for assertion_index, (field, expected, subject, source, locator) in enumerate(assertions):
        assertion_id = f"{source.id}:{assertion_index}:{field}"
        for template in _QUESTION_TEMPLATES[:variants]:
            cases.append(
                GeneratedCase(
                    assertion_id=assertion_id,
                    question=template.format(field=_friendly(field), subject=subject),
                    expected=_render_expected(expected),
                    expected_value=expected,
                    field=field,
                    source_id=source.id,
                    source_name=source.name,
                    locator=locator,
                )
            )
            if len(cases) >= max_questions:
                return cases
    return cases


def answer_matches(expected: object, actual: str) -> bool:
    """Compare an answer with an exact source value without another model call."""

    lowered = actual.casefold()
    if isinstance(expected, bool):
        positive = bool(re.search(r"\b(yes|true|available|allowed)\b", lowered))
        negative = bool(re.search(r"\b(no|false|unavailable|not allowed|not available)\b", lowered))
        return (expected and positive and not negative) or (not expected and negative)
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        numbers = [float(match.replace(",", "")) for match in _NUMBER.findall(actual)]
        return any(abs(number - float(expected)) < 1e-9 for number in numbers)
    expected_words = _WORD.findall(str(expected).casefold())
    actual_words = _WORD.findall(lowered)
    if not expected_words:
        return False
    width = len(expected_words)
    return any(
        actual_words[index : index + width] == expected_words for index in range(len(actual_words))
    )


def run_cases(
    cases: list[GeneratedCase], invoke: Callable[[str], ModelAnswer]
) -> list[ExecutedCase]:
    results: list[ExecutedCase] = []
    for case in cases:
        answer = invoke(case.question)
        passed = answer_matches(case.expected_value, answer.text)
        results.append(
            ExecutedCase(
                case=case,
                actual=answer.text,
                passed=passed,
                latency_ms=answer.latency_ms,
                failure_reason=(
                    None
                    if passed
                    else (
                        f"Expected {case.expected!r} from {case.source_name}, "
                        "but the response did not match."
                    )
                ),
            )
        )
    return results


def dimensions_from_results(
    results: list[ExecutedCase], *, latency_best_ms: int, latency_worst_ms: int
) -> DimensionScores:
    if not results:
        return DimensionScores()
    pass_rate = 100.0 * sum(item.passed for item in results) / len(results)
    groups: dict[str, list[str]] = {}
    for item in results:
        groups.setdefault(item.case.assertion_id, []).append(item.actual)
    similarities: list[float] = []
    for outputs in groups.values():
        for index, left in enumerate(outputs):
            left_tokens = set(_WORD.findall(left.lower()))
            for right in outputs[index + 1:]:
                right_tokens = set(_WORD.findall(right.lower()))
                union = left_tokens | right_tokens
                similarities.append(len(left_tokens & right_tokens) / len(union) if union else 1.0)
    stability = consistency_score(similarities)
    average_latency = sum(item.latency_ms for item in results) / len(results)
    latency = latency_score(
        current_ms=average_latency, best_ms=latency_best_ms, worst_ms=latency_worst_ms
    )
    return DimensionScores(
        quality=round(pass_rate, 1),
        groundedness=round(pass_rate, 1),
        semantic_stability=round(stability, 1) if stability is not None else None,
        reliability=round(
            reliability_score(
                successful_requests=len(results), total_requests=len(results)
            )
            or 0,
            1,
        ),
        latency=round(latency, 1),
    )


class ModelInvoker:
    """Invoke either a registered API endpoint or a backend-owned Groq model."""

    def __init__(
        self,
        settings: Settings,
        vault: CredentialVault,
        groq_client: GroqClient | None,
    ) -> None:
        self.settings = settings
        self.vault = vault
        self.groq_client = groq_client

    def build(
        self,
        model: MonitoredModel,
        version: ModelVersion | None,
        connections: list[ModelConnection],
    ) -> tuple[Callable[[str], ModelAnswer], str]:
        if model.provider.casefold() == "groq" and self.groq_client and version:
            return self._groq(version.model_identifier), f"Groq · {version.model_identifier}"
        connection = next(
            (
                item
                for item in connections
                if item.kind == "api" and item.status in {"configured", "connected"}
            ),
            None,
        )
        if connection is None:
            raise AutomatedEvaluationError(
                "No callable model connection is ready. Add an API connection for this model "
                "or configure the backend-owned Groq integration."
            )
        return self._api(connection), connection.name

    def _groq(self, model_identifier: str) -> Callable[[str], ModelAnswer]:
        def invoke(question: str) -> ModelAnswer:
            try:
                result = self.groq_client.complete(  # type: ignore[union-attr]
                    model=model_identifier, prompt=question, temperature=0.0
                )
            except GroqEvaluationError as exc:
                raise AutomatedEvaluationError(str(exc)) from exc
            return ModelAnswer(result.text, result.latency_ms)

        return invoke

    def _api(self, connection: ModelConnection) -> Callable[[str], ModelAnswer]:
        endpoint = connection.api_endpoint
        if not endpoint:
            raise AutomatedEvaluationError("The selected API connection has no endpoint.")
        try:
            validate_target_url(endpoint, self.settings)
            credential = self.vault.decrypt(connection.credential_ciphertext)
        except ConnectionCheckError as exc:
            raise AutomatedEvaluationError(str(exc)) from exc
        config = connection.config or {}
        request_field = str(config.get("request_field") or "message")
        response_path = str(config.get("response_path") or "answer")

        def invoke(question: str) -> ModelAnswer:
            sample = config.get("sample_request")
            body = copy.deepcopy(sample) if isinstance(sample, dict) else {}
            body[request_field] = question
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "DriftZero-Automated-Evaluation/1.0",
            }
            if credential:
                header = "X-API-Key" if connection.auth_scheme == "x-api-key" else "Authorization"
                headers[header] = credential if header == "X-API-Key" else f"Bearer {credential}"
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(body).encode(),
                headers=headers,
                method="POST",
            )
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(
                    request, timeout=self.settings.connection_check_timeout_seconds
                ) as response:
                    raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise AutomatedEvaluationError("Model response exceeded 1 MiB.")
                payload = json.loads(raw)
                value: object = payload
                for part in response_path.split("."):
                    value = value[int(part)] if isinstance(value, list) else value[part]  # type: ignore[index]
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                raise AutomatedEvaluationError(
                    "The model endpoint could not answer a test question."
                ) from exc
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
                raise AutomatedEvaluationError(
                    f"The model response did not contain configured path '{response_path}'."
                ) from exc
            return ModelAnswer(
                text=str(value),
                latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
            )

        return invoke
