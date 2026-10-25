#!/usr/bin/env python3
"""
Fundamental scores for a list of stocks, for checking the scoring rules against real data.

Runs analyze.py's analysis for each symbol (no peers, so it costs fewer API calls) and writes:
  scores.csv      one row per stock: total, label, confidence, the four pillars, the business-quality view and
                  quadrant, caps, conflicts
  indicators.csv  one row per stock and indicator: value, score, weight, note
  diff.csv        with --compare: stocks whose score or label changed against an earlier scores.csv

Usage:
  python score_batch.py MSFT COST JPM O NEE
  python score_batch.py --file tickers.txt --out validation/2026-10-24
  python score_batch.py --file tickers.txt --out validation/after --compare validation/before

Options:
  --file PATH      symbols, one per line or comma-separated ("#" starts a comment)
  --out DIR        output folder (default: score-batch)
  --compare DIR    folder holding an earlier scores.csv to diff against
  --years N        fiscal years of history (default 5)
  --no-market      skip Treasury / sector / industry data (fixed 9% discount, no P/E vs industry)
  --refresh        ignore the cache

A stock that fails (unknown symbol, no statements) is listed with its error and the run goes on.
Responses are cached like analyze.py's, so a rerun after a rule change costs no API calls.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze as A  # noqa: E402
import score as S  # noqa: E402
from fmp_client import FMPError, InvalidKey  # noqa: E402
from symbols import normalize_symbol  # noqa: E402

SCORE_FIELDS = ["symbol", "name", "sector", "industry", "kind", "rules", "score", "label", "raw_score",
                "confidence", "coverage", "valuation", "quality", "growth", "health", "business", "quadrant", "caps", "conflicts",
                "issues", "value_basis", "value_mid_vs_price", "price", "error"]
IND_FIELDS = ["symbol", "pillar", "indicator", "status", "value", "unit", "score", "weight", "note"]


def read_symbols(args):
    syms = list(args.symbols)
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0]
            syms += [s for s in line.replace(",", " ").split() if s]
    out = []
    for x in syms:
        try:
            s = normalize_symbol(x)  # BRK.B -> BRK-B
        except ValueError:
            s = x.strip().upper()    # kept as typed: analyze() reports why, and the batch goes on
        if s and s not in out:
            out.append(s)
    return out


def _r(x, d=3):
    return "" if x is None else round(x, d)


def rows_for(sym, r):
    s, prof = r["score"], r.get("profile") or {}
    p, c, vr = s["pillars"], s["confidence"], s.get("value_range") or {}
    row = {
        "symbol": sym, "name": prof.get("companyName"), "sector": prof.get("sector"),
        "industry": prof.get("industry"), "kind": s["kind"], "rules": s["version"], "score": s["score"],
        "label": s["label"], "raw_score": s["raw_score"], "confidence": c["level"], "coverage": _r(c["coverage"], 2),
        "valuation": p["valuation"]["score"], "quality": p["quality"]["score"], "growth": p["growth"]["score"],
        "health": p["health"]["score"], "business": s["views"]["business"], "quadrant": s["views"]["quadrant"],
        "caps": ";".join(x["type"] for x in s["caps"]),
        "conflicts": ";".join(x["type"] for x in s["conflicts"]), "issues": ";".join(c["issues"]),
        "value_basis": vr.get("basis"), "value_mid_vs_price": _r(vr.get("mid_vs_price")),
        "price": _r((r.get("current") or {}).get("price"), 2), "error": "",
    }
    inds = [{"symbol": sym, "pillar": n, "indicator": i["key"], "status": i["status"], "value": _r(i["value"], 4),
             "unit": i["unit"], "score": i["score"], "weight": _r(i["weight_share"]),
             "note": ";".join(x for x in (i["note"], i["detail"].get("base_note")) if x)}
            for n in s["pillar_order"] for i in p[n]["indicators"] if i["status"] != "n/a"]
    return row, inds


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def diff(prev_path, rows):
    """Stocks whose score or label changed against an earlier scores.csv, biggest moves first."""
    with open(prev_path, newline="", encoding="utf-8") as f:
        prev = {row["symbol"]: row for row in csv.DictReader(f)}
    out = []
    for row in rows:
        old = prev.get(row["symbol"])
        if not old or row["error"] or old.get("error"):
            continue
        d = round(float(row["score"]) - float(old["score"]), 2)
        if d or row["label"] != old["label"]:
            out.append({"symbol": row["symbol"], "old_score": old["score"], "new_score": row["score"], "change": d,
                        "old_label": old["label"], "new_label": row["label"],
                        "pillars_changed": ";".join(n for n in S.PILLARS
                                                    if float(old[n]) != float(row[n]))})
    return sorted(out, key=lambda x: -abs(x["change"]))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Fundamental scores for a list of stocks")
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--out", default="score-batch")
    ap.add_argument("--compare")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--no-market", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    syms = read_symbols(args)
    if not syms:
        ap.error("no symbols: pass them as arguments or with --file")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, inds = [], []
    for n, sym in enumerate(syms, 1):
        a = ["--peers", "none", "--no-insider", "--years", str(args.years)] + (["--no-market"] if args.no_market else []) \
            + (["--refresh"] if args.refresh else [])
        try:
            r = A.analyze(A.parse_args([sym] + a))
            row, ind = rows_for(sym, r)
        except InvalidKey as e:  # every later symbol would fail the same way
            print(f"API key problem: {e}", file=sys.stderr)
            return 2
        except (FMPError, SystemExit, Exception) as e:  # one bad symbol must not stop the batch
            row, ind = dict({k: "" for k in SCORE_FIELDS}, symbol=sym, error=f"{type(e).__name__}: {e}"[:300]), []
        rows.append(row)
        inds += ind
        shown = row["error"] or (f"{row['score']:+.2f} {row['label']} ({row['confidence']})"
                                 f"  V {row['valuation']:+.2f}  Q {row['quality']:+.2f}  G {row['growth']:+.2f}"
                                 f"  H {row['health']:+.2f}" + (f"  caps: {row['caps']}" if row["caps"] else ""))
        print(f"[{n}/{len(syms)}] {sym:<6} {shown}", flush=True)

    write_csv(out_dir / "scores.csv", SCORE_FIELDS, rows)
    write_csv(out_dir / "indicators.csv", IND_FIELDS, inds)
    print(f"\nWrote {out_dir / 'scores.csv'} and {out_dir / 'indicators.csv'}")
    if args.compare:
        changed = diff(Path(args.compare) / "scores.csv", rows)
        write_csv(out_dir / "diff.csv", ["symbol", "old_score", "new_score", "change", "old_label", "new_label",
                                         "pillars_changed"], changed)
        print(f"{len(changed)} of {len(rows)} stocks changed; see {out_dir / 'diff.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
