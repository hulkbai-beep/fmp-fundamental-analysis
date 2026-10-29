#!/usr/bin/env python3
"""
Fetch the frozen FMP snapshot for the forward-P/E band pilot. Runs on the machine that holds the FMP key.

    python -I -B -X utf8 backtest/pilot/fetch.py --out DIR              # fetch, replacement walk, manifest
    python -I -B -X utf8 backtest/pilot/fetch.py --out DIR --pack ZIP [--scan FILE ...]

Standard library only; requests go through the skill's own client (scripts/fmp_client.py), which reads
FMP_API_KEY from the environment and sends it in a request header. The key is never printed, logged or
written: progress lines carry symbols, parts and row counts only, error text is redacted, and --pack refuses
to zip a snapshot in which the key occurs.

What is fetched (about 600 requests for the 50 drawn companies):
  per company   income statements (quarterly, annual), splits, dividends, earnings dates, profile, today's
                analyst estimates (for the pipeline check), split-adjusted and dividend-adjusted daily bars from
                its own price start (the band needs 3 years before its first member day), the skill's /light
                closes when it is still listed, and the market cap around each split (an independent share
                count for the split-basis audit)
  market        SPY (both daily series) and the 3-month T-bill, from 2007-10-01
The end day is the last completed New York session, frozen in DIR/run.json at the first run: a rerun repeats
the same command and fetches only the files still missing. After the drawn companies, the replacement walk of
status.py runs (fetching a replacement when it reaches one) and writes DIR/status.json; then DIR/manifest.json
lists every file with its rows, first and last date and md5, with the provenance of the run. Nothing goes to
the skill's cache (use_cache=False).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
sys.path.insert(0, str(HERE))
from fmp_client import FMPClient, FMPError, InvalidKey, RestrictedEndpoint  # noqa: E402
import status as ST  # noqa: E402

EOD_ROW_CAP = 5000            # FMP returns at most this many daily rows per request, the newest ones
CHUNK_YEARS = 18              # calendar years per daily request when the span does not fit the cap
CHUNK_FIT_SHARE = 0.97        # a span whose estimated sessions fit 0.97 x the cap takes one request
EXHAUSTED_DAYS = 10           # a chunk ending this far after its `from` means the series starts there
MAX_CHUNKS = 4
FIRST_DAY = dt.date(2008, 1, 2)
LOOKBACK = 1096               # round(365.25 x 3): the band window (analyze.price_range)
WARMUP = 60                   # ATR(14) and the bar cleaning's look-around
GLOBAL_START = FIRST_DAY - dt.timedelta(days=LOOKBACK + WARMUP)       # 2004-11-02
MARKET_START = dt.date(2007, 10, 1)
TREASURY_WINDOW_DAYS = 85     # treasury-rates answers about 90 days counted back from `to` (scripts/macro.py)
NETWORK_STRIKES = 3           # consecutive network failures that stop the run
MARKET = ("SPY",)
ENV_REFUSED = ("FMP_BASE_URL", "FMP_AUTH_STYLE", "FMP_PATH_PREFIX", "FMP_TLS_VERIFY")
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}

SIMPLE = {                    # part -> (endpoint, params): full history in one request each
    "inc_q": ("income-statement", {"period": "quarter", "limit": 120}),
    "inc_a": ("income-statement", {"period": "annual", "limit": 30}),
    "splits": ("splits", {}),
    "div": ("dividends", {"limit": 1000}),
    "earn": ("earnings", {"limit": 200}),
    "profile": ("profile", {}),
}
DAILY = {
    "full": "historical-price-eod/full",                 # split-adjusted open/high/low/close/volume
    "adj": "historical-price-eod/dividend-adjusted",     # split- and dividend-adjusted, for total returns
}


class Stop(Exception):
    """Ends the run with a message (no key in it)."""


def day(x) -> dt.date:
    return dt.date.fromisoformat(str(x)[:10])


def rows_of(data) -> list:
    if isinstance(data, dict):
        data = data.get("historical", [data])
    return data if isinstance(data, list) else []


def us_eastern(utc: dt.datetime) -> dt.datetime:
    """Naive UTC -> naive New York time (US daylight saving rules since 2007), as analyze.us_eastern."""
    mar1, nov1 = dt.datetime(utc.year, 3, 1), dt.datetime(utc.year, 11, 1)
    start = mar1 + dt.timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)
    end = nov1 + dt.timedelta(days=(6 - nov1.weekday()) % 7, hours=6)
    return utc - dt.timedelta(hours=4 if start <= utc < end else 5)


def last_session(now_utc: dt.datetime) -> dt.date:
    """The last New York weekday whose session ended (16:15 ET buffer); holidays fall out with SPY's bars."""
    ny = us_eastern(now_utc)
    d = ny.date()
    if d.weekday() < 5 and (ny.hour, ny.minute) >= (16, 15):
        return d
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def fits(start: dt.date, to: dt.date) -> bool:
    return (to - start).days * 252 / 365.25 <= EOD_ROW_CAP * CHUNK_FIT_SHARE


