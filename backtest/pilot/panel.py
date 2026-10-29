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
DELIST_GAP_DAYS = 10                     # bars ending this long before the snapshot's last day: delisted
SPIN_MOVE = 0.20                         # one-day moves beyond this, off splits and earnings: spin-off candidates
BAND_OF = {"T": "T", "F": "F", "FY": "F"}


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
    non-positive closes and duplicate dates; a one-day move over 50% that is not near a split, not matched by
    the dividend-adjusted series or reversed within 5 bars marks the 40 bars on either side as suspicious.
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
        near_split = any(abs(j - i) <= 5 for j in split_idx)
        a0, a1 = adj.get(dates[i - 1]), adj.get(dates[i])
        adj_ok = bool(a0 and a1 and a0 > 0 and abs((a1 / a0) / move - 1.0) <= 0.05)
        holds = math.log(bars[min(i + 5, n - 1)]["c"] / bars[i - 1]["c"]) / math.log(move) >= 0.5 if i + 5 < n else True
        ok = (not near_split) and adj_ok and holds
        report["jumps"].append({"date": dates[i], "move": round(move - 1.0, 4), "near_split": near_split,
                                "adjusted_agrees": adj_ok, "holds": holds, "verified": ok})
        if not ok:
            for j in range(max(0, i - 40), min(n, i + 41)):
                sus[j] = True
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


def normalize_basis(rows: list, splits: list, report: dict) -> list:
    """Rows (each filing, with end / known / eps / shares / ni) on today's split basis, in four steps; every
    decision goes into report (a dict of lists) for review.
      1 eps_shares: EPS x diluted shares / net income near a split product F (or 1/F) means the EPS and share
        fields of that row are on different bases; the EPS is put on the shares' basis. Rows outside 0.6-1.6
        otherwise are only listed (preferred dividends, two classes of stock).
      2 boundary, per split, newest first: the share count of the last row filed before the split against the
        first row filed on or after it (with a later period end). Near the factor: FMP did not restate, and
        every row filed before the split is put on the new basis; near 1: restated, nothing to do; otherwise
        unclear (listed, left as is). Factors under 1.25 need the ratio within a quarter (not a half) of the
        log factor of either answer.
      3 partial: a step between consecutive period ends' share counts outside 0.8-1.25 that is within 10% of a
        product of splits dated after the older row's filing means FMP restated only the newer rows; the older
        ones are put on the new basis. Other steps are listed (a merger, a spin-off) for history_problem.
    """
    rows = sorted((dict(r) for r in rows), key=lambda r: (r["known"], r["end"]))
    for k in ("eps_shares", "boundary", "partial", "share_steps", "review"):
        report.setdefault(k, [])
    big = [F for F in _runs([f for _, f in splits]) if abs(math.log(F)) >= math.log(1.4)]
    for r in rows:
        e, n, ni = r["eps"], r["shares"], r.get("ni")
        if not (e and n and ni) or e * ni <= 0:
            continue
        c = e * n / ni
        hit = next((F for F in big + [1 / F for F in big] if abs(c / F - 1.0) <= 0.10), None)
        if hit:
            report["eps_shares"].append({"end": r["end"].isoformat(), "ratio": round(c, 3), "fixed_by": round(hit, 4)})
            r["eps"] = e / hit
        elif not EPS_SHARES_OK[0] <= c <= EPS_SHARES_OK[1]:
            report["review"].append({"end": r["end"].isoformat(), "eps_x_shares_over_ni": round(c, 3)})
    mult = [1.0] * len(rows)
    for x, f in sorted(splits, reverse=True):
        lf = abs(math.log(f))
        if lf < SPLIT_MIN:
            continue
        pre = [k for k, r in enumerate(rows) if r["known"] < x and r["shares"]]
        if not pre:
            continue
        kp = pre[-1]
        post = [k for k, r in enumerate(rows) if r["known"] >= x and r["shares"] and r["end"] > rows[kp]["end"]]
        if not post:
            report["boundary"].append({"split": x.isoformat(), "factor": f, "action": "no row after"})
            continue
        kq = post[0]
        ratio = rows[kq]["shares"] * mult[kq] / (rows[kp]["shares"] * mult[kp])
        tol = (0.5 if lf >= SPLIT_WEAK else 0.25) * lf
        if abs(math.log(ratio / f)) < tol:
            action = "not_restated"
            for k, r in enumerate(rows):
                if r["known"] < x:
                    mult[k] *= f
        elif abs(math.log(ratio)) < tol:
            action = "restated"
        else:
            action = "unclear"
        report["boundary"].append({"split": x.isoformat(), "factor": f, "pre_end": rows[kp]["end"].isoformat(),
                                   "post_end": rows[kq]["end"].isoformat(), "ratio": round(ratio, 4),
                                   "action": action, "rows_changed": sum(r["known"] < x for r in rows)
                                   if action == "not_restated" else 0})
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
        later = [f for x, f in splits if x > rows[ka]["known"] and abs(math.log(f)) >= SPLIT_MIN]
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


