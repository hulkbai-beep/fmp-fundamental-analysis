"""SPY and the 3-month Treasury bill from the snapshot: the cash rate known on a day and SPY's total return."""
from __future__ import annotations

import bisect
import json
from pathlib import Path

from panel import fnum, read


class Rates:
    """rates(day_iso) -> the 3-month T-bill yield (a fraction) of the latest Treasury row on or before that day."""

    def __init__(self, rows: list):
        pts = sorted((str(r["date"])[:10], fnum(r.get("month3"))) for r in rows if r.get("date"))
        pts = [(d, y / 100.0) for d, y in pts if y is not None]
        self.days = [d for d, _ in pts]
        self.vals = [y for _, y in pts]

    def __call__(self, d: str) -> float:
        i = bisect.bisect_right(self.days, d) - 1
        return self.vals[i] if i >= 0 else 0.0


class Spy:
    """SPY's dividend-adjusted closes and opens (adjClose / adjOpen) by day."""

    def __init__(self, rows: list):
        rows = sorted((str(r["date"])[:10], fnum(r.get("adjOpen")), fnum(r.get("adjClose"))) for r in rows
                      if r.get("date"))
        rows = [x for x in rows if x[2]]
        self.days = [d for d, _, _ in rows]
        self.open = [o for _, o, _ in rows]
        self.close = [c for _, _, c in rows]

    def close_on(self, d: str) -> float | None:
        """The last close on or before d."""
        i = bisect.bisect_right(self.days, d) - 1
        return self.close[i] if i >= 0 else None

    def open_on(self, d: str) -> float | None:
        """The open of d, or of the next SPY session when SPY did not trade on d."""
        i = bisect.bisect_left(self.days, d)
        return self.open[i] if i < len(self.days) and self.open[i] else self.close_on(d)


def load(snap: Path) -> tuple[Rates, Spy]:
    raw = Path(snap) / "raw"
    return Rates(read(raw / "market" / "treasury.json")), Spy(read(raw / "adj" / "SPY.json"))


def check_manifest(snap: Path) -> list:
    """Files whose md5 differs from the manifest (or that are missing): the analysis refuses such a snapshot."""
    import hashlib
    snap = Path(snap)
    man = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    bad = []
    for rel, meta in man["files"].items():
        p = snap / rel
        if not p.exists() or hashlib.md5(p.read_bytes()).hexdigest() != meta["md5"]:
            bad.append(rel)
    return bad
