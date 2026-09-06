"""Evaluator boundary for the signature stability tests.

Evaluators are fallible, so the product versions them and records which one
produced each judgement. This module defines the boundary and ships a
deterministic simulated implementation for the demo; a real deployment supplies
its own adapter without anything else changing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

# Return windows by corpus version, for the ShopAssist scenario. The current
# policy extended the window; the retriever kept serving the retired policy.
DEMO_RETURN_WINDOWS: dict[str, str] = {
    "returns-policy-2026-09-01": "30 days from delivery",
    "returns-policy-2026-06-01": "14 days from delivery",
}
CURRENT_CORPUS_VERSION = "returns-policy-2026-09-01"

CLAIM_RETURN_WINDOW = "return_window"


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """One answer plus the material facts it asserts.

    Stability is judged on whether these claims agree, not on whether the
    wording matched, so the evaluator is responsible for extracting them.
    """

    text: str
    claims: dict[str, str] = field(default_factory=dict)


class EvaluatorAdapter(Protocol):
    """Boundary for whatever actually produces and judges answers."""

    simulation: bool
    name: str
    version: str
    provider: str

    def paraphrase(self, question: str, count: int) -> list[str]: ...

    def answer(
        self, *, question: str, corpus_version: str | None, variant_index: int = 0
    ) -> GeneratedAnswer: ...


def _digest(*parts: str | None) -> int:
    material = "|".join(part or "" for part in parts)
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16)


class SimulatedEvaluator:
    """Deterministic evaluator; it calls no external model.

    Behaviour is a pure function of its inputs, because the demo has to produce
    the same result every time it is presented.

    Two properties make the signature tests meaningful:

    * A **current** corpus answers every paraphrase identically, so semantic
      stability is high.
    * A **superseded or unknown** corpus answers inconsistently across
      paraphrases -- some retrievals surface the stale document and some do
      not. That is what a knowledge-freshness failure actually looks like, and
      it is what drives semantic stability down.
    """

    simulation = True
    name = "simulated-evaluator"
    version = "eval-v1"
    provider = "simulated"

    _TEMPLATES = (
        "{question}",
        "Could you tell me: {question}",
        "I need to know — {question}",
        "Quick question, {question}",
        "For my records: {question}",
    )

    def paraphrase(self, question: str, count: int) -> list[str]:
        """Return meaning-preserving rewordings, the original always first."""

        stripped = question.strip()
        return [
            template.format(question=stripped)
            for template in self._TEMPLATES[: max(1, count)]
        ]

    def answer(
        self, *, question: str, corpus_version: str | None, variant_index: int = 0
    ) -> GeneratedAnswer:
        current = DEMO_RETURN_WINDOWS[CURRENT_CORPUS_VERSION]

        if corpus_version == CURRENT_CORPUS_VERSION:
            value = current
        elif corpus_version in DEMO_RETURN_WINDOWS:
            # A stale corpus does not fail uniformly: some paraphrases retrieve
            # the superseded document and some fall through to the current one.
            stale = DEMO_RETURN_WINDOWS[corpus_version]
            value = stale if (variant_index + _digest(question)) % 2 == 0 else current
        else:
            value = current if _digest(question, corpus_version) % 2 == 0 else "unknown"

        return GeneratedAnswer(
            text=f"Items may be returned within {value}.",
            claims={CLAIM_RETURN_WINDOW: value},
        )
