"""Redaction applied to prompt and response text before it is stored.

DriftZero keeps trace-level evidence, which means it holds fragments of real
user traffic. Only a redacted rendering is persisted; the hash is taken over the
*original* so duplicate or replayed content can still be recognised after the
text itself is gone.

The policy is versioned. Every stored trace records which version produced its
redaction, so a later change to these rules cannot be mistaken for a change in
the underlying traffic.
"""

from __future__ import annotations

import hashlib
import re

REDACTION_POLICY_VERSION = "redact-v1"

# Order matters, most specific first. Emails are consumed before the numeric
# patterns so their digits cannot be re-matched, and an unbroken digit run is
# treated as an identifier before the looser phone pattern (which allows
# separators) can claim it.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.%+-]+@[\w-]+\.[\w.-]*[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b\d{6,}\b"), "[id]"),
    (re.compile(r"\+?\d[\d\s().-]{8,}\d"), "[phone]"),
)


def redact(text: str | None) -> str | None:
    """Return ``text`` with directly identifying values masked.

    Deliberately conservative and pattern-based: it is a safety net for a demo
    corpus, not a substitute for a real DLP pipeline. It never returns the input
    unchanged when a pattern matched, and it is idempotent — re-redacting
    already-redacted text is a no-op.
    """

    if text is None:
        return None

    redacted = text
    for pattern, placeholder in _PATTERNS:
        redacted = pattern.sub(placeholder, redacted)
    return redacted


def content_hash(text: str | None) -> str | None:
    """Return a stable hash of the original text, before redaction.

    Lets identical questions be correlated across traces without retaining what
    was asked.
    """

    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