def statement_rows(raw: list, splits: list, report: dict) -> list:
    """Income rows -> [{end, known, placeholder, period, eps, shares, ni}], every filing kept, oldest known
    first, on today's split basis."""
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
    return normalize_basis(out, splits, report)


def latest_by_end(rows: list, before: dt.date | None = None) -> list:
    """One row per period end, the latest filing (known before `before` when given), oldest end first."""
    best = {}
    for r in rows:
        if before is not None and not (r["known"] and r["known"] < before):
            continue
        if r["end"] not in best or r["known"] >= best[r["end"]]["known"]:
            best[r["end"]] = r
    return [best[e] for e in sorted(best)]


def annual_check(years: list, quarters: list) -> list:
    """Fiscal-year EPS against the sum of its four quarters (latest filings): a ratio near a split factor marks
    a basis error the steps above missed."""
    out = []
    qs = latest_by_end(quarters)
    for y in latest_by_end(years):
        inside = [q for q in qs if y["end"] - dt.timedelta(days=370) < q["end"] <= y["end"] and q["eps"] is not None]
        if len(inside) == 4 and y["eps"] and sum(q["eps"] for q in inside):
            ratio = y["eps"] / sum(q["eps"] for q in inside)
            if not 0.9 <= ratio <= 1.1:
                out.append({"fy_end": y["end"].isoformat(), "fy_eps": y["eps"], "ratio": round(ratio, 3)})
    return out


# ---------------------------------------------------------------- EPS versions
def ttm_steps(quarters: list) -> tuple[list, list]:
    """Version T as a step function: (days, values), values[i] = (TTM EPS or None, newest period end summed)
    once everything filed by days[i] is known; None when the latest four known quarters are not consecutive."""
    events = sorted((q["known"], q["end"], q) for q in quarters if q["known"] and q["eps"] is not None)
    days, vals, seen = [], [], {}
    i = 0
    while i < len(events):
        d = events[i][0]
        while i < len(events) and events[i][0] == d:
            seen[events[i][1]] = events[i][2]["eps"]          # the latest filing known by then wins
            i += 1
        v, newest = None, None
        if len(seen) >= 4:
            last4 = sorted(seen)[-4:]
            newest = last4[-1]
            if (last4[-1] - last4[0]).days <= TTM_SPAN:
                v = sum(seen[e] for e in last4)
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
    report: dict = field(default_factory=dict)

    def range_at(self, v: str, i: int):
        """(low, mid, high, pct) on bar i for version v, or None."""
        b, e = self.band[BAND_OF.get(v, v)][i], self.eps[v][i]
        if b is None or not e or e <= 0:
            return None
        return e * b["p25"], e * b["median"], e * b["p75"], b["pct"]

    def can_start(self, v: str, i: int) -> bool:
        return self.member[i] and not (self.no_new.get(v) and self.no_new[v][i])


def in_spans(d: str, spans: list) -> bool:
    return any(a <= d < b for a, b in spans)


