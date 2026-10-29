"""
Day-by-day simulation of the user's buy method on one company's sleeve: the pure-fundamental reading of
rules-1.1 (investment-final-plan docs/rules-1.1.md). Every check happens on a close and trades at the next open.

At each close, in the order of rules-1.1 section 11 (the first that applies wins):
  1. must exit: close < the stop in force (the plan stop, raised to breakeven when tp_1 fills, and from the
     close after tp_2 fills also the trailing stop) -> sell everything, cancel the unfilled tranches
  2. take profit: tp_1 (close >= T1, or >= average cost + 2R), tp_2 (temperature rich or hot, or close >= T2),
     tp_3 (temperature hot: the band-only stand-in for "expensive"); the tiers split the shares held so that
     20 / 30 / 30 / 20 (tail) partition the position; the tail rides the trailing stop
  3. the next DCA tranche (section 5.3): dated every 10 weekdays from the plan day (as the engine counts),
     bought only while the temperature is fair, tranche k only after k - 1 filled, all expiring 120 calendar
     days after the plan day; the fill at the next open is skipped when that open is above the trigger close
     + 0.5 ATR (the chase limit, max_price)
  4. no plan: a close below the band mid starts one when the stop and reward/risk gates pass (sections 6, 7, 9)
Temperatures come from the band percentile: fair <= 0.75 < rich < 0.95 <= hot; no band = unknown, which
pauses buying, never fires a valuation tier and uses the trailing multiple of 'unknown' (3.0). A holding is
sold at the last close before a confirmed spin-off (panel.spin_exit) and at a delisted company's last close.

Before its first fill a plan whose close falls below its stop is cancelled (cancelled_below_stop; only a plan
started while rich or hot, a random-timing start that waits for fair, can get there), and so is a plan still
waiting at the last close before a confirmed spin-off (status 'spin').

Each plan also accumulates, over the SPY sessions 1..252 after its signal close (Plan.m, in sleeve units;
divided by the plan's size in Plan.metrics()), the pilot's primary metric: the P&L of the stock position
hedged every day with the same dollars of SPY (overnight on the shares held at the previous close, intraday on
the shares held after the open's trades), net of trading costs; and with it the unhedged P&L, the T-bill carry
of the position, the costs, the capital deployed and the worst running P&L. A plan that never buys (it lapses
at the chase limit, expires unfilled, is cancelled below its stop or is still waiting at the end) is kept in
'voids' with all of them zero.
"""
from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass, field

TEMP = ("fair", "rich", "hot")
H_LONG, H_SHORT = 252, 126                      # sessions after the signal close in the hedged metric
METRICS = ("dh252", "dh126", "raw252", "tb252", "cost252", "dep252", "mae252")


@dataclass(frozen=True)
class Rules:
    version: str = "T"                          # EPS version of the band (panel.py)
    weights: tuple = (0.10, 0.20, 0.30, 0.20, 0.20)
    interval: int = 10                          # weekdays between DCA tranche dates (entries._add_trading_days)
    expiry_days: int = 120                      # calendar days (long horizon), one expiry for every tranche
    max_price: str | None = "trigger"           # "trigger": next open <= trigger close + 0.5 ATR (section 5.3);
                                                # "plan": close <= P + 0.5 ATR(plan day) (engine + Ledger, V1); None
    max_price_atr: float = 0.5
    tranche_below_mid: bool = False             # V12: later tranches only while the close is still below the mid
    skip_paused: bool = False                   # V7: a tranche not bought before the next one's date is forfeited
    stop_atr: float = 2.0                       # no support zones: lowest planned entry - 2 ATR
    stop_min_atr: float = 1.0
    stop_max_pct: float | None = 0.15           # farther than this from the planned average -> WAIT
    stop_pct: float | None = None               # variant: the exit stop this fraction below P (gates unchanged)
    no_stop: bool = False                       # variant: no loss stop (initial or breakeven); the trailing stays
    t_min_atr: float = 1.5
    t_proj_atr: float = 3.0
    t2_gap_atr: float = 1.0
    t2_fallback_atr: float = 5.0
    min_rr: float | None = 1.5                  # None: no reward/risk gate (V11; the 15% distance check stays)
    min_rr0: float | None = 1.0
    tp_weights: tuple = (0.20, 0.30, 0.30)
    tail: float = 0.20
    tp_split: str = "partition"                 # "partition": 20/30/30/20 of the position; "raw": w x shares held (V2)
    tp1_r: float = 2.0
    tp_temp: bool = True                        # False (V6): tp_2 only at T2, tp_3 never (missing TA states false)
    cancel_on_tp1: bool = False                 # V3: unfilled tranches are cancelled once tp_1 fills
    rich_pct: float = 0.75                      # temperature rich: percentile above this
    hot_pct: float = 0.95                       # hot: at or above this
    trail_k: tuple = (3.0, 2.5, 2.0)            # fair, rich, hot
    trail_k_unknown: float = 3.0
    trail_from: str = "tp_2"                    # binds from the close after this fills: "first_fill" (V4) | "tp_2" | "tp_3" (V5)
    exit_all_at: str | None = None              # variant: "high" sells everything on a close above the band high
    cooldown: int = 0                           # V8: trading days after a full exit before a new plan
    cooldown_after: str = "any"                 # "any" exit | "stop" only
    cost: float = 0.0005                        # one way


