"""
Ticker normalisation for every entry point: what people type -> the symbol FMP's stable API expects.

FMP writes share classes with a hyphen (BRK-B, BF-B, HEI-A); people type BRK.B, BRK/B, "brk b" or $BRK.B.
A dot followed by two or more letters is a foreign exchange suffix (SHOP.TO, 0700.HK, SAP.DE), and so are
the one-letter suffixes .L (London) and .T (Tokyo). The skill covers US listings only, so those are refused
with a hint instead of being guessed at. Index symbols keep their caret (^VIX).
"""
from __future__ import annotations

import re

_PLAIN = re.compile(r"^\^?[A-Z]{1,8}$")                           # AAPL, GOOGL, ^VIX
_SHARE_CLASS = re.compile(r"^([A-Z]{1,6})[.\-/ ]([A-Z])$")      # BRK.B, BRK-B, BRK/B, BRK B
_FOREIGN = re.compile(r"^[A-Z0-9]{1,10}\.([A-Z]{1,4})$")         # SHOP.TO, 0700.HK, SAP.DE, 7203.T
# One-letter exchange suffixes that collide with the share-class form: refused rather than turned into X-L.
_ONE_LETTER_EXCHANGES = {"L": "London", "T": "Tokyo"}
EXAMPLES = "e.g. AAPL, BRK.B, ^VIX"


def normalize_symbol(text) -> str:
    """The FMP symbol for a typed ticker; ValueError with a hint when it cannot be a US listing."""
    raw = "" if text is None else str(text)
    s = re.sub(r"\s+", " ", raw.strip().upper())
    if s.startswith("$"):
        s = s[1:].strip()
    if not s:
        raise ValueError("no ticker given")
    if _PLAIN.match(s):
        return s
    m = _SHARE_CLASS.match(s)
    if m:
        root, cls = m.groups()
        if "." in s and cls in _ONE_LETTER_EXCHANGES:
            raise ValueError(f"{raw.strip()!r} looks like a {_ONE_LETTER_EXCHANGES[cls]} listing; this skill covers US "
                             f"listings only (use the US ticker or ADR; a US share class is written {root}-{cls})")
        return f"{root}-{cls}"
    m = _FOREIGN.match(s)
    if m:
        raise ValueError(f"{raw.strip()!r} looks like a non-US listing (exchange suffix .{m.group(1)}); this skill "
                         "covers US listings only: use the US ticker or ADR")
    raise ValueError(f"{raw.strip()!r} is not a US ticker: letters, optionally a share class ({EXAMPLES})")