def build(symbol: str, snap: Path, spans: list, versions=("T", "F", "FY"), snapshot_end: str | None = None,
          first_day: str = "2007-12-01", truncate: str | None = None, spinoffs: list = (),
          audit_known=None) -> Panel:
    """The panel of one company. truncate: drop every input dated after this day (statements by filing date,
    bars and dividends by date) for the self-test that nothing on or before it changes; audit_known(raw row)
    -> (day, placeholder) decides which statements survive the cut when given (the test's own reading of the
    filing dates, so a leak in known_day shows). The split basis is
    settled on the full data first: putting old statements on today's share basis is a change of units that a
    later split forces, not information about what came after (prices are on today's basis too).
    spinoffs: confirmed spin-off ex-dates; no new T plan for 365 days after one (the trailing EPS still holds
    the unit the price no longer does), no new F / FY plan until the end of that fiscal year."""
    raw = snap / "raw"
    split_rows = read(raw / "splits" / f"{symbol}.json")
    splits = split_factors(split_rows)
    bars, sus, clean = clean_bars(read(raw / "full" / f"{symbol}.json"), read(raw / "adj" / f"{symbol}.json"),
                                  split_rows)
    divs = read(raw / "div" / f"{symbol}.json")
    rep = {"clean": clean, "basis_q": {}, "basis_a": {}}
    quarters = statement_rows(read(raw / "inc_q" / f"{symbol}.json"), splits, rep["basis_q"])
    years = statement_rows(read(raw / "inc_a" / f"{symbol}.json"), splits, rep["basis_a"])
    rep["annual_vs_quarters"] = annual_check(years, quarters)
    rep["spin_candidates"] = spin_candidates(bars, split_rows, read(raw / "earn" / f"{symbol}.json"))
    if truncate:
        keep = sum(b["date"] <= truncate for b in bars)
        bars, sus = bars[:keep], sus[:keep]
        divs = [r for r in divs if str(r.get("date"))[:10] <= truncate]
        cut = day(truncate)
        def kept(r):
            k = audit_known(r["raw"])[0] if audit_known else r["known"]
            return k is not None and k <= cut
        quarters = [q for q in quarters if kept(q)]
        years = [y for y in years if kept(y)]
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
    t_days, t_vals = ttm_steps(quarters)
    ntm_f, fy_eps, horizon = fiscal_eps(years)
    # the skill's history check reads 'shares' and 'date' of the fiscal years; on day d only the years filed by d - 1
    q_shares = sorted((q["known"], q["end"], q["shares"]) for q in quarters if q["known"] and q["shares"])
    eps, why_eps = {}, {}
    if "T" in versions:
        t = [ttm_at(t_days, t_vals, day(d)) for d in dates]
        eps["T"], why_eps["T"] = [x[0] for x in t], [x[1] for x in t]
    if "F" in versions or "FY" in versions:
        eps["F"] = [ntm_f(d) for d in dates]
        why_eps["F"] = [None if e is not None else "beyond_horizon" if horizon is None or d > horizon
                        else "eps_not_positive_or_gap" for d, e in zip(dates, eps["F"])]
    if "FY" in versions:
        eps["FY"] = [fy_eps(d) if f is not None else None for d, f in zip(dates, eps["F"])]
    for v in versions:
        p.eps[v] = eps[v]
    for bv in sorted({BAND_OF[v] for v in versions}):
        p.band[bv], p.why[bv] = bands(dates, p.c, eps[bv], why_eps[bv], years, q_shares, first_day)
    if "FY" in versions:
        p.why["FY"] = [w if w else (None if e and e > 0 else "eps_not_positive") for w, e in zip(p.why["F"], eps["FY"])]
    fy_ends = [y["end"].isoformat() for y in latest_by_end(years)]
    for v in versions:
        block = [False] * len(dates)
        for x in spinoffs:
            x = str(x)[:10]
            if v == "T":
                stop = (day(x) + dt.timedelta(days=365)).isoformat()
            else:
                j = bisect.bisect_left(fy_ends, x)
                stop = fy_ends[j] if j < len(fy_ends) else "9999-12-31"
            for i in range(bisect.bisect_left(dates, x), bisect.bisect_right(dates, stop)):
                block[i] = True
        p.no_new[v] = block
    rep["f_horizon"] = horizon
    return p


def bands(dates: list, close: list, eps: list, why_eps: list, years: list, q_shares: list, first_day: str):
    """The skill's 3-year P/E band on every day from first_day on (None before, or with the reason)."""
    n = len(dates)
    out, why = [None] * n, [None] * n
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
        window = [(dates[lo], close[lo]), (dates[i], close[i])]          # _band reads only its ends
        if not eps[i] or eps[i] <= 0:
            why[i] = why_eps[i] or "eps_not_positive"
            continue
        vals = [pe[j] for j in range(lo, i + 1) if pe[j] is not None]
        if len(vals) < MIN_BAND_DAYS:
            why[i] = "short_history"
            continue
        b = A._band(vals, window, pe[i])
        out[i] = {"p25": b["p25"], "median": b["median"], "p75": b["p75"], "pct": b["now_pct"], "n": b["n"]}
    return out, why
