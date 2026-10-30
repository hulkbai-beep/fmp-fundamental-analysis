"""
One company's daily panel from the frozen snapshot: cleaned split-adjusted bars, dividends, ATR(14),
S&P 500 membership, and on every day the 3-year P/E band of each EPS version, built with the skill's own
functions (analyze._band, analyze.history_problem, analyze._ntm), none of them edited.

EPS versions (the user chose T as the main result, F as an optimistic ceiling only):
  T   TTM diluted EPS known on the day: the latest four quarters known before the day (one value per period
      end, the latest filing known by then wins), whose period ends span at most 330 days and the newest of
      which ended at most 200 days earlier. A quarter counts as known from its filing date; a filing date
      missing or less than 10 days after the period end is FMP's placeholder, replaced by the period end
      + 45 days (Q1-Q3) or + 90 days (Q4, annual).
  F   the fiscal-year EPS the company later reported, blended to next-twelve-months like the skill's forward
      P/E (_ntm): perfect foresight, so it reads high. Defined up to the end of the second-to-last reported
      fiscal year ("beyond_horizon" after it) and not across a loss year.
  FY  variant of F: this fiscal year's reported EPS x F's band (the skill's UI card "FY<current>").
On day d the band is the daily P/E over the window the skill uses (prices from d - round(365.25 x 3) days to
d) with positive EPS, at least 120 such days; low / mid / high = EPS(d) x p25 / median / p75 and the
temperature is EPS(d)'s percentile in it (the skill's now_pct). No band when EPS(d) <= 0, under 120 days, or
when history_problem objects (share-basis step or a one-day price move outside 0.5-2x).

Statements are put on the split basis of the prices (today's) before anything else: whether FMP restated a
row for a later split is judged by the row's filing date (statements filed after a split show the new basis,
whatever period they cover), from the diluted share counts across each split; see normalize_basis.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import analyze as A  # noqa: E402

LOOKBACK_DAYS = round(365.25 * 3)        # analyze.price_range(lookback_years=3)
MIN_BAND_DAYS = 120                      # analyze.multiple_bands
INCOME_LAG = {"Q1": 45, "Q2": 45, "Q3": 45, "Q4": 90, "FY": 90}   # placeholder filing dates (V3 ladder_sim S13)
MIN_FILE_DAYS = 10                       # a filing date closer than this to the period end is a placeholder
TTM_SPAN = 330                           # the four summed quarters' period ends span at most this many days
TTM_STALE_DAYS = 200                     # the newest of them ended at most this long before the day
ATR_N = 14
SPLIT_MIN = math.log(1.02)               # smaller factors are ignored
SPLIT_WEAK = math.log(1.25)              # below this the share-count test needs clearer evidence
STEP_BAND = (0.8, 1.25)                  # consecutive diluted share counts outside this are a step to explain
EPS_SHARES_OK = (0.6, 1.6)               # EPS x diluted shares / net income outside this is listed for review
UNIT_SLIP = 1000.0                       # EPS x shares / NI this far off (within 2%): one field is in the wrong unit
UNIT_NEAR_DAYS = 730                     # ... and the EPS is the wrong one when it is 100 times off the EPS of the
UNIT_OFF = math.log(100.0)               #     company's other rows with period ends this close
SHARE_UNITS = (1e3, 1e6, 1e-3, 1e-6)     # a share count this many times off the median of the company's rows
SHARE_UNIT_NEAR = math.log(1.5)          # known by then within two years (to within this) is in the wrong unit
YEAR_DAYS = 340                          # a fiscal year's quarters end in the 340 days up to its end
EPS_ZERO_MIN = 0.01                      # EPS 0 as filed while net income / shares is at least this: a placeholder
TTM_SHARES_MAX = 1.8                     # history_problem's limit: four quarters whose counts differ more add up
                                         # to no per-share figure
SPIN_SIDE_DAYS = 182                     # a fiscal year ending more than this after a spin-off is the company after it
DELIST_GAP_DAYS = 10                     # bars ending this long before the snapshot's last day: delisted
SPIN_MOVE = 0.20                         # one-day moves beyond this, off splits and earnings: spin-off candidates
BAND_OF = {"T": "T", "F": "F", "FY": "F"}
FIXES = Path(__file__).resolve().parent / "statement_fixes.json"    # the data review's corrections and exclusions


def day(x) -> dt.date:
    return dt.date.fromisoformat(str(x)[:10])


def read(path: Path) -> list:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("historical", [data])
    return data if isinstance(data, list) else []


def fnum(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- bars
def clean_bars(rows: list, adj_rows: list, split_rows: list) -> tuple[list, list, dict]:
    """V3's cleaning (ladder_sim.clean_bars): drop placeholder bars (no volume and open = high = low = close),
    non-positive closes and duplicate dates. A one-day move over 50% on bar i is verified when no split is
    within 5 bars, the dividend-adjusted series makes the same move and the close 5 bars later still holds half
    of it, a verdict first known at the close of bar i + 5. The flags are point in time, so no bar before the
    move is ever one (V3 also flagged the 40 bars before, which reads ahead): bars i + 5 to i + 40 are
    suspicious when the move failed the verdict, and a bar t from i to i + 4 when what is known at its close
    already fails it (the dividend-adjusted series disagrees, a split row within 5 bars of i is on or before t,
    or the close at t holds less than half of the move).
    Returns (bars oldest first as dicts with date/o/h/l/c/v, suspicious flags, report)."""
    by_day = {}
    for r in rows:
        o, h, l, c = (fnum(r.get(k)) for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c) or c <= 0:
            continue
        by_day[str(r["date"])[:10]] = {"date": str(r["date"])[:10], "o": o, "h": h, "l": l, "c": c,
                                       "v": fnum(r.get("volume")) or 0.0}
    bars, dropped = [], 0
    for d in sorted(by_day):
        b = by_day[d]
        if b["v"] == 0 and b["o"] == b["h"] == b["l"] == b["c"]:
            dropped += 1
            continue
        bars.append(b)
    adj = {str(r["date"])[:10]: fnum(r.get("adjClose")) for r in adj_rows}
    split_days = sorted(str(r["date"])[:10] for r in split_rows if r.get("date"))
    dates = [b["date"] for b in bars]
    split_idx = [bisect.bisect_left(dates, s) for s in split_days]
    n = len(bars)
    sus = [False] * n
    report = {"placeholders_removed": dropped, "jumps": []}
    for i in range(1, n):
        move = bars[i]["c"] / bars[i - 1]["c"]
        if abs(move - 1.0) <= 0.5:
            continue
        near = [j for j in split_idx if abs(j - i) <= 5]
        a0, a1 = adj.get(dates[i - 1]), adj.get(dates[i])
        adj_ok = bool(a0 and a1 and a0 > 0 and abs((a1 / a0) / move - 1.0) <= 0.05)
        held = lambda t: math.log(bars[t]["c"] / bars[i - 1]["c"]) / math.log(move) >= 0.5     # noqa: E731
        known = i + 5 < n                           # else the bars end before the verdict
        holds = held(i + 5) if known else None
        ok = (not near) and adj_ok and holds if known else None
        report["jumps"].append({"date": dates[i], "move": round(move - 1.0, 4), "near_split": bool(near),
                                "adjusted_agrees": adj_ok, "holds": holds, "verified": ok})
        for t in range(i, min(n, i + 5)):           # the verdict pending: what bar t's close knows
            if not adj_ok or any(j <= t for j in near) or not held(t):
                sus[t] = True
        if ok is False:
            for t in range(i + 5, min(n, i + 41)):
                sus[t] = True
    return bars, sus, report


def atr14(bars: list) -> list:
    """Wilder's ATR(14) as the technical skill computes it (indicators.atr): true range = max(high - low,
    |high - prev close|, |low - prev close|), high - low on the first bar; seeded with the mean of the first 14."""
    out = [None] * len(bars)
    tr = []
    for i, b in enumerate(bars):
        hl = b["h"] - b["l"]
        tr.append(hl if i == 0 else max(hl, abs(b["h"] - bars[i - 1]["c"]), abs(b["l"] - bars[i - 1]["c"])))
    if len(tr) < ATR_N:
        return out
    avg = sum(tr[:ATR_N]) / ATR_N
    out[ATR_N - 1] = avg
    for i in range(ATR_N, len(tr)):
        avg += (tr[i] - avg) / ATR_N
        out[i] = avg
    return out


def spin_candidates(bars: list, split_rows: list, earn_rows: list) -> list:
    """One-day moves beyond SPIN_MOVE that are not within 5 bars of a split or 2 bars of an earnings date: the
    prices are not adjusted for spin-offs, so a distribution shows as such a move. To be confirmed by eye."""
    dates = [b["date"] for b in bars]
    near = set()
    for s in split_rows:
        if s.get("date"):
            j = bisect.bisect_left(dates, str(s["date"])[:10])
            near.update(range(j - 5, j + 6))
    for e in earn_rows:
        if e.get("date"):
            j = bisect.bisect_left(dates, str(e["date"])[:10])
            near.update(range(j - 2, j + 3))
    out = []
    for i in range(1, len(bars)):
        move = bars[i]["c"] / bars[i - 1]["c"] - 1.0
        if abs(move) > SPIN_MOVE and i not in near:
            out.append({"date": dates[i], "move": round(move, 4)})
    return out


# ---------------------------------------------------------------- statements
def known_day(r: dict) -> tuple[dt.date | None, bool]:
    """(the first day a statement row counts as known, whether that day is a placeholder)."""
    if not r.get("date"):
        return None, False
    end = day(r["date"])
    f = r.get("filingDate") or r.get("acceptedDate")
    if f:
        try:
            fd = day(f)
        except ValueError:
            fd = None
        if fd and fd >= end + dt.timedelta(days=MIN_FILE_DAYS):
            return fd, False
    return end + dt.timedelta(days=INCOME_LAG.get(str(r.get("period") or "FY").upper(), 90)), True


def split_factors(split_rows: list) -> list:
    """[(date, factor)] oldest first; factor = new shares per old share (4.0 for a 4-for-1 split)."""
    out = []
    for r in split_rows:
        num, den = fnum(r.get("numerator")), fnum(r.get("denominator"))
        if r.get("date") and num and den and num > 0 and den > 0:
            out.append((day(r["date"]), num / den))
    return sorted(out)


def _runs(factors: list) -> list:
    """Products of every run of consecutive factors."""
    return [math.prod(factors[a:b]) for a in range(len(factors)) for b in range(a + 1, len(factors) + 1)]


def _dated_runs(splits: list) -> list:
    """(product, split dates) of every run of consecutive splits [(date, factor)], in _runs' order."""
    return [(math.prod(f for _, f in splits[a:b]), [x for x, _ in splits[a:b]]) for a in range(len(splits))
            for b in range(a + 1, len(splits) + 1)]


