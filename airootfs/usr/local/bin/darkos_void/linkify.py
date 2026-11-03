#!/usr/bin/env python3
"""Classifies clickable text in scrollback: URLs, IPv4 (+ CIDR), hashes,
CVE ids.

Patterns are plain `re`-compatible strings so `classify()` here and
`Vte.Regex.new_for_match()` in `darkos-terminal.py` compile the *same*
source string — one definition, not two regex dialects to keep in sync.
VTE needs PCRE2 flags passed as an int (`PCRE2_FLAGS`), since VTE's
`Vte.Regex` has no Python `re`-flag equivalent; the values are
`PCRE2_MULTILINE` (0x400) and `PCRE2_CASELESS` (0x8) from `pcre2.h`,
confirmed against `/usr/include/pcre2.h` rather than assumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PCRE2_MULTILINE = 0x00000400
PCRE2_CASELESS = 0x00000008

# (kind, pattern, re.flags, pcre2_flags) — ordered by match priority when
# two candidates start at the same offset (widest/most-specific first).
_KINDS = (
    ("url", r"(?:https?|ftp)://[^\s<>\"'`]+", 0, PCRE2_MULTILINE),
    ("sha256", r"\b[A-Fa-f0-9]{64}\b", 0, PCRE2_MULTILINE),
    ("sha1", r"\b[A-Fa-f0-9]{40}\b", 0, PCRE2_MULTILINE),
    ("md5", r"\b[A-Fa-f0-9]{32}\b", 0, PCRE2_MULTILINE),
    ("cve", r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE, PCRE2_MULTILINE | PCRE2_CASELESS),
    ("ipv4_cidr",
     r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)/(?:3[0-2]|[12]?\d)\b",
     0, PCRE2_MULTILINE),
    ("ipv4", r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b",
     0, PCRE2_MULTILINE),
)

PATTERNS = {kind: pattern for kind, pattern, _, _ in _KINDS}
PCRE2_FLAGS = {kind: flags for kind, _, _, flags in _KINDS}
_COMPILED = [(kind, re.compile(pattern, flags)) for kind, pattern, flags, _ in _KINDS]

# Context-menu actions per kind: (action_id, label). darkos-terminal.py maps
# action_id to behaviour; copy is universal, open/set-target are kind-specific.
# Deliberately no "look up" / "search online" action for hashes or CVE ids —
# The Void never makes a network call on the user's behalf.
_ACTIONS = {
    "url": (("open", "Open"), ("copy", "Copy")),
    "ipv4": (("set-target", "Set as Target"), ("copy", "Copy")),
    "ipv4_cidr": (("set-target", "Set as Target"), ("copy", "Copy")),
    "sha256": (("copy", "Copy"),),
    "sha1": (("copy", "Copy"),),
    "md5": (("copy", "Copy"),),
    "cve": (("copy", "Copy"),),
}


@dataclass(frozen=True)
class Match:
    kind: str
    start: int
    end: int
    value: str


def classify(text: str) -> list[Match]:
    """Every non-overlapping match in `text`, left to right.

    Collects all candidates from all kinds, then greedily keeps the
    earliest-starting one at each position (ties broken by longest span,
    i.e. `_KINDS` order), dropping anything that overlaps a kept match —
    so a hash-looking run inside a URL is reported once, as the URL.
    """
    candidates = []
    for kind, regex in _COMPILED:
        for m in regex.finditer(text):
            candidates.append(Match(kind, m.start(), m.end(), m.group(0)))
    candidates.sort(key=lambda m: (m.start, -(m.end - m.start)))
    kept: list[Match] = []
    last_end = -1
    for m in candidates:
        if m.start >= last_end:
            kept.append(m)
            last_end = m.end
    return kept


def actions_for(kind: str) -> tuple[tuple[str, str], ...]:
    """(action_id, label) pairs for a match kind's right-click menu."""
    return _ACTIONS.get(kind, (("copy", "Copy"),))