@dataclass
class Plan:
    start: int                                  # bar of the close that created it
    price: float                                # P, the plan close
    atr: float
    stop0: float
    t1: float
    t2: float
    t1_src: str
    rr: float | None
    size: float                                 # sleeve value when it was created
    expires: str
    sched: list                                 # ISO date from which each tranche may trigger
    temp0: str | None = None
    pct0: float | None = None
    mid0: float | None = None
    filled: list = field(default_factory=list)  # (bar, price, shares, cash spent, tranche)
    sold: list = field(default_factory=list)    # (bar, price, shares, cash received, reason)
    tp_fired: list = field(default_factory=lambda: [False, False, False])
    tp_filled: list = field(default_factory=lambda: [False, False, False])
    next_k: int = 0                             # next tranche to trigger
    blocked: int = 0                            # tranche fills skipped by the chase limit
    forfeited: int = 0                          # V7
    cancelled: bool = False                     # no more tranches
    end: int | None = None
    divs: float = 0.0
    status: str = "open"
    m: dict = field(default_factory=lambda: dict.fromkeys(METRICS, 0.0))

    def invested(self) -> float:
        return sum(f[3] for f in self.filled)

    def metrics(self) -> dict:
        """Plan.m per unit of the planned position; dep252 in capital-years."""
        out = {k: v / self.size for k, v in self.m.items()}
        out["dep252"] /= 252.0
        return out

    def proceeds(self) -> float:
        return sum(s[3] for s in self.sold) + self.divs


def temp_of(rng, r: Rules) -> str | None:
    """fair / rich / hot from the band percentile, None (unknown) without a band."""
    if rng is None:
        return None
    return "hot" if rng[3] >= r.hot_pct else "rich" if rng[3] > r.rich_pct else "fair"


def add_weekdays(day: dt.date, n: int) -> dt.date:
    """The engine's _add_trading_days (investment-final-plan ifp/entries.py): n weekdays later."""
    d = day
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def initial_stop(P: float, A: float, r: Rules, gate: bool = False) -> float:
    """entries.initial_stop without support zones: P - 2 ATR, at least 1 ATR below, to 4 decimals. The
    stop_pct variant widens only the stop that exits (gate=False): the plan gates keep the rules' stop, so the
    variant trades the same plans as the method."""
    stop = P * (1 - r.stop_pct) if r.stop_pct is not None and not gate else P - r.stop_atr * A
    if P - stop < r.stop_min_atr * A:
        stop = P - r.stop_min_atr * A
    return round(stop, 4)


def targets(P: float, A: float, mid: float, high: float, r: Rules) -> tuple:
    """entries.targets without resistance zones (reference = the planned average = P for DCA): T1 is the mid,
    else the high, at least 1.5 ATR above P, else P + 3 ATR; T2 is the lowest of those candidates (the
    projection included) at least 1 ATR above T1, else max(P + 5 ATR, T1 + 1 ATR)."""
    floor = P + r.t_min_atr * A
    fa = [round(x, 4) for x in (mid, high) if x and x >= floor]
    proj = round(P + r.t_proj_atr * A, 4)
    t1, src = (fa[0], "fa_range") if fa else (proj, "atr_projection")
    rest = sorted(x for x in fa + [proj] if x >= t1 + r.t2_gap_atr * A)
    t2 = rest[0] if rest else round(max(P + r.t2_fallback_atr * A, t1 + r.t2_gap_atr * A), 4)
    return t1, t2, src