def daily_history(get, endpoint: str, symbol: str, start: dt.date, end: dt.date) -> tuple[list, str | None, int]:
    """(rows start..end oldest first, problem or None, requests). One request when the span fits under the row
    cap, else newest-first chunks; an empty newest chunk does not end the walk (a series that ended earlier)."""
    seen, to, n = {}, end, 0
    for _ in range(MAX_CHUNKS):
        frm = start if fits(start, to) else \
            max(start, dt.date(to.year - CHUNK_YEARS, to.month, min(to.day, 28)) + dt.timedelta(days=1))
        chunk = [r for r in rows_of(get(endpoint, symbol=symbol, **{"from": frm.isoformat(), "to": to.isoformat()}))
                 if isinstance(r, dict) and r.get("date")]
        n += 1
        for r in chunk:
            if start <= day(r["date"]) <= end:
                seen[str(r["date"])[:10]] = r
        if not chunk:
            if frm <= start:
                break
            to = frm - dt.timedelta(days=1)
            continue
        earliest = min(day(r["date"]) for r in chunk)
        if len(chunk) >= EOD_ROW_CAP:
            to = earliest - dt.timedelta(days=1)
        elif frm <= start or (earliest - frm).days > EXHAUSTED_DAYS:
            break
        else:
            to = frm - dt.timedelta(days=1)
        if to < start:
            break
    else:
        return [seen[d] for d in sorted(seen)], f"stopped after {MAX_CHUNKS} requests", n
    return [seen[d] for d in sorted(seen)], None if seen else "no rows", n


def treasury(get, start: dt.date, end: dt.date) -> tuple[list, list, int]:
    """(rows, problems, requests): 85-day windows, each checked to reach within 5 days of its ends."""
    seen, frm, problems, n = {}, start, [], 0
    while frm <= end:
        to = min(frm + dt.timedelta(days=TREASURY_WINDOW_DAYS - 1), end)
        rows = [r for r in rows_of(get("treasury-rates", **{"from": frm.isoformat(), "to": to.isoformat()}))
                if isinstance(r, dict) and r.get("date")]
        n += 1
        ds = sorted(day(r["date"]) for r in rows)
        if not ds or (ds[0] - frm).days > 5 or (to - ds[-1]).days > 5:
            problems.append({"from": frm.isoformat(), "to": to.isoformat(), "rows": len(ds),
                             "first": ds[0].isoformat() if ds else None, "last": ds[-1].isoformat() if ds else None})
        for r in rows:
            if start <= day(r["date"]) <= end:
                seen[str(r["date"])[:10]] = r
        frm = to + dt.timedelta(days=1)
    return [seen[d] for d in sorted(seen)], problems, n


def price_start(spans: list, end: dt.date) -> dt.date:
    """First day of a company's prices: its first member day in [2008-01-02, end] - 1,156 days."""
    firsts = [max(day(a), FIRST_DAY) for a, b in spans if day(b) > FIRST_DAY and day(a) <= end]
    return GLOBAL_START if not firsts else max(GLOBAL_START, min(firsts) - dt.timedelta(days=LOOKBACK + WARMUP))


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def summary(path: Path) -> dict:
    rows = rows_of(json.loads(path.read_text(encoding="utf-8")))
    dates = sorted(str(r.get("date"))[:10] for r in rows if isinstance(r, dict) and r.get("date"))
    return {"rows": len(rows), "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
            "md5": md5(path)}


