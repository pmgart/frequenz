"""Text cleanup for station and place metadata from the public API.

Some names arrive with invisible characters (a zero-width space in "\u200bHsinchu City", a
left-to-right mark after "Nabeul") or with doubled spaces. They look wrong in labels and
sort and search badly, so every value is cleaned before it is stored or shown.
"""

from __future__ import annotations

import unicodedata

# Format characters (category Cf) that carry meaning in some scripts: zero-width joiner and
# zero-width non-joiner. Every other Cf character (zero-width space, bidi marks, BOM, word
# joiner, soft hyphen) is invisible noise and is removed.
_KEEP_FORMAT = frozenset({"\u200c", "\u200d"})


def clean_text(value: str | None) -> str:
    """Return display-safe text: NFC-normalized, no invisible format characters, single spaces."""
    if not value:
        return ""
    text = str(value)
    # Fast path: plain ASCII without edge or doubled spaces is already clean.
    if text.isascii() and text.isprintable() and text == text.strip() and "  " not in text:
        return text
    normalized = unicodedata.normalize("NFC", text)
    pieces: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if category == "Cf" and char not in _KEEP_FORMAT:
            continue
        if category == "Cc":  # tabs, line breaks and other control characters
            pieces.append(" ")
            continue
        pieces.append(char)
    return " ".join("".join(pieces).split())