def gates(P: float, stop: float, t1: float, r: Rules) -> tuple:
    """(rr, None) or (rr, why it is a WAIT): plan.py's reward/risk gate for a DCA plan, whose tranches are all
    estimated at P and whose stop does not move before tp_1, so rr and rr on the initial stop are one number
    (sizing.core_reward_risk, rounded to 2 decimals and compared rounded). The averages are formed as the
    engine forms them, so a value on a rounding boundary falls the same way."""
    w = r.weights
    p3 = sum(x * P for x in w[:3]) / sum(w[:3])
    p_avg = sum(x * P for x in w) / sum(w)
    risk = p3 - stop
    rr = None if risk <= 0 else round((t1 - p3) / risk, 2)
    if r.stop_max_pct is not None and (p_avg - stop) / p_avg > r.stop_max_pct + 1e-12:
        return rr, "stop_too_far"
    if rr is not None and ((r.min_rr is not None and rr < r.min_rr) or (r.min_rr0 is not None and rr < r.min_rr0)):
        return rr, "reward_risk"
    return rr, None


def run(p, r: Rules, rates, first_day: str = "2008-01-02", last_day: str | None = None, starts=None,
        record_days: bool = True, hedge=None, single: bool = False) -> dict:
    """One sleeve (capital 1.0) through the panel p (panel.Panel). starts: None = the method (a close below the
    band mid); otherwise a set of bar indices on which a plan may start whatever the price (the random-timing
    placebo), every other rule unchanged. rates(date_iso) -> the 3-month T-bill yield known on that day.
    hedge: (SPY's adjusted opens, closes, session numbers) on p.dates, for the hedged metric: the window is
    counted in SPY sessions (without hedge the hedge leg is 0 and the window counts the company's bars).
    single: stop as soon as the first plan has ended (one plan from first_day: the every-start table)."""
    n = len(p.dates)
    i0 = bisect.bisect_left(p.dates, first_day)
    i1 = n - 1 if last_day is None else bisect.bisect_right(p.dates, last_day) - 1
    so, sc, sess = hedge if hedge is not None else (None, None, range(n))
    cash, shares, avg = 1.0, 0.0, 0.0
    stop, stop_src, hc, trail = None, None, None, None
    plan = None
    plans, voids = [], []
    waits = {"stop_too_far": 0, "reward_risk": 0}
    expired, lapsed = 0, 0
    orders = []        # queued at a close for the next open: ("buy", cash, cap, tranche) | ("sell", shares, why)
    cool_until = -1
    value = [None] * n if record_days else None
    held = [None] * n if record_days else None            # the stock part of the value

    def close_plan(i, status):
        nonlocal plan, stop, stop_src, hc, trail, avg, cool_until, shares
        plan.end, plan.status = i, status
        plan.cancelled = True
        plans.append(plan)
        if r.cooldown and (r.cooldown_after == "any" or status == "stop"):
            cool_until = i + r.cooldown
        plan, stop, stop_src, hc, trail, avg, shares = None, None, None, None, None, 0.0, 0.0

    def void(i, status):
        nonlocal plan
        plan.end, plan.status, plan.cancelled = i, status, True
        voids.append(plan)
        plan = None

    def pnl(pl, k, stock, hedged, carry=0.0, cost=0.0):
        m = pl.m
        m["raw252"] += stock - cost
        m["dh252"] += stock - hedged - cost
        m["tb252"] += carry
        m["cost252"] += cost
        if k <= H_SHORT:
            m["dh126"] += stock - hedged - cost

    for i in range(i0, i1 + 1):
        # ---------------- the open of bar i
        cur = plan                                  # the plan held into this bar, for the hedged metric
        k_h = sess[i] - sess[cur.start] if cur is not None else 0
        acc = cur is not None and k_h <= H_LONG
        if i > i0:
            days = (dt.date.fromisoformat(p.dates[i]) - dt.date.fromisoformat(p.dates[i - 1])).days
            rate = rates(p.dates[i - 1]) * days / 365.0
            cash *= 1.0 + rate
            if acc and shares > 0:                  # overnight: the shares held at the previous close
                cp, o = p.c[i - 1], p.o[i]
                spy = so[i] / sc[i - 1] - 1.0 if so is not None and so[i] and sc[i - 1] else 0.0
                pnl(cur, k_h, shares * (o - cp + p.div[i]), shares * cp * spy, shares * cp * rate)
        if shares > 0 and p.div[i]:
            cash += shares * p.div[i]               # holders at the previous close get the dividend
            plan.divs += shares * p.div[i]
        px = p.o[i]
        for o in orders:
            if o[0] == "sell" and shares > 0:
                q = min(o[1], shares)
                got = q * px * (1 - r.cost)
                cash += got
                shares -= q
                plan.sold.append((i, px, q, got, o[2]))
                if acc:
                    pnl(cur, k_h, 0.0, 0.0, cost=q * px * r.cost)
                if o[2].startswith("tp_"):
                    for t in (int(x) - 1 for x in o[2][3:].split("+")):
                        plan.tp_filled[t] = True
                        if t == 0:
                            if not r.no_stop and avg > stop:
                                stop, stop_src = avg, "breakeven"
                            if r.cancel_on_tp1:
                                plan.cancelled = True
            elif o[0] == "buy" and not plan.cancelled:
                k = o[3]
                if o[2] is not None and px > o[2]:  # above the chase limit: no fill, the tranche stays armed
                    plan.blocked += 1
                    if not plan.filled:            # buy_1 blocked: the plan lapses
                        lapsed += 1
                        void(i, "lapsed")
                        break
                    plan.next_k = k
                    continue
                amt = min(o[1], cash)
                q = amt / (px * (1 + r.cost))
                avg = (avg * shares + amt) / (shares + q)
                shares += q
                cash -= amt
                plan.filled.append((i, px, q, amt, k))
                if acc:
                    pnl(cur, k_h, 0.0, 0.0, cost=amt - q * px)
        orders = []
        if plan is not None and plan.filled and shares <= 1e-12 * max(1.0, plan.size):
            close_plan(i, plan.sold[-1][4] if plan.sold else "closed")
        # ---------------- the close of bar i
        c, A = p.c[i], p.atr[i]
        if acc and shares > 0:                      # intraday: the shares held after the open's trades
            o = p.o[i]
            spy = sc[i] / so[i] - 1.0 if so is not None and so[i] and sc[i] else 0.0
            pnl(cur, k_h, shares * (c - o), shares * o * spy)
            cur.m["dep252"] += shares * c
        rng = p.range_at(r.version, i)
        temp = temp_of(rng, r)
        last_bar = i == i1
        today = p.dates[i]
        if plan is not None:
            sells = []
            if shares > 0:
                hc = c if hc is None else max(hc, c)
                if A:
                    k_t = r.trail_k[TEMP.index(temp)] if temp else r.trail_k_unknown
                    trail = hc - k_t * A if trail is None else max(trail, hc - k_t * A)
                bind = {"first_fill": True, "tp_2": plan.tp_filled[1], "tp_3": plan.tp_filled[2]}[r.trail_from]
                eff, eff_src = (stop, stop_src) if not r.no_stop else (None, None)
                if bind and trail is not None and (eff is None or trail > eff):
                    eff, eff_src = trail, "trailing"
                done = plan.tp_fired
                forced = "delisted" if p.delisted and last_bar else "spin" if i in p.spin_exit else None
                if forced:                          # sold at this close: delisted, or a spin-off goes ex next
                    got = shares * c * (1 - r.cost)
                    cash += got
                    plan.sold.append((i, c, shares, got, forced))
                    if acc:
                        pnl(cur, k_h, 0.0, 0.0, cost=shares * c * r.cost)
                    close_plan(i, forced)
                elif eff is not None and c < eff:
                    sells.append(("sell", shares, eff_src))
                    plan.cancelled = True
                elif r.exit_all_at == "high" and rng is not None and c > rng[2]:
                    sells.append(("sell", shares, "exit_high"))
                    plan.cancelled = True
                else:
                    fire = []
                    if not done[0] and (c >= plan.t1 or c >= avg + r.tp1_r * (avg - plan.stop0)):
                        fire.append(0)
                    if not done[1] and ((r.tp_temp and temp in ("rich", "hot")) or c >= plan.t2):
                        fire.append(1)
                    if not done[2] and r.tp_temp and temp == "hot":
                        fire.append(2)
                    if fire:
                        if r.tp_split == "partition":
                            left = sum(w for w, d in zip(r.tp_weights, done) if not d) + r.tail
                            q = shares * sum(r.tp_weights[t] for t in fire) / left
                        else:
                            q = shares * (1 - _prod(1 - r.tp_weights[t] for t in fire))
                        for t in fire:
                            done[t] = True
                        sells.append(("sell", q, "tp_" + "+".join(str(t + 1) for t in fire)))
            if plan is not None and not plan.filled and i in p.spin_exit:
                void(i, "spin")                     # its levels do not survive the distribution
            elif plan is not None and not plan.filled and not r.no_stop and c < plan.stop0:
                void(i, "cancelled_below_stop")     # no first buy once the stop is broken
            if plan is not None and not sells and not plan.cancelled:
                k = plan.next_k
                if today > plan.expires:
                    plan.cancelled = True
                    if not plan.filled:
                        expired += 1
                        void(i, "expired")
                elif k < len(r.weights) and today >= plan.sched[k]:
                    if r.skip_paused and k + 1 < len(r.weights) and today >= plan.sched[k + 1] and plan.filled:
                        while k + 1 < len(r.weights) and today >= plan.sched[k + 1]:
                            k += 1                  # V7: tranches whose window passed are forfeited
                            plan.forfeited += 1
                        plan.next_k = k
                    ok = temp == "fair" and not last_bar and \
                        (r.max_price != "plan" or c <= plan.price + r.max_price_atr * plan.atr) and \
                        (not r.tranche_below_mid or k == 0 or c < rng[1])
                    if ok:
                        cap = c + r.max_price_atr * A if r.max_price == "trigger" and A else None
                        orders.append(("buy", r.weights[k] * plan.size, cap, k))
                        plan.next_k = k + 1
            orders.extend(sells)
        elif i >= cool_until and not last_bar and p.can_start(r.version, i) and rng is not None and A:
            low, mid, high, pct = rng
            if (c < mid) if starts is None else (i in starts):
                stop0 = initial_stop(c, A, r)
                t1, t2, src = targets(c, A, mid, high, r)
                rr, why = gates(c, initial_stop(c, A, r, gate=True), t1, r)
                if why:
                    waits[why] += 1
                else:
                    t0 = dt.date.fromisoformat(today)
                    plan = Plan(start=i, price=c, atr=A, stop0=stop0, t1=t1, t2=t2, t1_src=src, rr=rr, size=cash,
                                expires=(t0 + dt.timedelta(days=r.expiry_days)).isoformat(),
                                sched=[add_weekdays(t0, k * r.interval).isoformat() for k in range(len(r.weights))],
                                temp0=temp, pct0=pct, mid0=mid)
                    stop, stop_src = stop0, "stop"
                    if temp == "fair":
                        cap = c + r.max_price_atr * A if r.max_price == "trigger" else None
                        orders.append(("buy", r.weights[0] * plan.size, cap, 0))
                        plan.next_k = 1
        if acc:
            cur.m["mae252"] = min(cur.m["mae252"], cur.m["raw252"])
        if record_days:
            value[i] = cash + shares * c
            held[i] = shares * c
        if single and (plans or voids or plan is None):
            break
    last = min(i1, i) if i1 >= i0 else i1
    end_value = cash + shares * p.c[last] if i1 >= i0 else 1.0
    open_plan = plan if plan is not None and plan.filled else None
    if plan is not None and not plan.filled:        # still waiting for its first fill at the end
        plan.end, plan.status = last, "unfilled"
        voids.append(plan)
    return {"symbol": p.symbol, "rules": r, "plans": plans, "open": open_plan, "voids": voids, "waits": waits,
            "expired": expired, "lapsed": lapsed, "value": value, "held": held, "first": i0, "last": i1,
            "end_value": end_value, "open_value": shares * p.c[last] if open_plan else 0.0}


def _prod(xs) -> float:
    out = 1.0
    for x in xs:
        out *= x
    return out