def git_head() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=20)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class Fetcher:
    """Writes DIR/raw/<part>/<SYMBOL>.json once per (part, symbol); a part that fails is not written and goes
    to the failure list. Stops after NETWORK_STRIKES network failures in a row, and on a rejected key."""

    def __init__(self, out: Path, client, end: dt.date, key: str | None, records: dict):
        self.out, self.raw, self.client, self.end, self.key = out, out / "raw", client, end, key
        self.records = records
        self.failures, self.optional, self.notes, self.requests, self.strikes = [], [], {}, {}, 0
        self.done = set()

    def redact(self, text: str) -> str:
        return text.replace(self.key, "***") if self.key else text

    def get(self, endpoint, **params):
        try:
            data = self.client.get(endpoint, **params)
        except FMPError as e:
            if isinstance(e, RestrictedEndpoint) or not any(m in str(e) for m in (
                    "network error", "failed after retries", "rate limit or server error")):
                self.strikes = 0
                raise
            self.strikes += 1
            if self.strikes >= NETWORK_STRIKES:
                raise Stop(f"{NETWORK_STRIKES} network or server failures in a row; stopped. Rerun the same "
                           f"command when the connection is back (finished files are kept).")
            raise
        self.strikes = 0
        return data

    def save(self, part: str, name: str, fetch, optional: bool = False) -> None:
        if name.upper() in RESERVED:
            raise Stop(f"{name}: a reserved Windows file name")
        path = self.raw / part / f"{name}.json"
        if path.exists():
            return
        try:
            data, note, n = fetch()
        except (InvalidKey, Stop, KeyboardInterrupt):
            raise
        except Exception as e:                                # noqa: BLE001 (any failure of one part is logged)
            msg = self.redact(f"{type(e).__name__}: {e}")[:300]
            (self.optional if optional else self.failures).append({"part": part, "symbol": name, "error": msg})
            print(f"  {name} {part}: {'not available' if optional else 'FAILED'} ({msg[:120]})", flush=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
        self.requests[f"{part}/{name}"] = n
        if note:
            self.notes[f"{part}/{name}"] = note
        print(f"  {name} {part}: {len(rows_of(data))} rows" + (f" ({note})" if note else ""), flush=True)

    def simple(self, part: str, sym: str):
        ep, params = SIMPLE[part]
        data = self.get(ep, symbol=sym, **params)
        note = None
        if part in ("inc_q", "inc_a") and len(rows_of(data)) <= 5:
            note = f"only {len(rows_of(data))} rows (a capped history?)"
        return data, note, 1

    def estimates(self, sym: str):
        try:
            return self.get("analyst-estimates", symbol=sym, period="annual", page=0, limit=10), None, 1
        except RestrictedEndpoint:
            return self.get("analyst-estimates", symbol=sym, period="annual", page=0, limit=5), "limit=5", 2

    def daily(self, ep: str, sym: str, start: dt.date):
        rows, problem, n = daily_history(self.get, ep, sym, start, self.end)
        note = problem
        if rows and (day(rows[0]["date"]) - start).days > 10 and not problem:
            note = f"first bar {str(rows[0]['date'])[:10]}"
        return rows, note, n

    def company(self, sym: str) -> None:
        """Every part of one company (the series ticker), from its own price start."""
        if sym in self.done:
            return
        self.done.add(sym)
        rec = next((r for r in self.records.values() if (r.get("series") or "") == sym), None)
        start = price_start(rec["spans"], self.end) if rec else GLOBAL_START
        print(f"{sym} (prices from {start})", flush=True)
        for part, ep in DAILY.items():
            self.save(part, sym, lambda ep=ep: self.daily(ep, sym, start))
        for part in SIMPLE:
            self.save(part, sym, lambda part=part: self.simple(part, sym))
        self.save("est", sym, lambda: self.estimates(sym))
        bars = rows_of(_load(self.raw / "full" / f"{sym}.json"))
        listed = bool(bars) and (self.end - day(bars[-1]["date"])).days <= 10
        if listed:                                           # the skill's own close source, for the pipeline check
            years = sorted(str(r.get("date"))[:10] for r in rows_of(_load(self.raw / "inc_a" / f"{sym}.json"))
                           if r.get("date"))
            frm = (day(years[-5:][0]) - dt.timedelta(days=10)) if years else self.end - dt.timedelta(days=4 * 365)
            self.save("light", sym, lambda: (self.get("historical-price-eod/light", symbol=sym,
                                                      **{"from": frm.isoformat(), "to": self.end.isoformat()}), None, 1),
                      optional=True)
        for r in rows_of(_load(self.raw / "splits" / f"{sym}.json")):
            if not r.get("date"):
                continue
            x = day(r["date"])
            if not start <= x <= self.end:
                continue
            name = f"{sym}_{x.isoformat()}"
            self.save("mcap", name, lambda x=x: (self.get(
                "historical-market-capitalization", symbol=sym,
                **{"from": (x - dt.timedelta(days=100)).isoformat(),
                   "to": min(self.end, x + dt.timedelta(days=100)).isoformat()}), None, 1), optional=True)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def check_treasury(raw: Path, sessions: list, problems: list) -> list:
    """Coverage of the T-bill rows over SPY's sessions: at least 95% and no gap over 7 days."""
    days = sorted(str(r["date"])[:10] for r in rows_of(_load(raw / "market" / "treasury.json")) if r.get("date"))
    out = list(problems)
    have = set(days)
    s = [d for d in sessions if d >= MARKET_START.isoformat()]
    share = sum(d in have for d in s) / len(s) if s else 0.0
    gaps = [(a, b) for a, b in zip(days, days[1:]) if (day(b) - day(a)).days > 7]
    if share < 0.95 or gaps:
        out.append({"coverage": round(share, 4), "gaps": gaps[:10]})
    return out


def manifest(out: Path, run: dict, fetcher: Fetcher | None, treasury_problems: list) -> str:
    raw = out / "raw"
    files = sorted(p for p in raw.rglob("*.json"))
    meta = {name: md5(out / name) for name in ("run.json", "status.json", "fetch_log.json") if (out / name).exists()}
    man = {"created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "run": run,
           "network_calls": fetcher.client.stats["network_calls"] if fetcher else None,
           "requests": fetcher.requests if fetcher else {}, "notes": fetcher.notes if fetcher else {},
           "treasury_problems": treasury_problems, "meta_files": meta,
           "files": {str(p.relative_to(out)).replace("\\", "/"): summary(p) for p in files}}
    path = out / "manifest.json"
    if path.exists():                       # a rerun keeps the counts of the earlier runs
        old = json.loads(path.read_text(encoding="utf-8"))
        man["requests"] = {**old.get("requests", {}), **man["requests"]}
        man["notes"] = {**old.get("notes", {}), **man["notes"]}
        man["network_calls"] = (old.get("network_calls") or 0) + (man["network_calls"] or 0)
    path.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return md5(path)


def pack(out: Path, zip_path: Path, scan: list, key: str | None) -> int:
    """Key scan over the snapshot and the given files, then the zip (names relative to the snapshot)."""
    if not key:
        raise Stop("FMP_API_KEY is not set, so the key scan cannot run")
    k = key.strip().encode()
    hits, files = 0, 0
    for p in [out] + [Path(x) for x in scan]:
        if not p.exists():
            raise Stop(f"{p}: not found, so it was not scanned; nothing was zipped")
        for f in ([p] if p.is_file() else sorted(p.rglob("*"))):
            if f.is_file():
                hits += f.read_bytes().count(k)
                files += 1
    print(f"key occurrences: {hits} in {files} files")
    if hits:
        raise Stop("the key occurs in the snapshot or the log; nothing was zipped (find the file by name)")
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    listed = set(man["files"])
    present = {str(f.relative_to(out)).replace("\\", "/") for f in (out / "raw").rglob("*.json")}
    bad = sorted(r for r in listed if not (out / r).exists() or md5(out / r) != man["files"][r]["md5"])
    bad += sorted(present - listed)
    bad += sorted(n for n, h in man.get("meta_files", {}).items() if not (out / n).exists() or md5(out / n) != h)
    if bad:
        raise Stop(f"{len(bad)} files differ from the manifest (rerun the fetch to rewrite it), e.g. {bad[:3]}")
    names = ["manifest.json", "run.json", "fetch_log.json", "status.json"]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            if (out / name).exists():
                z.write(out / name, name)
        for f in sorted((out / "raw").rglob("*.json")):
            z.write(f, str(f.relative_to(out)).replace("\\", "/"))
    print(f"zip md5 {md5(zip_path)}  manifest md5 {md5(out / 'manifest.json')}  ({zip_path.stat().st_size} bytes)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="snapshot folder (outside any repo working tree)")
    ap.add_argument("--sample", default=str(HERE / "sample.json"), help="the drawn sample with the seeded orders")
    ap.add_argument("--end", help="last day (default: the last completed New York session, frozen at the first run)")
    ap.add_argument("--pack", help="write this zip after a key scan (no fetching)")
    ap.add_argument("--scan", nargs="*", default=[], help="more files for the key scan (the console log)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    key = (os.environ.get("FMP_API_KEY") or "").strip() or None      # the value the client sends, for redaction
    try:
        if a.pack:
            return pack(out, Path(a.pack), a.scan, key)
        bad = [v for v in ENV_REFUSED if os.environ.get(v)]
        if bad:
            raise Stop(f"refusing to run with {', '.join(bad)} set (the official host, header auth and TLS checks "
                       f"are required)")
        if int(os.environ.get("FMP_MAX_PER_MIN") or 280) > 280:
            raise Stop("FMP_MAX_PER_MIN is above 280")
        sample_path = Path(a.sample)
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        out.mkdir(parents=True, exist_ok=True)
        run_path = out / "run.json"
        if run_path.exists():
            run = json.loads(run_path.read_text(encoding="utf-8"))
            if a.end and a.end != run["end"]:
                raise Stop(f"this snapshot is frozen at end {run['end']}; use a new folder for another end")
        else:
            end = a.end or last_session(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)).isoformat()
            run = {"end": end, "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "code": git_head(), "fetch_md5": md5(Path(__file__)),
                   "client_md5": md5(HERE.parent.parent / "scripts" / "fmp_client.py"),
                   "status_md5": md5(HERE / "status.py"), "panel_md5": md5(HERE / "panel.py"),
                   "sample_md5": md5(sample_path), "python": sys.version.split()[0], "platform": platform.platform()}
            run_path.write_text(json.dumps(run, indent=1), encoding="utf-8")
        end = day(run["end"])
        client = FMPClient(use_cache=False)
        f = Fetcher(out, client, end, key, sample["records"])
        for sym in MARKET:
            for part, ep in DAILY.items():
                f.save(part, sym, lambda ep=ep: daily_history(f.get, ep, sym, MARKET_START, end))
        tr_path = out / "raw" / "market" / "treasury.json"
        tr_problems = []
        if not tr_path.exists():
            def tr():
                rows, problems, n = treasury(f.get, MARKET_START, end)
                tr_problems.extend(problems)
                return rows, (f"{len(problems)} windows short" if problems else None), n
            f.save("market", "treasury", tr)
        sessions = ST.sessions(out, run["end"])
        if not sessions:
            raise Stop("no SPY sessions: the market files failed")
        z = sessions[-1]
        for sym in sample["sample"]:
            f.company(sample["records"][sym].get("series") or sym)
        st = ST.walk(sample, out, sessions, z, fetch=f.company)
        st.update({"rule": ST.__doc__.strip(), "end": run["end"], "z": z})
        (out / "status.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
        (out / "fetch_log.json").write_text(json.dumps({"failures": f.failures, "optional_missing": f.optional},
                                                       indent=1), encoding="utf-8")
        tr_problems = check_treasury(out / "raw", sessions, tr_problems)
        mm = manifest(out, run, f, tr_problems)
        files = sum(1 for _ in (out / "raw").rglob("*.json"))
        print(f"{files} files, {client.stats['network_calls']} network calls, {len(f.failures)} failures, "
              f"{sum(1 for s in st['replacements'] if s['in'])} replaced, {len(st['review'])} for review; "
              f"Z {z}; manifest md5 {mm}")
        for s in st["replacements"]:
            print(f"  replaced {s['out']} ({s['why']}) -> {s['in']}")
        return 1 if f.failures else 0
    except (Stop, InvalidKey) as e:
        msg = str(e).replace(key, "***") if key else str(e)
        print(f"stopped: {msg}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
