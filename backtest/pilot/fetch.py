#!/usr/bin/env python3
"""
Fetch the frozen FMP snapshot for the forward-P/E band pilot. Runs on the machine that holds the FMP key.

    python backtest/pilot/fetch.py --out DIR [--symbols FILE] [--start 2003-01-01]

Standard library only; requests go through the skill's own client (scripts/fmp_client.py), which reads
FMP_API_KEY from the environment and sends it in a request header. The key is never printed, logged or
written: progress lines carry symbols, parts and row counts only.

Writes DIR/raw/<part>/<SYMBOL>.json, one file per (part, symbol). A file that is already there is not
fetched again, so a rerun after an interruption picks up where it stopped; a part that fails is not
written and is listed in DIR/fetch_log.json. Nothing goes to the skill's cache (use_cache=False), so the
snapshot is one consistent download. DIR/manifest.json lists every file with its rows, first and last
date and md5; the analysis refuses a snapshot whose files do not match it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
from fmp_client import FMPClient, FMPError, InvalidKey  # noqa: E402

EOD_ROW_CAP = 5000            # FMP returns at most this many daily rows per request, the newest ones
CHUNK_YEARS = 18              # calendar years per daily-price request (~4,540 sessions, below the cap)
MAX_CHUNKS = 4
TREASURY_WINDOW_DAYS = 90     # treasury-rates answers about 90 days per request (scripts/macro.py)

# part -> (endpoint, params); full history in one request each
SIMPLE = {
    "inc_q": ("income-statement", {"period": "quarter", "limit": 120}),
    "inc_a": ("income-statement", {"period": "annual", "limit": 30}),
    "splits": ("splits", {}),
    "div": ("dividends", {"limit": 1000}),
    "profile": ("profile", {}),
    "earn": ("earnings", {"limit": 200}),
    "est": ("analyst-estimates", {"period": "annual", "limit": 10}),
}
DAILY = {
    "full": "historical-price-eod/full",                 # split-adjusted open/high/low/close
    "adj": "historical-price-eod/dividend-adjusted",     # split- and dividend-adjusted, for returns
}
MARKET = ("SPY",)


def day(x) -> dt.date:
    return dt.date.fromisoformat(str(x)[:10])


def rows_of(data) -> list:
    if isinstance(data, dict):
        data = data.get("historical", [data])
    return data if isinstance(data, list) else []


def daily_history(client, endpoint, symbol, start: dt.date, end: dt.date) -> list:
    """All daily rows start..end, oldest first, in newest-first chunks under the row cap."""
    seen, to = {}, end
    for _ in range(MAX_CHUNKS):
        frm = max(start, dt.date(to.year - CHUNK_YEARS, to.month, min(to.day, 28)) + dt.timedelta(days=1))
        chunk = rows_of(client.get(endpoint, symbol=symbol, **{"from": frm.isoformat(), "to": to.isoformat()}))
        if not chunk:
            break
        for r in chunk:
            seen[str(r["date"])[:10]] = r
        earliest = min(day(r["date"]) for r in chunk)
        if len(chunk) >= EOD_ROW_CAP:
            to = earliest - dt.timedelta(days=1)
        elif frm <= start or (earliest - frm).days > 10:
            break
        else:
            to = frm - dt.timedelta(days=1)
        if to < start:
            break
    else:
        raise FMPError(f"{endpoint}: more than {MAX_CHUNKS} chunks, history not complete")
    return [seen[d] for d in sorted(seen)]


def treasury(client, start: dt.date, end: dt.date) -> list:
    seen, frm = {}, start
    while frm <= end:
        to = min(frm + dt.timedelta(days=TREASURY_WINDOW_DAYS - 1), end)
        for r in rows_of(client.get("treasury-rates", **{"from": frm.isoformat(), "to": to.isoformat()})):
            seen[str(r["date"])[:10]] = r
        frm = to + dt.timedelta(days=1)
    return [seen[d] for d in sorted(seen)]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def summary(path: Path) -> dict:
    rows = rows_of(json.loads(path.read_text(encoding="utf-8")))
    dates = sorted(str(r.get("date"))[:10] for r in rows if isinstance(r, dict) and r.get("date"))
    return {"rows": len(rows), "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
            "md5": md5(path)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="snapshot folder (outside any repo working tree)")
    ap.add_argument("--symbols", default=str(HERE / "symbols.txt"),
                    help="one ticker per line (default: the 50 drawn companies and their spares)")
    ap.add_argument("--start", default="2003-01-01", help="first day of the daily prices")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    a = ap.parse_args(argv)
    out = Path(a.out)
    raw = out / "raw"
    start, end = day(a.start), day(a.end)
    syms = [s.split("#")[0].strip() for s in Path(a.symbols).read_text(encoding="utf-8").splitlines()]
    syms = [s for s in syms if s]
    client = FMPClient(use_cache=False)
    failures = []

    def save(part, name, fetch):
        path = raw / part / f"{name}.json"
        if path.exists():
            return
        try:
            data = fetch()
        except InvalidKey:
            raise
        except FMPError as e:
            failures.append({"part": part, "symbol": name, "error": str(e)[:300]})
            print(f"  {name} {part}: FAILED ({str(e)[:120]})", flush=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
        print(f"  {name} {part}: {len(rows_of(data))} rows", flush=True)

    for i, sym in enumerate(syms + [s for s in MARKET if s not in syms], 1):
        print(f"[{i}/{len(syms) + len(MARKET)}] {sym}", flush=True)
        for part, ep in DAILY.items():
            save(part, sym, lambda ep=ep: daily_history(client, ep, sym, start, end))
        if sym in MARKET:
            continue
        for part, (ep, params) in SIMPLE.items():
            save(part, sym, lambda ep=ep, params=params: client.get(ep, symbol=sym, **params))
    save("market", "treasury", lambda: treasury(client, max(start, dt.date(2005, 1, 1)), end))

    files = sorted(p for p in raw.rglob("*.json"))
    manifest = {"created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "start": a.start, "end": a.end, "symbols": syms, "network_calls": client.stats["network_calls"],
                "files": {str(p.relative_to(out)).replace("\\", "/"): summary(p) for p in files}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "fetch_log.json").write_text(json.dumps({"failures": failures}, indent=1), encoding="utf-8")
    print(f"{len(files)} files, {client.stats['network_calls']} network calls, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
