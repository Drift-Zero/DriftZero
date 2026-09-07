"""Shared tokenisation for retrieval and deterministic comparison.

Both steps must fold words identically. If retrieval matched "returned" to a
fact about "return" but the comparator did not, a claim would be handed
evidence that then failed to settle it -- and the operator would see
``insufficient_evidence`` next to a passage that plainly answers the question.
One implementation removes that possibility.

The stemmer is deliberately small: no dependency, and it only folds the
inflections that actually occur in policy and catalogue text -- plurals and
regular verb endings. Exact linguistic correctness is not required, only that
both sides agree.
"""

from __future__ import annotations

import re

WORD = re.compile(r"[a-z0-9]+")

# Words that carry no retrieval signal; without these, any chunk matches any claim.
STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
        "for", "from", "has", "have", "how", "in", "into", "is", "it", "its",
        "may", "of", "on", "or", "that", "the", "their", "there", "these",
        "they", "this", "to", "was", "were", "what", "when", "which", "who",
        "will", "with", "within", "you", "your",
    ]
)

_MIN_STEM = 3


_SIBILANTS = ("s", "x", "z", "ch", "sh")


def stem(word: str) -> str:
    """Fold a word to a comparison key.

    ``return``, ``returns`` and ``returned`` must all reach the same key, and so
    must ``ship``, ``shipping`` and ``shipped``.

    Suffix order matters. Stripping ``es`` before ``s`` would fold ``prices`` to
    ``pric`` while leaving ``price`` alone -- the singular and plural of the same
    word landing on different keys, which is precisely the disagreement this
    module exists to prevent. So ``es`` is only removed after a sibilant, where
    it is genuinely the plural marker.
    """

    lowered = word.lower()

    if lowered.endswith("ies") and len(lowered) > 4:
        return lowered[:-3] + "y"

    for suffix in ("ing", "ed"):
        if lowered.endswith(suffix) and len(lowered) - len(suffix) >= _MIN_STEM:
            trimmed = lowered[: -len(suffix)]
            # "shipping" -> "shipp" -> "ship", but leave "ss" and "ll" alone.
            if len(trimmed) > _MIN_STEM and trimmed[-1] == trimmed[-2] and trimmed[-1] not in "sl":
                trimmed = trimmed[:-1]
            return trimmed

    if lowered.endswith("es") and len(lowered) - 2 >= _MIN_STEM:
        base = lowered[:-2]
        if base.endswith(_SIBILANTS):
            return base

    if lowered.endswith("s") and not lowered.endswith("ss") and len(lowered) - 1 >= _MIN_STEM:
        return lowered[:-1]

    return lowered


def stems(text: str, *, drop_stopwords: bool = False) -> set[str]:
    """Every distinct comparison key in a piece of text."""

    words = WORD.findall(text.lower())
    if drop_stopwords:
        words = [word for word in words if word not in STOPWORDS]
    return {stem(word) for word in words}
