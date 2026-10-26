"""Text that comes from devices is untrusted: clean it where it enters.

Discovery answers are unauthenticated (anything on the LAN can answer), and a
paired thermostat's name is whatever someone set on it or in its app. Such text
ends up in terminals, the state file, status bars, the Omarchy panel and AI
clients, so it must not carry control sequences (terminal escapes), bidi
overrides (text that displays differently from what it is) or unbounded length.
Markup characters (`<`, `|`) are kept: each display escapes for its own syntax.
"""

from __future__ import annotations

import unicodedata

MAX_LEN = 64  # HomeKit's own limit for names

# Bidirectional embeddings, overrides and isolates (Trojan Source, CVE-2021-42574).
_BIDI = set("‪‫‬‭‮⁦⁧⁨⁩‎‏؜")


def clean(value: object, limit: int = MAX_LEN) -> str:
    """Drop control and bidi-control characters and cap the length."""
    text = "" if value is None else str(value)
    text = "".join(c for c in text if c not in _BIDI and unicodedata.category(c) != "Cc")
    return text[:limit]