def share_split(f: float) -> bool:
    """Whether a split row changes the share count: its factor times a whole number from 1 to 20 is a whole
    number (2-for-1, 3-for-2, 1-for-4, a 5% stock dividend's 21/20). FMP also books a spin-off's price
    adjustment as a split (759/500 for Xerox's spin-off of Conduent in 2017), and that changes no count."""
    return any(abs(f * k - round(f * k)) <= 1e-9 * f * k for k in range(1, 21))


def normalize_basis(rows: list, splits: list, report: dict, unclear: str = "keep", units: str = "keep",
                    eps_shares: str = "any") -> list:
    """Rows (each filing, with end / known / eps / shares / ni) on today's split basis, in four steps; every
    decision goes into report (a dict of lists) for review.
      0 share_units and eps_units (units="fix", the pilot's panels; status.py's frozen rule keeps the rows as
        filed). A share count within a factor 1.5 of 1000, 10^6, 1/1000 or 1/10^6 times the median count of the
        company's other rows known by its own day with period ends within two years is in the wrong unit and is
        put right; when its EPS x that count / NI is within 2% of 1, the EPS was figured on the wrong count and
        is put right with it (both decided on the rows as filed). Then EPS x shares / NI within 2% of 1000 or
        1/1000 means one field is in the wrong unit. When the EPS is also 100
        times off the median EPS of the company's other rows within two years, the EPS is the wrong field and
        becomes NI / shares; otherwise the net income is, and nothing changes (only the EPS is used).
      1 eps_shares: EPS x diluted shares / net income near the product F (or 1/F) of a run of splits means the
        EPS and share fields of that row are on different bases (FMP restated one of them for the splits and
        not the other); the EPS is put on the shares' basis, and the fix is listed with the splits' dates. Only
        a split after the row was filed can do that (eps_shares="later", the pilot's panels: a ratio near the
        product of earlier splits is noncontrolling interests, preferred dividends or a rounded EPS); status.py's
        frozen rule takes every run of the company's splits (eps_shares="any"). Rows outside 0.6-1.6 otherwise
        are only listed (preferred dividends, two classes of stock).
      2 boundary, per split, newest first: the share count of the last row filed before the split against the
        first row filed on or after it (with a later period end). Near the factor: FMP did not restate, and
        every row filed before the split is put on the new basis; near 1: restated, nothing to do; otherwise
        unclear: listed, and the rows filed before the split are left as filed (unclear="keep", the reading
        status.py's frozen rule uses), lose their EPS (unclear="none", the annual rows of the panels: version
        F builds no band on a share basis that cannot be told), or are left as filed and marked with
        unclear_until, the day the first statement filed on or after the split became known (unclear="mark",
        the quarterly rows of the panels: version T leaves them out of every decision after that day, when a
        statement on the new basis is in use, and keeps them before it, when every statement in use is on the
        one old basis, so mid, percentile and the test against the mid do not depend on it; of two unclear
        splits after a row the older decides). With unclear="mark" the verdict must be known on that day, so
        a split whose test rests on a statement filed later, or on none yet, is unclear too (listed with
        verdict_known). Factors under 1.25 need the ratio within a quarter (not a half) of the log factor of
        either answer.
      3 partial: a step between consecutive period ends' share counts outside 0.8-1.25 that is within 10% of a
        product of splits dated after the older row's filing means FMP restated only the newer rows; the older
        ones are put on the new basis. Only splits that change the share count count here (share_split): FMP
        also books a spin-off's price adjustment as a split, and that restates no count. Other steps are listed
        (a merger, a spin-off) for history_problem. With
        unclear="mark" a split step 2 left unclear explains no step to a row filed on or after it: that row
        would decide the basis of rows version T uses as filed until the first statement after the split.
    """
    rows = sorted((dict(r) for r in rows), key=lambda r: (r["known"], r["end"]))
    for k in ("share_units", "eps_units", "eps_shares", "boundary", "partial", "share_steps", "review"):
        report.setdefault(k, [])
    if units == "fix":
        moved = []
        for r in rows:
            n = r["shares"]
            near = sorted(x["shares"] for x in rows if x is not r and x["shares"] and x["known"] <= r["known"]
                          and x["end"] != r["end"] and abs((x["end"] - r["end"]).days) <= UNIT_NEAR_DAYS)
            u = next((u for u in SHARE_UNITS if abs(math.log(n * u / near[len(near) // 2])) <= SHARE_UNIT_NEAR),
                     None) if n and n > 0 and near and near[len(near) // 2] > 0 else None
            if u:
                e, ni = r["eps"], r.get("ni")
                moved.append((r, u, bool(e and ni and e * ni > 0 and abs(math.log(e * n / ni)) <= 0.02)))
        for r, u, with_eps in moved:             # decided on the rows as filed, then applied
            report["share_units"].append({"end": r["end"].isoformat(), "shares": r["shares"], "now": r["shares"] * u,
                                          "eps": r["eps"], "eps_now": r["eps"] / u if with_eps else r["eps"]})
            r["shares"] *= u
            if with_eps:
                r["eps"] /= u
        fixes = []
        for r in rows:
            e, n, ni = r["eps"], r["shares"], r.get("ni")
            if not (e and n and ni) or e * ni <= 0 or abs(abs(math.log(e * n / ni)) - math.log(UNIT_SLIP)) > 0.02:
                continue
            near = sorted(abs(x["eps"]) for x in rows if x is not r and x["eps"] and x["end"] != r["end"]
                          and abs((x["end"] - r["end"]).days) <= UNIT_NEAR_DAYS)
            if near and abs(math.log(abs(e) / near[len(near) // 2])) > UNIT_OFF:
                fixes.append((r, ni / n))
        for r, new in fixes:                     # decided on the rows as filed, then applied
            report["eps_units"].append({"end": r["end"].isoformat(), "eps": r["eps"], "now": round(new, 6)})
            r["eps"] = new
    def big(sp):
        return [(F, xs) for F, xs in _dated_runs(sp) if abs(math.log(F)) >= math.log(1.4)]
    every = big(splits)
    for r in rows:
        e, n, ni = r["eps"], r["shares"], r.get("ni")
        if not (e and n and ni) or e * ni <= 0:
            continue
        c = e * n / ni
        runs = every if eps_shares == "any" else big([(x, f) for x, f in splits if x > r["known"]])
        hit = next(((F, xs) for F, xs in runs + [(1 / F, xs) for F, xs in runs] if abs(c / F - 1.0) <= 0.10), None)
        if hit:
            report["eps_shares"].append({"end": r["end"].isoformat(), "ratio": round(c, 3),
                                         "fixed_by": round(hit[0], 4), "splits": [x.isoformat() for x in hit[1]]})
            r["eps"] = e / hit[0]
        elif not EPS_SHARES_OK[0] <= c <= EPS_SHARES_OK[1]:
            report["review"].append({"end": r["end"].isoformat(), "eps_x_shares_over_ni": round(c, 3)})
    mult, left = [1.0] * len(rows), set()          # left: the splits "mark" leaves unclear
    for x, f in sorted(splits, reverse=True):
        lf = abs(math.log(f))
        if lf < SPLIT_MIN:
            continue
        pre = [k for k, r in enumerate(rows) if r["known"] < x and r["shares"]]
        if not pre:
            continue
        kp = pre[-1]
        post = [k for k, r in enumerate(rows) if r["known"] >= x and r["shares"] and r["end"] > rows[kp]["end"]]
        first = min((r["known"] for r in rows if r["known"] >= x), default=None)
        # "mark" ends the old rows' use on the day the first statement after the split is known: a verdict from
        # a statement filed later (or from none yet) is not known then, so the split is unclear
        late = unclear == "mark" and first is not None and (not post or rows[post[0]]["known"] > first)
        if not post and not late:
            report["boundary"].append({"split": x.isoformat(), "factor": f, "action": "no row after"})
            continue
        kq = post[0] if post else None
        ratio = rows[kq]["shares"] * mult[kq] / (rows[kp]["shares"] * mult[kp]) if post else None
        tol = (0.5 if lf >= SPLIT_WEAK else 0.25) * lf
        if not late and abs(math.log(ratio / f)) < tol:
            action = "not_restated"
            for k, r in enumerate(rows):
                if r["known"] < x:
                    mult[k] *= f
        elif not late and abs(math.log(ratio)) < tol:
            action = "restated"
        else:
            action = "unclear"
            if unclear == "none":
                for r in rows:
                    if r["known"] < x and r["eps"] is not None:
                        r["eps"], r["eps_unclear"] = None, x.isoformat()
            elif unclear == "mark":
                left.add(x)
                for r in rows:                      # splits run newest first: the oldest one after a row wins
                    if r["known"] < x:
                        r["unclear_until"] = first
        entry = {"split": x.isoformat(), "factor": f, "pre_end": rows[kp]["end"].isoformat(),
                 "post_end": rows[kq]["end"].isoformat() if post else None,
                 "ratio": round(ratio, 4) if post else None, "action": action,
                 "rows_changed": sum(r["known"] < x for r in rows)
                 if action == "not_restated" or (action == "unclear" and unclear in ("none", "mark")) else 0}
        if action == "unclear" and unclear == "mark":
            entry["unused_after"] = first.isoformat()
        if late:
            entry["verdict_known"] = rows[kq]["known"].isoformat() if post else None
        report["boundary"].append(entry)
    latest = {}
    for k, r in enumerate(rows):
        if r["shares"]:
            latest[r["end"]] = k
    ends = sorted(latest)
    for a, b in reversed(list(zip(ends, ends[1:]))):
        ka, kb = latest[a], latest[b]
        ratio = rows[kb]["shares"] * mult[kb] / (rows[ka]["shares"] * mult[ka])
        if STEP_BAND[0] <= ratio <= STEP_BAND[1]:
            continue
        later = [f for x, f in splits if x > rows[ka]["known"] and abs(math.log(f)) >= SPLIT_MIN and share_split(f)
                 and not (x in left and rows[kb]["known"] >= x)]
        hit = next((F for F in _runs(later) if abs(ratio / F - 1.0) <= 0.10), None)
        if hit:
            for k, r in enumerate(rows):
                if r["end"] <= a:
                    mult[k] *= hit
            report["partial"].append({"older_end": a.isoformat(), "newer_end": b.isoformat(),
                                      "ratio": round(ratio, 4), "factor": round(hit, 4)})
        else:
            report["share_steps"].append({"older_end": a.isoformat(), "newer_end": b.isoformat(),
                                          "ratio": round(ratio, 4)})
    for k, r in enumerate(rows):
        if mult[k] != 1.0:
            r["shares"] = r["shares"] * mult[k] if r["shares"] else r["shares"]
            r["eps"] = r["eps"] / mult[k] if r["eps"] is not None else None
            r["basis_factor"] = mult[k]
    return rows


def statement_rows(raw: list, splits: list, report: dict, unclear: str = "keep", units: str = "keep",
                   eps_shares: str = "any") -> list:
    """Income rows -> [{end, known, placeholder, period, eps, shares, ni}], every filing kept, oldest known
    first, on today's split basis (unclear, units, eps_shares: see normalize_basis)."""
    out, seen = [], set()
    for r in raw:
        if not r.get("date"):
            continue
        k, ph = known_day(r)
        row = {"end": day(r["date"]), "known": k, "placeholder": ph, "period": str(r.get("period") or "FY").upper(),
               "eps": fnum(r.get("epsDiluted", r.get("epsdiluted", r.get("eps")))),
               "shares": fnum(r.get("weightedAverageShsOutDil")) or fnum(r.get("weightedAverageShsOut")),
               "ni": fnum(r.get("netIncome")), "raw": r}
        key = (row["end"], row["known"], row["eps"], row["shares"])
        if key not in seen:
            seen.add(key)
            out.append(row)
    report["placeholders"] = sum(r["placeholder"] for r in out)
    report["rows"] = len(out)
    return normalize_basis(out, splits, report, unclear, units, eps_shares)


def fixes_of(symbol: str, path: Path = FIXES) -> dict:
    """The data review's entries for one company in statement_fixes.json: "rows", corrections of FMP statement
    rows, and "exclude", spans of days with no band of a version."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("companies", {}).get(symbol, {})


def statements(snap: Path, symbol: str, kind: str, fixes: dict, report: dict | None = None) -> list:
    """The company's statement rows of one kind (inc_q, inc_a) as the snapshot has them, with the data review's
    corrections applied: an entry of fixes["rows"] names a row by kind, period end and filing date and gives the
    fields that replace FMP's (the evidence is in the file). Every change goes into report["fixes"], with the
    number of rows the entry named (one, when the entry is right)."""
    todo = [f for f in fixes.get("rows", []) if f["kind"] == kind]
    hits = [0] * len(todo)
    out = []
    for r in read(snap / "raw" / kind / f"{symbol}.json"):
        k = next((i for i, f in enumerate(todo) if str(r.get("date"))[:10] == f["date"]
                  and str(r.get("filingDate"))[:10] == f["filed"]), None)
        if k is not None:
            hits[k] += 1
            r = dict(r, **todo[k]["set"])
        out.append(r)
    if report is not None:
        report.setdefault("fixes", []).extend(
            {"kind": kind, "date": f["date"], "filed": f["filed"], "set": f["set"], "rows": h} for f, h in zip(todo, hits))
    return out


def latest_by_end(rows: list, before: dt.date | None = None) -> list:
    """One row per period end, the latest filing (known before `before` when given), oldest end first."""
    best = {}
    for r in rows:
        if before is not None and not (r["known"] and r["known"] < before):
            continue
        if r["end"] not in best or r["known"] >= best[r["end"]]["known"]:
            best[r["end"]] = r
    return [best[e] for e in sorted(best)]


def _filed_eps(r: dict):
    return fnum(r["raw"].get("epsDiluted", r["raw"].get("epsdiluted", r["raw"].get("eps"))))


def from_the_year(quarters: list, years: list, report: dict) -> list:
    """Two kinds of FMP quarterly rows that hold no quarter, put right from the fiscal year after the split
    basis (so on today's): a row that repeats its fiscal year (its period end is the year's, its net income the
    year's to within 0.1% and its EPS as filed the year's to within 2%, by an annual row known by the row's own
    day), and a zero-EPS placeholder (diluted and basic EPS both 0 as filed while net income / diluted shares
    is at least 0.01 in size: FMP's derived Q4 of some companies). Its EPS becomes the year's less those of the
    year's three earlier quarters, the latest filing of each known by the row's own day (the four period ends
    within 340 days, as annual_check), and None when they are not all known then; a placeholder with no annual
    row of its period end known by then (or one with no EPS) gets the bottom-line net income / its diluted
    shares instead. A repeating row's net income is put right the same way. Every change is listed in
    report["from_year"]."""
    report.setdefault("from_year", [])
    out = []
    for q in quarters:
        raw, e0 = q["raw"], _filed_eps(q)
        same = [y for y in years if y["end"] == q["end"] and y["known"] and q["known"] and y["known"] <= q["known"]]
        repeat = q["eps"] is not None and q["ni"] and any(
            y["ni"] and abs(q["ni"] / y["ni"] - 1.0) < 1e-3 and e0 and _filed_eps(y) and
            abs(e0 / _filed_eps(y) - 1.0) <= 0.02 for y in same)
        b = fnum(raw.get("bottomLineNetIncome")) or q["ni"]
        zero = e0 == 0 and fnum(raw.get("eps")) == 0 and bool(b and q["shares"]) and abs(b / q["shares"]) >= EPS_ZERO_MIN
        if not (repeat or zero):
            out.append(q)
            continue
        prev = latest_by_end([r for r in quarters if q["end"] - dt.timedelta(days=YEAR_DAYS) < r["end"] < q["end"]
                              and r["eps"] is not None and r["ni"] is not None],
                             before=q["known"] + dt.timedelta(days=1))
        year = max((y for y in same if y["eps"] is not None), key=lambda y: y["known"], default=None)
        new = dict(q, eps=None, from_year="repeat" if repeat else "zero")
        if repeat:
            new["ni"] = None
            if len(prev) == 3:
                new["eps"] = q["eps"] - sum(r["eps"] for r in prev)
                new["ni"] = q["ni"] - sum(r["ni"] for r in prev)
        elif year is None:
            new["eps"] = b / q["shares"]
        elif len(prev) == 3:
            new["eps"] = year["eps"] - sum(r["eps"] for r in prev)
        report["from_year"].append({"end": q["end"].isoformat(), "known": q["known"].isoformat(), "kind": new["from_year"],
                                    "eps": q["eps"], "now": None if new["eps"] is None else round(new["eps"], 6),
                                    "quarters": [r["end"].isoformat() for r in prev]})
        out.append(new)
    return out


def annual_check(years: list, quarters: list) -> list:
    """Fiscal-year EPS against the sum of its four quarters (latest filings), the quarters ending in the 340 days
    up to the year's end (the first ends about 273, the year before about 364 days earlier, 52/53-week years
    included): a ratio near a split factor marks a basis error the steps above missed."""
    out = []
    qs = latest_by_end(quarters)
    for y in latest_by_end(years):
        inside = [q for q in qs if y["end"] - dt.timedelta(days=YEAR_DAYS) < q["end"] <= y["end"] and q["eps"] is not None]
        if len(inside) == 4 and y["eps"] and sum(q["eps"] for q in inside):
            ratio = y["eps"] / sum(q["eps"] for q in inside)
            if not 0.9 <= ratio <= 1.1:
                out.append({"fy_end": y["end"].isoformat(), "fy_eps": y["eps"], "ratio": round(ratio, 3)})
    return out


# ---------------------------------------------------------------- EPS versions
def ttm_steps(quarters: list, shares_max: float | None = None) -> tuple[list, list]:
    """Version T as a step function: (days, values), values[i] = (TTM EPS or None, newest period end summed)
    once everything filed by days[i] is known; None when the latest four known quarters are not consecutive, or
    (shares_max: build passes TTM_SHARES_MAX) when their diluted counts differ by more than that, history_problem's
    limit between two counts (a recapitalization, an IPO, a merger paid in shares: EPS on such different counts
    add up to no per-share figure). status.py's U2, frozen before the data, reads it without the guard."""
    events = sorted(((q["known"], q["end"], q) for q in quarters if q["known"] and q["eps"] is not None),
                    key=lambda e: e[:2])                     # two filings of one quarter on one day: file order
    days, vals, seen = [], [], {}
    i = 0
    while i < len(events):
        d = events[i][0]
        while i < len(events) and events[i][0] == d:
            seen[events[i][1]] = events[i][2]                 # the latest filing known by then wins
            i += 1
        v, newest = None, None
        if len(seen) >= 4:
            last4 = sorted(seen)[-4:]
            newest = last4[-1]
            sh = [seen[e]["shares"] for e in last4]
            if (last4[-1] - last4[0]).days <= TTM_SPAN and not (shares_max and all(sh) and max(sh) > shares_max * min(sh)):
                v = sum(seen[e]["eps"] for e in last4)
        days.append(d)
        vals.append((v, newest))
    return days, vals


def step_at(days: list, vals: list, d: dt.date, strict: bool = True):
    """Value of a step function on day d; strict: only what was known BEFORE d (filed on or before d - 1)."""
    i = (bisect.bisect_left(days, d) if strict else bisect.bisect_right(days, d)) - 1
    return vals[i] if i >= 0 else None


def ttm_at(days: list, vals: list, d: dt.date) -> tuple:
    """(TTM EPS known before d or None, why missing)."""
    s = step_at(days, vals, d)
    if s is None or s[0] is None:
        return None, "eps_unknown"
    if (d - s[1]).days > TTM_STALE_DAYS:
        return None, "eps_stale"
    return s[0], None


def fiscal_eps(years: list):
    """(F as day_iso -> NTM EPS, FY as day_iso -> this fiscal year's EPS, F's last day) from the latest
    filing of every fiscal year in the snapshot (the look-ahead is the point of F)."""
    fys = [(y["end"].isoformat(), y["eps"]) for y in latest_by_end(years) if y["eps"] is not None]
    ntm = A._ntm(fys) if fys else (lambda d: None)
    keys = [d for d, _ in fys]
    horizon = keys[-2] if len(keys) >= 2 else None

    def this_year(d):
        i = bisect.bisect_left(keys, d)
        if i >= len(keys) or (dt.date.fromisoformat(keys[i]) - dt.date.fromisoformat(d)).days > 400:
            return None
        return fys[i][1]
    return ntm, this_year, horizon


# ---------------------------------------------------------------- the panel
@dataclass
class Panel:
    symbol: str
    dates: list                    # ISO strings, trading days of the cleaned bars
    o: list
    h: list
    l: list
    c: list
    div: list                      # split-adjusted dividend per share going ex on this bar (before the open)
    atr: list
    member: list
    suspicious: list
    delisted: bool
    eps: dict = field(default_factory=dict)       # version -> list of EPS(d) or None
    band: dict = field(default_factory=dict)      # band version -> list of None | {p25, median, p75, pct, n}
    why: dict = field(default_factory=dict)       # version -> list of the reason a range is missing
    no_new: dict = field(default_factory=dict)    # version -> list of True on days no new plan may start
    spin_exit: set = field(default_factory=set)   # bars whose close is the last before a confirmed spin-off
    report: dict = field(default_factory=dict)
    epochs: dict = field(default_factory=dict)    # version -> [(last day or None, EPS on every bar)]: see build

    def window_eps(self, v: str, i: int) -> list:
        """The EPS on every bar that day i's band divides the closes by: version T's of the epoch day i falls in
        (statements an unclear split takes out of use are out of the whole window), else the days' own."""
        for until, e in self.epochs.get(v, []):
            if until is None or self.dates[i] <= until:
                return e
        return self.eps[v]

    def range_at(self, v: str, i: int):
        """(low, mid, high, pct) on bar i for version v, or None."""
        b, e = self.band[BAND_OF.get(v, v)][i], self.eps[v][i]
        if b is None or not e or e <= 0:
            return None
        return e * b["p25"], e * b["median"], e * b["p75"], b["pct"]

    def can_start(self, v: str, i: int) -> bool:
        """A member day that is not a suspicious bar (clean_bars), not the last close before a confirmed spin-off
        (its first buy would fill after the distribution) and not in the blackout after one."""
        return self.member[i] and not self.suspicious[i] and i not in self.spin_exit and \
            not (self.no_new.get(v) and self.no_new[v][i])


def in_spans(d: str, spans: list) -> bool:
    return any(a <= d < b for a, b in spans)


def t_years(years: list, rep: dict, until: str | None) -> list:
    """The fiscal years version T's share check (history_problem) reads on the days up to until, the end of one
    of T's epochs (None: after the last one). While the quarters filed before an unclear quarterly split are in
    use as filed, the fiscal years filed before it are read as filed too: the factor an annual not_restated
    verdict put on their share counts is taken off. That verdict comes from statements filed after the split,
    and so then decides nothing on the days before them. A fiscal year filed on or after the split is left out
    until then: its counts are on the new basis, and whether the quarters in use are too is what the quarterly
    test, known only at the epoch's end, would tell."""
    if until is None:
        return years
    ann = {b["split"]: b["action"] for b in rep["basis_a"].get("boundary", [])}
    undo = [(day(b["split"]), b["factor"]) for b in rep["basis_q"].get("boundary", [])
            if b.get("unused_after") and b["unused_after"] >= until and ann.get(b["split"]) == "not_restated"]
    if not undo:
        return years
    return [dict(y, shares=y["shares"] / math.prod(f for x, f in undo if y["known"] < x)) if y["shares"] else y
            for y in years if not any(y["known"] >= x for x, _ in undo)]


def build(symbol: str, snap: Path, spans: list, versions=("T", "F", "FY"), snapshot_end: str | None = None,
          first_day: str = "2007-12-01", truncate: str | None = None, spinoffs: list = (),
          audit_known=None, fixes: dict | None = None) -> Panel:
    """The panel of one company. truncate: drop every bar and dividend dated after this day and every statement
    known on or after it, for the self-test that nothing on or before it changes (T at a close uses only
    statements known before that day, so a leak of even one day shows at a cut on a filing day);
    audit_known(raw row) -> (day, placeholder) decides which statements survive the cut when given (the test's
    own reading of the filing dates, so a leak in known_day shows); the bars are cleaned from the rows dated on or
    before it alone, so the suspicious flags must not read ahead either. The split basis is
    settled on the full data first: putting old statements on today's share basis is a change of units that a
    later split forces, not information about what came after (prices are on today's basis too). Quarterly
    statements filed before a split whose basis cannot be told leave version T on the first day a statement
    filed after the split is in use: from there on T has its own epoch, with the TTM of every day, the window
    of the band included, and the share check's latest quarter taken without them (normalize_basis,
    unclear="mark"); before it T's share check reads the fiscal years as filed too (t_years). A truncated build
    drops the marks of the statements the cut removed, so its epochs are the ones the data before the cut give.
    Version F's share check reads the quarterly counts with every boundary decided on the full data
    (unclear="none"), as its fiscal years are.
    spinoffs: confirmed spin-off ex-dates; no new T plan for 365 days after one (the trailing EPS still holds
    the unit the price no longer does), no new F / FY plan until the end of that fiscal year, and a holding is
    sold at the last close before the ex-date (the bars drop by the spun-off value, which they do not credit).
    Those spans have no band either, and after them each version's band window starts again, holding no day
    from before (SPEC amendment 29: FMP adjusts the prices before most ex-dates by a split row and not the
    statements, so P/E days on both sides of one are on two scales); F has no EPS on the days before an ex-date
    whose blend weights a fiscal year ending more than 182 days after it (the company after the spin-off,
    against prices that are the company before it, or on the other scale).
    fixes: the data review's corrections of statement rows and spans with no band (statements, fixes_of;
    statement_fixes.json by default). The statement rows that hold no quarter (from_the_year) are put right
    before anything reads the quarters."""
    raw = snap / "raw"
    fixes = fixes_of(symbol) if fixes is None else fixes
    split_rows = read(raw / "splits" / f"{symbol}.json")
    splits = split_factors(split_rows)
    full_rows, adj_rows = read(raw / "full" / f"{symbol}.json"), read(raw / "adj" / f"{symbol}.json")
    if truncate:
        upto = lambda rs: [r for r in rs if str(r.get("date"))[:10] <= truncate]       # noqa: E731
        bars, sus, clean = clean_bars(upto(full_rows), upto(adj_rows), upto(split_rows))
    else:
        bars, sus, clean = clean_bars(full_rows, adj_rows, split_rows)
    divs = read(raw / "div" / f"{symbol}.json")
    rep = {"clean": clean, "basis_q": {}, "basis_a": {}}
    q_raw = statements(snap, symbol, "inc_q", fixes, rep)
    quarters = statement_rows(q_raw, splits, rep["basis_q"], unclear="mark", units="fix", eps_shares="later")
    years = statement_rows(statements(snap, symbol, "inc_a", fixes, rep), splits, rep["basis_a"], unclear="none",
                           units="fix", eps_shares="later")
    quarters = from_the_year(quarters, years, rep["basis_q"])
    # F's share check reads the quarters' counts with every boundary decided on the full data, as F's own
    # fiscal years are (F looks ahead by design); T's reads the statements of its epoch
    quarters_f = statement_rows(q_raw, splits, {}, unclear="none", units="fix", eps_shares="later")
    rep["annual_vs_quarters"] = annual_check(years, quarters)
    rep["spin_candidates"] = spin_candidates(bars, split_rows, read(raw / "earn" / f"{symbol}.json"))
    if truncate:
        divs = [r for r in divs if str(r.get("date"))[:10] <= truncate]
        cut = day(truncate)
        def kept(r):
            k = audit_known(r["raw"])[0] if audit_known else r["known"]
            return k is not None and k < cut
        quarters = [q for q in quarters if kept(q)]
        for q in quarters:                  # a mark is the day of a statement after a split the cut removed
            if q.get("unclear_until") and q["unclear_until"] >= cut:
                del q["unclear_until"]
        years = [y for y in years if kept(y)]
        quarters_f = [q for q in quarters_f if kept(q)]
    dates = [b["date"] for b in bars]
    div_on = {}
    for r in divs:
        amt = fnum(r.get("adjDividend")) or fnum(r.get("dividend"))
        if amt and r.get("date"):
            div_on[str(r["date"])[:10]] = div_on.get(str(r["date"])[:10], 0.0) + amt
    div = [0.0] * len(dates)
    for d, amt in div_on.items():                 # an ex-date on a non-trading day goes to the next bar
        i = bisect.bisect_left(dates, d)
        if i < len(dates):
            div[i] += amt
    end = snapshot_end or (dates[-1] if dates else None)
    p = Panel(symbol, dates, [b["o"] for b in bars], [b["h"] for b in bars], [b["l"] for b in bars],
              [b["c"] for b in bars], div, atr14(bars), [in_spans(d, spans) for d in dates], sus,
              bool(dates) and (day(end) - day(dates[-1])).days > DELIST_GAP_DAYS, report=rep)
    ntm_f, fy_eps, horizon = fiscal_eps(years)
    # the skill's history check reads 'shares' and 'date' of the fiscal years; on day d only the years filed by d - 1
    def counts(qs):
        return sorted((q["known"], q["end"], q["shares"]) for q in qs if q["known"] and q["shares"])
    eps, why_eps, t_epochs, t_of = {}, {}, [], []
    if "T" in versions:
        # epoch k runs to ends[k] (the last one to the end): the statements in use are those whose unclear_until
        # is not before that day, for the TTM and the share check alike
        ends = sorted({q["unclear_until"] for q in quarters if q.get("unclear_until")})
        for k in range(len(ends) + 1):
            until = ends[k] if k < len(ends) else None
            used = [q for q in quarters if not q.get("unclear_until") or
                    (until is not None and q["unclear_until"] >= until)]
            t_days, t_vals = ttm_steps(used, TTM_SHARES_MAX)
            t = [ttm_at(t_days, t_vals, day(d)) for d in dates]
            t_epochs.append((None if until is None else until.isoformat(), [x[0] for x in t], [x[1] for x in t],
                             counts(used)))
        t_of = [next(k for k, e in enumerate(t_epochs) if e[0] is None or d <= e[0]) for d in dates]
        eps["T"] = [t_epochs[k][1][i] for i, k in enumerate(t_of)]
        why_eps["T"] = [t_epochs[k][2][i] for i, k in enumerate(t_of)]
        p.epochs["T"] = [(u, e) for u, e, _, _ in t_epochs]
    fy_ends = [y["end"].isoformat() for y in latest_by_end(years)]
    spins = sorted(str(x)[:10] for x in spinoffs)

    def stop_of(x, v):                    # the last day of the span after the spin-off x with no new plan
        if v == "T":
            return (day(x) + dt.timedelta(days=365)).isoformat()
        j = bisect.bisect_left(fy_ends, x)
        return fy_ends[j] if j < len(fy_ends) else "9999-12-31"

    def restart(x, v):                    # the first day of the band window after it
        s = stop_of(x, v)
        return s if s >= "9999" else (day(s) + dt.timedelta(days=1)).isoformat()
    if "F" in versions or "FY" in versions:
        eps["F"] = [ntm_f(d) for d in dates]
        why_eps["F"] = [None if e is not None else "beyond_horizon" if horizon is None or d > horizon
                        else "eps_not_positive_or_gap" for d, e in zip(dates, eps["F"])]
        keys = [y["end"].isoformat() for y in latest_by_end(years) if y["eps"] is not None]    # what F blends
        for x in spins:
            after = (day(x) + dt.timedelta(days=SPIN_SIDE_DAYS)).isoformat()
            for i in range(bisect.bisect_left(dates, x)):
                if eps["F"][i] is None:
                    continue
                j = bisect.bisect_left(keys, dates[i])            # _ntm's years: the one in progress, the next
                w = min((day(keys[j]) - day(dates[i])).days / 365.25, 1.0)
                if (w > 0 and keys[j] > after) or (w < 1 and keys[j + 1] > after):
                    eps["F"][i], why_eps["F"][i] = None, "spin_ntm"
    if "FY" in versions:
        eps["FY"] = [fy_eps(d) if f is not None else None for d, f in zip(dates, eps["F"])]
    for v in versions:
        p.eps[v] = eps[v]
    for bv in sorted({BAND_OF[v] for v in versions}):
        # an exclusion of the data review starts the window again the day after it, as a spin-off's span does
        resets = [(x, restart(x, bv)) for x in spins] + \
            [(ex["from"], (day(ex["to"]) + dt.timedelta(days=1)).isoformat())
             for ex in fixes.get("exclude", []) if ex["version"] == bv]
        if bv == "T":
            # by epoch, with the fiscal years as T reads them up to the epoch's end (the last epoch of a
            # truncated build ends at the cut)
            each = [bands(dates, p.c, e, w, t_years(years, rep, u or truncate), qs, first_day, resets)
                    for u, e, w, qs in t_epochs]
            p.band[bv] = [each[k][0][i] for i, k in enumerate(t_of)]
            p.why[bv] = [each[k][1][i] for i, k in enumerate(t_of)]
        else:
            p.band[bv], p.why[bv] = bands(dates, p.c, eps[bv], why_eps[bv], years, counts(quarters_f), first_day,
                                          resets)
        for ex in fixes.get("exclude", []):                      # the data review's spans with no band
            if ex["version"] == bv:
                for i in range(bisect.bisect_left(dates, ex["from"]), bisect.bisect_right(dates, ex["to"])):
                    p.band[bv][i], p.why[bv][i] = None, "data_review"
    if "FY" in versions:
        p.why["FY"] = [w if w else (None if e and e > 0 else "eps_not_positive") for w, e in zip(p.why["F"], eps["FY"])]
    for v in versions:
        block = [False] * len(dates)
        for x in spins:
            for i in range(bisect.bisect_left(dates, x), bisect.bisect_right(dates, stop_of(x, BAND_OF[v]))):
                block[i] = True
        p.no_new[v] = block
    for x in spinoffs:                            # a holding is sold at the last close before the ex-date
        i = bisect.bisect_left(dates, str(x)[:10])
        if 0 < i < len(dates):
            p.spin_exit.add(i - 1)
    rep["f_horizon"] = horizon
    return p


def bands(dates: list, close: list, eps: list, why_eps: list, years: list, q_shares: list, first_day: str,
          resets: list = ()):
    """The skill's 3-year P/E band on every day from first_day on (None before, or with the reason). resets:
    [(x, start)] (ISO days): from x to the day before start no band (spin_reset), and from start on the P/E days
    of the band hold no day before start (build: a confirmed spin-off, and the data review's exclusion, whose own
    days build then marks data_review); the latest start of those with x on or before the day holds, and the
    history checks keep the whole window."""
    n = len(dates)
    out, why = [None] * n, [None] * n
    resets = sorted(resets)
    pe = [close[i] / eps[i] if eps[i] and eps[i] > 0 else None for i in range(n)]
    # history_problem's price check (a one-day move outside 0.5-2x inside the window) as a running count, so
    # the skill's function only has to do its share-basis check each day; the order of the two checks is kept
    bad = [0] * n
    for j in range(1, n):
        bad[j] = bad[j - 1] + (not 0.5 <= close[j] / close[j - 1] <= 2.0)
    lo = 0
    for i in range(n):
        if dates[i] < first_day:
            why[i] = "before the test window"
            continue
        d = day(dates[i])
        start = (d - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
        while dates[lo] < start:
            lo += 1
        r = max((s for x, s in resets if x <= dates[i]), default=None)       # the latest restart
        if r is not None and dates[i] < r:
            why[i] = "spin_reset"
            continue
        known_years = [{"date": y["end"].isoformat(), "shares": y["shares"]} for y in latest_by_end(years, d)] \
            if years else []
        k = bisect.bisect_left(q_shares, (d,)) - 1
        cur_shares = q_shares[k][-1] if k >= 0 else None             # the latest period known before d
        code, _ = A.history_problem(known_years, [], start, cur_shares)
        if not code and bad[i] - bad[lo] > 0:
            code = "price_jump"
        if code:
            why[i] = code
            continue
        lo2 = lo if r is None else max(lo, bisect.bisect_left(dates, r))
        window = [(dates[lo2], close[lo2]), (dates[i], close[i])]        # _band reads only its ends
        if not eps[i] or eps[i] <= 0:
            why[i] = why_eps[i] or "eps_not_positive"
            continue
        vals = [pe[j] for j in range(lo2, i + 1) if pe[j] is not None]
        if len(vals) < MIN_BAND_DAYS:
            why[i] = "short_history"
            continue
        b = A._band(vals, window, pe[i])
        out[i] = {"p25": b["p25"], "median": b["median"], "p75": b["p75"], "pct": b["now_pct"], "n": b["n"]}
    return out, why
