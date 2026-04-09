"""Regression guard: key docs and templates must contain no mojibake sequences.

'Mojibake' here means UTF-8 multibyte characters misread as Latin-1 and
re-encoded, producing sequences like â€" (U+2014 misread) or the Unicode
replacement character U+FFFD.  The check also flags all non-ASCII characters
in the two files that the audit explicitly targets, so that future edits cannot
silently re-introduce ambiguous glyphs.
"""

import os
import pytest

# Paths relative to the repo root (resolved at import time).
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DOCS = os.path.abspath(os.path.join(_REPO, "..", "docs"))

_TARGET_FILES = [
    os.path.join(_DOCS, "api-spec.md"),
    os.path.join(_REPO, "app", "templates", "schedule", "confirm.html"),
]

# Classic mojibake signatures produced when UTF-8 text is decoded as Latin-1.
_MOJIBAKE_SEQUENCES = [
    "\u00e2\u20ac",   # start of â€" (U+2014 em-dash misread)
    "\u00c3\u00a2",   # start of Ã¢  (various misread sequences)
    "\u00c3\u0082",   # Ã‚ prefix
    "\ufffd",         # Unicode replacement character
]


@pytest.mark.parametrize("path", _TARGET_FILES, ids=[os.path.basename(p) for p in _TARGET_FILES])
def test_no_mojibake(path):
    """File must be valid UTF-8 and contain no mojibake byte sequences."""
    assert os.path.exists(path), f"Target file not found: {path}"
    content = open(path, encoding="utf-8").read()  # raises on invalid UTF-8

    for seq in _MOJIBAKE_SEQUENCES:
        assert seq not in content, (
            f"{os.path.basename(path)} contains mojibake sequence {seq!r}"
        )


@pytest.mark.parametrize("path", _TARGET_FILES, ids=[os.path.basename(p) for p in _TARGET_FILES])
def test_no_non_ascii(path):
    """Audit-targeted files must contain only ASCII characters."""
    assert os.path.exists(path), f"Target file not found: {path}"
    content = open(path, encoding="utf-8").read()

    non_ascii = [
        (content[: i].count("\n") + 1, hex(ord(ch)))
        for i, ch in enumerate(content)
        if ord(ch) > 127
    ]
    assert not non_ascii, (
        f"{os.path.basename(path)} contains {len(non_ascii)} non-ASCII character(s): "
        + ", ".join(f"line {ln} {cp}" for ln, cp in non_ascii[:5])
    )
