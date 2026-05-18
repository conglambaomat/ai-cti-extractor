"""Refang utility with offset preservation.

CTI vendors defang IOCs to make reports safe to share (preventing accidental
clicks or auto-detonation in mail clients). Examples:

    evil[.]example.com   -> evil.example.com
    hxxps://bad.com      -> https://bad.com
    user[at]evil.com     -> user@evil.com
    ​...evil.com    -> ...evil.com  (zero-width chars stripped)

The refang must run BEFORE pattern matching, but :class:`IocCandidate.evidence`
points at offsets in the **original** chunk text. To bridge the two, we
build a virtual *refanged view* of the chunk that records, for every char
in the refanged stream, which original char (or range) it came from. The
extractor then matches on the refanged view and resolves spans back to the
original chunk via :meth:`RefangedView.resolve`.

We do not mutate the chunk; we read it in two parallel streams.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DefangRule = tuple[re.Pattern[str], str]

# Rules in order of specificity. Most specific first to avoid double-rewrites.
DEFANG_RULES: tuple[_DefangRule, ...] = (
    (re.compile(r"hxxps://", re.IGNORECASE), "https://"),
    (re.compile(r"hxxp://", re.IGNORECASE), "http://"),
    (re.compile(r"\bfxp://", re.IGNORECASE), "ftp://"),
    (re.compile(r"\[://\]"), "://"),
    (re.compile(r"\[\.\]"), "."),
    (re.compile(r"\(\.\)"), "."),
    (re.compile(r"\[d\]"), "."),
    (re.compile(r"\[at\]", re.IGNORECASE), "@"),
    (re.compile(r"\[@\]"), "@"),
    (re.compile(r"[​‌‍﻿]"), ""),  # zero-width chars
)


@dataclass(frozen=True)
class RefangedView:
    """Refanged text + per-char back-mapping to the original chunk text.

    ``original`` is the chunk text as ingested.
    ``refanged`` is the refanged stream the regex sees.
    ``orig_idx_per_char[i]`` is the index in ``original`` that the i-th char
    of ``refanged`` came from. Stable monotonic non-decreasing.
    """

    original: str
    refanged: str
    orig_idx_per_char: tuple[int, ...]

    def resolve(self, refanged_start: int, refanged_end: int) -> tuple[int, int]:
        """Map a (start, end) span in ``refanged`` back to ``original`` indices.

        Returns a half-open window ``[orig_start, orig_end)`` such that
        ``original[orig_start:orig_end]`` covers exactly the source bytes
        the matched refanged span came from.
        """
        if refanged_start < 0 or refanged_end > len(self.refanged):
            msg = f"span ({refanged_start}, {refanged_end}) out of refanged range"
            raise IndexError(msg)
        if refanged_start >= refanged_end:
            return (refanged_start, refanged_start)

        # Map each refanged char to original. The original window is the
        # min..max+? of those original indices.
        first_orig = self.orig_idx_per_char[refanged_start]

        # Find the original index of the next refanged char (or end-of-text)
        if refanged_end < len(self.orig_idx_per_char):
            last_orig_excl = self.orig_idx_per_char[refanged_end]
        else:
            last_orig_excl = len(self.original)

        return (first_orig, last_orig_excl)


def build_refanged_view(text: str) -> RefangedView:
    """Apply :data:`DEFANG_RULES` to ``text`` while tracking original offsets.

    Algorithm: walk every defang rule once, replace match by replacement,
    rebuild the original-index list. Iteratively until no rule matches.
    Practical CTI text rarely needs more than 1-2 passes.
    """
    refanged: list[str] = list(text)
    orig_idx: list[int] = list(range(len(text)))

    changed = True
    while changed:
        changed = False
        joined = "".join(refanged)
        for pattern, replacement in DEFANG_RULES:
            m = pattern.search(joined)
            if m is None:
                continue
            start, end = m.span()
            # Splice replacement chars in; each replacement char inherits the
            # ORIGINAL index of the FIRST char of the matched region.
            inherit_orig = orig_idx[start]
            refanged[start:end] = list(replacement)
            orig_idx[start:end] = [inherit_orig] * len(replacement)
            changed = True
            break  # restart from first rule after every successful rewrite

    return RefangedView(
        original=text,
        refanged="".join(refanged),
        orig_idx_per_char=tuple(orig_idx),
    )


__all__ = ["DEFANG_RULES", "RefangedView", "build_refanged_view"]
