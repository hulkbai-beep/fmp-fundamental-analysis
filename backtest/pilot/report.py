#!/usr/bin/env python3
"""
The pilot's tables in Chinese, from run_pilot.py's results.json and plans.csv (with checks.py's checks.json and
repro.json when given): the primary test (version T: each plan's P&L hedged daily with SPY over 252 sessions,
against plans started on random eligible days) with the decision rule of SPEC v1 6.2, the rules-free signal
test, version F read one way only (6.4), the variants against their own tables (descriptive), the portfolios
against buy-and-hold and SPY (descriptive), the plan statistics by exit and by year, and the data notes.
Numbers only: the reading of them is written by hand.

    python backtest/pilot/report.py --res DIR [--checks DIR] > report.md
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_pilot as R  # noqa: E402
import stats as ST  # noqa: E402

NAMES = {
    "method_T": "你的买法（T 版：当时已公布的 TTM EPS）",
    "method_F": "参考版 F（事后真实年度 EPS，前瞻 12 个月）",
    "stop_15pct": "V-a 止损放宽到 15%",
    "exit_all_above_high": "V-b 高于区间上沿全部卖出",
    "V8_cooldown_20": "V-c 清仓后冷却 20 个交易日",
    "V12_tranches_below_mid": "V-d 后续批次只在仍低于中位时买",
    "buy_hold_member": "同 50 家买入持有（在指数内期间）",
    "spy_matched_T": "同样的买卖时点换成 SPY（T 版）",
    "spy_matched_F": "同样的买卖时点换成 SPY（F 版）",
    "spy": "SPY 买入持有",
}
VARIANTS = ("stop_15pct", "exit_all_above_high", "V8_cooldown_20", "V12_tranches_below_mid")
EXITS = {"stop": "止损", "breakeven": "保本止损", "trailing": "移动止损", "delisted": "退市清算",
         "spin": "分拆前清仓或取消", "exit_high": "高于上沿清仓", "open": "期末仍持有", "closed": "其他",
         "lapsed": "首批追高作废", "expired": "到期没买到", "cancelled_below_stop": "买前跌破止损取消",
         "unfilled": "期末还在等首批"}
NO_RESULT, PROMISING, NOT_PROMISING, INCONCLUSIVE = "没有结果（检查没通过）", "有希望", "不看好", "说不准"
CHECKS = (("calendar", "交易日历"), ("band", "区间"), ("pipeline", "和技能对数"), ("truncation", "未来数据"),
          ("fills", "成交"))
CHECKS_CODE = (HERE / "checks.py", HERE.parent.parent / "scripts" / "score.py")    # the code the checks come from
MIN_SAMPLED = 200                               # band triples and truncation cuts, at least (SPEC 8.3 and 8.5)


def pct(x, d=1):
    return "—" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def ci(o):
    if not o or o.get("theta") is None:
        return "—"
    return f"{pct(o['theta'], 2)}（90% 区间 {pct(o['lo'], 2)} 到 {pct(o['hi'], 2)}，{o['G']} 个年份块）"


def pp(x, d=2):
    """A per-plan amount in percentage points of the planned position."""
    return "—" if x is None else f"{100 * x:+.{d}f} 个百分点"


def results_digest(res: dict) -> str:
    """The md5 of a results.json apart from its creation time (check 8 compares results this way)."""
    return hashlib.md5(json.dumps({k: v for k, v in res.items() if k != "created"}, sort_keys=True,
                                  default=str).encode("utf-8")).hexdigest()


def checks_code() -> dict:
    return {f.name: hashlib.md5(f.read_bytes()).hexdigest() for f in CHECKS_CODE}


def checks_pass(res: dict, ch: dict | None, repro: dict | None) -> tuple[bool, list]:
    """Section 8 of SPEC v1, as far as the files show it: the results are of the full run fixed beforehand (both
    versions, SPEC 5.2's replicas, the four variants), every every-start table reproduces its plans, the
    replacement walk matches the PC's, checks.py's checks all pass and were made from the inputs of these
    results (snapshot, sample, confirmed spin-offs, code) by the checks' code as it is now, on at least 200 band
    triples and truncation cuts and on every plan of the every-start tables, with the data review table
    written, and two runs gave these same results. The unit tests, the snapshot's integrity and the signature
    on the data review are steps of the run, not of these files."""
    notes = []
    prim = res.get("primary", {})
    reps = {v: ((x.get("dh252") or {}).get("placebo") or {}).get("replicas") for v, x in prim.items()}
    if sorted(prim) != sorted(R.VERSIONS) or any(n != ST.PLAN_REPS for n in reps.values()) or \
            sorted(res.get("variants") or {}) != sorted(R.VARIANTS) or \
            sorted(res.get("variant_tests") or {}) != sorted(R.VARIANTS):
        notes.append(f"不是事先定好的完整运行（T、F 两版，随机择时各 {ST.PLAN_REPS} 次，四个对照版本）：这次的版本 "
                     + ("、".join(f"{v} 随机择时 {n} 次" for v, n in sorted(reps.items())) or "没有")
                     + f"，对照版本 {len(res.get('variant_tests') or {})} 个")
    tables = {f"{v} 版": x.get("every_start", {}) for v, x in res.get("primary", {}).items()}
    tables.update({NAMES.get(k, k): x.get("every_start", {}) for k, x in res.get("variant_tests", {}).items()})
    for name, es in tables.items():
        bad = [c for c, x in es.items() if x["n_missing"] or x["max_diff"] > 1e-9]
        if bad:
            notes.append(f"{name}的每天起步表和实际计划对不上：{', '.join(bad[:5])}")
    if res.get("walk", {}).get("same_as_pc") is False:
        notes.append("替换规则在云端和你电脑上的结果不同")
    if ch is None:
        notes.append("没有提供 checks.json")
    else:
        if ch.get("inputs") is None or ch["inputs"] != res.get("inputs"):
            notes.append("检查和这次运行用的不是同一份快照、样本、分拆确认或代码")
        if ch.get("checks_code") != checks_code():
            notes.append("检查不是用现在的检查代码（checks.py、score.py）做的")
        for k, name in (("band", "区间"), ("truncation", "未来数据")):
            if k in ch and (ch[k].get("checked") or 0) < MIN_SAMPLED:
                notes.append(f"{name}检查只查了 {ch[k].get('checked') or 0} 项，至少要 {MIN_SAMPLED} 项")
        if "fills" in ch and not 0 < (ch["fills"].get("pool_days") or 0) == ch["fills"].get("every_start_plans"):
            notes.append(f"成交检查只重放了随机起步表的 {ch['fills'].get('every_start_plans') or 0} 笔计划，"
                         f"起步池有 {ch['fills'].get('pool_days') or 0} 天，要每天都重放")
        for k, name in CHECKS:
            if k not in ch:
                notes.append(f"没有跑{name}检查")
            elif ch[k].get("failed"):
                notes.append(f"{name}检查失败 {ch[k]['failed']} 项")
        if not (ch.get("review") or {}).get("written"):
            notes.append("没有生成数据核对表（review.md）")
    if repro is None:
        notes.append("没有提供重跑对比（repro.json）")
    elif repro.get("diff") or not repro.get("same"):
        notes.append(f"两次运行结果不同：{', '.join(repro.get('diff') or ['?'])}")
    elif (repro.get("results") or [None])[0] != results_digest(res):
        notes.append("重跑对比（repro.json）比的不是这份结果")
    return not notes, notes


def decide(t: dict, sig: dict, ok: bool) -> tuple[str, list]:
    """SPEC v1 6.2, fixed before the data."""
    pl = t.get("placebo") or {}
    theta, pctl = t.get("theta"), pl.get("percentile")
    loyo = (t.get("leave_one_year_out") or {}).get("min")
    top3 = (t.get("without_top3") or {}).get("theta")
    gap = ((sig.get("h252") or {}).get("gap") or {}).get("theta")
    why = [f"每笔对冲收益比随机择时 {pp(theta)}，在随机择时里排在 {pct(pctl, 0)} 分位",
           f"去掉任何一年后最小 {pp(loyo)}，去掉贡献最大的 3 家后 {pp(top3)}",
           f"不靠规则的信号检验：低于中位后一年比其他日子 {pct(gap, 2)}"]
    if not ok:
        return NO_RESULT, why
    if theta is None or pctl is None:
        return NO_RESULT, why + ["没有可比的计划"]
    if theta <= 0 or (loyo is not None and loyo <= 0) or (top3 is not None and top3 <= 0):
        return NOT_PROMISING, why
    if pctl >= 0.8 and gap is not None and gap > 0 and loyo is not None and top3 is not None:
        return PROMISING, why
    return INCONCLUSIVE, why


def f_reading(label: str, t_theta, f_theta) -> list:
    """SPEC v1 6.4: F is read one way only."""
    if label == NO_RESULT:
        return []
    if f_theta is None:
        return ["F 版没有可比的计划"]
    out = []
    if label == PROMISING:
        out.append("T 版有希望：在试点能测出的范围内，这是对用 TTM 市盈率这版规则的真证据")
    if f_theta <= 0:
        out.append("F ≤ 0" + ("，T 也 ≤ 0：对这套规则是很强的反面证据" if t_theta is not None and t_theta <= 0 else
                              "：就算事先确切知道之后的盈利，这套规则也没把买点挑得比随机好，是很强的反面证据"))
    else:
        out.append("F > 0：说明不了什么（F 用了事后的盈利，没有优势时也常显得好）"
                   + ("；T 不看好，所以对用分析师预期的规则仍是说不准，只能靠从现在起存档的预期来定"
                      if label == NOT_PROMISING else ""))
    return out


def primary_lines(t: dict, title: str) -> list:
    if not t or t.get("theta") is None:
        return [f"- {title}：没有可比的计划"]
    pl, yb, cl = t.get("placebo"), t["year_blocks"], t["cluster"]
    lo = t["leave_one_company_out"]
    out = [f"- {title}：每笔 {pp(t['theta'])}（你的买法平均 {pp(t['strategy_mean'])}，随机择时期望 "
           f"{pp(t['placebo_expectation'])}；{t['plans']} 笔计划，其中 {t.get('void_plans', 0)} 笔一股没买到、按 0 计，"
           f"{t['companies']} 家公司，随机起步池 {t['pool']} 天）"]
    if pl:
        out.append(f"  - 随机择时 {pl['replicas']} 次：随机里不低于它的比例 {pct(pl['p_one_sided'])}（单边 p），"
                   f"随机的 5%–95% 范围 {pp(pl['q05'])} 到 {pp(pl['q95'])}")
    out += [f"  - 按年份块的 90% 区间 {pp(yb['lo'])} 到 {pp(yb['hi'])}（{yb['G']} 个年份），"
            f"按公司重抽的标准误 {pp(cl['se'])}",
            f"  - 去掉任何一年：{pp(t['leave_one_year_out']['min'])} 到 {pp(t['leave_one_year_out']['max'])}；"
            f"去掉贡献最大的 3 家（{', '.join(t['without_top3']['companies'])}）：{pp(t['without_top3']['theta'])}；"
            f"去掉任何一家：{pp(lo['min'])} 到 {pp(lo['max'])}"]
    return out


def signal_lines(sig: dict) -> list:
    out = [f"- 抽样天数 {sig.get('days')}（每 21 个 SPY 交易日抽一天，只取能随机起步、252 天窗口完整的日子），"
           f"其中收盘低于中位的占 {pct(sig.get('below_share'))}"]
    for h in (63, 126, 252):
        x = sig.get(f"h{h}") or {}
        g = x.get("gap") or {}
        if g.get("theta") is None:
            continue
        unit = {"two_years": "个两年块", "company": "家公司"}.get(g.get("scheme"), "个年份块")
        y1 = (x.get("gap_schemes") or {}).get("by_year")
        by_year = ""
        if y1:                          # SPEC 5.3's own blocks: narrower in most no-edge worlds, not in all
            narrower = y1["hi"] - y1["lo"] < g["hi"] - g["lo"]
            by_year = (f"；按单个年份重抽（SPEC 5.3 原来的做法）{'会窄到' if narrower else '是'} "
                       f"{pct(y1['lo'], 2)} 到 {pct(y1['hi'], 2)}{'，偏乐观' if narrower else ''}")
        out.append(f"- 之后 {h} 个交易日扣掉 SPY 的收益，低于中位减其他日子：{pct(g['theta'], 2)}（90% 区间 "
                   f"{pct(g['lo'], 2)} 到 {pct(g['hi'], 2)}，按 {g['G']} {unit}重抽{by_year}"
                   + f"）；IC {num(x.get('ic'), 3)}" + ("（主项）" if h == 252 else "（只作参考）"))
    return out


def describe_lines(d: dict) -> list:
    """SPEC 5.4: the method's plans against the pool, per unit of the planned position."""
    if not d or not d.get("plans"):
        return []
    m, q = d["mean"], d["pool_mean"]
    out = [f"- 252 天窗口完整的 {d['plans']} 笔，和随机起步比（随机按每家公司的计划数加权）：",
           f"  - 对冲收益 {pp(m['dh252'])} 对 {pp(q['dh252'])}；不对冲 {pp(m['raw252'])} 对 {pp(q['raw252'])}；"
           f"大盘部分（不对冲减对冲）{pp(d['market_part']['method'])} 对 {pp(d['market_part']['pool'])}",
           f"  - 占用资金 {m['dep252']:.3f} 对 {q['dep252']:.3f} 年；交易成本 {pp(m['cost252'], 3)} 对 {pp(q['cost252'], 3)}；"
           f"最差浮亏平均 {pp(m['mae252'])} 对 {pp(q['mae252'])}",
           f"  - 对冲收益的分布：中位 {pp(d['dh252']['median'])}，四分位 {pp(d['dh252']['q25'])} 到 "
           f"{pp(d['dh252']['q75'])}，最差 5% {pp(d['dh252']['q05'])}",
           "  - 结束方式：" + "，".join(f"{EXITS.get(k, k)} {pct(v)}（随机 {pct(d['pool_exits'].get(k, 0.0))}）"
                                     for k, v in sorted(d["exits"].items(), key=lambda kv: -kv[1]))]
    return out


def bought(rows: list) -> list:
    return [r for r in rows if r.get("ret") not in (None, "")]


def plan_table(rows: list) -> list:
    n = len(rows)
    if not n:
        return ["（没有计划）"]
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    fill = bought(rows)
    rets = [float(r["ret"]) for r in fill]
    wins = [x for x in rets if x > 0]
    loss = [x for x in rets if x <= 0]
    out = [f"- 计划数 {n}，其中买到的 {len(fill)}；买到的平均建仓比例 "
           f"{pct(statistics.mean(float(r['filled_frac']) for r in fill)) if fill else '—'}，平均成本比计划价 "
           f"{pct(statistics.mean(float(r['avg_vs_P']) for r in fill), 2) if fill else '—'}，首批平均 "
           f"{statistics.mean(int(r['days_to_fill']) for r in fill) if fill else 0:.1f} 个交易日后买到，平均持有 "
           f"{statistics.mean(int(r['sessions']) for r in fill) if fill else 0:.0f} 个交易日"]
    if rets:
        payoff = statistics.mean(wins) / -statistics.mean(loss) if wins and loss and statistics.mean(loss) < 0 else None
        out.append(f"- 每笔收益（按投入资金）：平均 {pct(statistics.mean(rets), 2)}，中位 {pct(statistics.median(rets), 2)}，"
                   f"赚钱的比例 {pct(len(wins) / len(rets))}，平均赚 {pct(statistics.mean(wins), 2) if wins else '—'}，"
                   f"平均亏 {pct(statistics.mean(loss), 2) if loss else '—'}，盈亏比 {num(payoff)}")
    out += ["- 结束方式：" + "，".join(f"{EXITS.get(k, k)} {v}（{pct(v / n)}）" for k, v in
                                    sorted(by.items(), key=lambda kv: -kv[1])),
            "- 止盈档位触发比例（买到的计划里）：T1/2R 档 {}，估值偏贵/T2 档 {}，很贵档 {}".format(
                *(pct(sum(r[k] == "True" for r in fill) / len(fill)) if fill else "—" for k in ("tp1", "tp2", "tp3")))]
    return out


def group_cells(rows: list) -> str:
    """Counts and means of a group of plans (SPEC 5.4's breakdowns): plans, plans that bought, the mean return
    on the money put in, the mean DH_252 of the plans with a full window (void plans count 0, as in the main
    test), and the share stopped out."""
    fill = bought(rows)
    full = [float(r["dh252"]) for r in rows if r["full252"] == "True"]
    return (f"{len(rows)} | {len(fill)} | "
            f"{pct(statistics.mean(float(r['ret']) for r in fill), 2) if fill else '—'} | "
            f"{pp(statistics.mean(full)) if full else '—'}（{len(full)} 笔） | "
            f"{pct(sum(r['status'] == 'stop' for r in rows) / len(rows)) if rows else '—'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--res", required=True)
    ap.add_argument("--checks")
    a = ap.parse_args(argv)
    rd = Path(a.res)
    res = json.loads((rd / "results.json").read_text(encoding="utf-8"))
    with (rd / "plans.csv").open(encoding="utf-8") as f:
        plans = list(csv.DictReader(f))
    ch = json.loads((Path(a.checks) / "checks.json").read_text(encoding="utf-8")) if a.checks else None
    repro = json.loads((rd / "repro.json").read_text(encoding="utf-8")) if (rd / "repro.json").exists() else None
    s, cmp_ = res["summary"], res["compare"]
    prim, sig = res.get("primary", {}), res.get("signal", {}).get("T", {})
    w = []
    w.append(f"# 50 家试点结果（{res['first_day']} 到 {res['snapshot']['last_day']}）\n")
    swaps = [x for x in res["replacements"] if x.get("in")]
    w.append(f"公司 {len(res['companies'])} 家；替换 {len(swaps)} 家"
             + ("：" + "，".join(f"{x['out']} → {x['in']}（{x['why']}）" for x in swaps) if swaps else "") + "\n")
    t, fv = prim.get("T", {}), prim.get("F", {})
    ok, notes = checks_pass(res, ch, repro)
    label, why = decide(t.get("dh252", {}), sig, ok)
    w.append("## 结论（按事先定好的规则）\n")
    w.append(f"**{label}**\n")
    w += [f"- {x}" for x in why]
    w += [f"- 检查：{x}" for x in notes] or ["- 检查：全部通过"]
    w += [f"- F 版的读法：{x}" for x in f_reading(label, t.get("dh252", {}).get("theta"),
                                                 fv.get("dh252", {}).get("theta"))]
    w.append("- 50 家只能看出每笔大约 0.5 个百分点以上的优势（相当于投入资金每年约 4 个百分点）；"
             "现实大小的优势多半会显示为“说不准”。\n")
    w.append("## 主检验：你的买法 vs 随机择时（T 版，每笔计划之后 252 个 SPY 交易日、每天用 SPY 对冲后的盈亏，"
             "按计划资金算，扣交易成本）\n")
    w += primary_lines(t.get("dh252"), "252 天对冲收益")
    w += primary_lines(t.get("dh126"), "126 天对冲收益（只作参考）")
    w += primary_lines(t.get("raw252"), "252 天不对冲收益（只作参考，含仓位多少的影响）")
    w.append("")
    w.append("## 不靠交易规则的信号检验（T 版）\n")
    w += signal_lines(sig)
    w.append("")
    if fv:
        w.append("## F 版（用了事后才知道的 EPS：只按上面的读法看）\n")
        w += primary_lines(fv.get("dh252"), "252 天对冲收益")
        w.append("")
    vt = res.get("variant_tests", {})
    if vt:
        w.append("## 四个对照版本（T 版，只作描述：每个版本对自己的随机起步表，不给 p 值）\n")
        w.append("| 版本 | 计划数（252 天窗口完整） | 每笔对冲收益比随机 | 止损结束的比例 | 组合年化 | 最大回撤 | 平均仓位 |")
        w.append("|---|---|---|---|---|---|---|")
        for k in VARIANTS:
            if k not in vt:
                continue
            x, d = vt[k]["dh252"], res.get("describe", {}).get(k, {})
            stops = d.get("exits", {}).get("stop")
            w.append(f"| {NAMES[k]} | {x.get('plans', 0)} | {pp(x.get('theta'))} | {pct(stops)} | "
                     f"{pct(s[k]['cagr'])} | {pct(s[k]['max_dd'])} | {pct(s[k].get('held_share'))} |")
        w.append("- 每个版本的随机对照有自己的零偏差，版本之间的高低不算证据；V-c 的随机起步表就是主表"
                 "（单独一笔计划碰不到冷却期）。\n")
    for v in ("T", "F"):
        if v not in cmp_:
            continue
        c = cmp_[v]
        w.append(f"## {NAMES['method_' + v]}：计划明细" + ("（含未来信息，只作描述）" if v != "T" else "") + "\n")
        w += describe_lines(res.get("describe", {}).get(v))
        w += plan_table([r for r in plans if r["run"] == f"method_{v}"])
        w.append(f"- 每笔平均收益（按投入资金，只算买到的）：{ci(c['plan_mean'])}")
        for k, name in (("vs_buy_hold_member", "同 50 家买入持有"), (f"vs_spy_matched_{v}", "同时点换成 SPY"),
                        ("vs_spy", "SPY 买入持有")):
            if k in c:
                w.append(f"- 组合每年收益减{name}（只作描述）：{ci(c[k]['mean'])}")
        w.append("")
    w.append("## 组合层面（只作描述；每家等权一份资金，空仓部分拿 3 个月国债利息）\n")
    w.append("| 方案 | 年化 | 夏普 | 最大回撤 | 平均仓位 | 买到的计划数 |")
    w.append("|---|---|---|---|---|---|")
    for run in [k for k in NAMES if k in s]:
        x = s[run]
        w.append(f"| {NAMES[run]} | {pct(x['cagr'])} | {num(x['sharpe'])} | {pct(x['max_dd'])} | "
                 f"{pct(x.get('held_share'))} | {x.get('plans', '—')} |")
    w.append("")
    head = "计划数 | 买到的 | 每笔平均（按投入） | 每笔对冲收益（252 天窗口完整的） | 止损比例 |"
    w.append("## 按年份（T 版，按建仓开始的年份；只作描述）\n")
    w.append("| 年份 | " + head)
    w.append("|---|---|---|---|---|---|")
    main_rows = [r for r in plans if r["run"] == "method_T"]
    for y in sorted({r["year"] for r in main_rows}):
        w.append(f"| {y} | {group_cells([r for r in main_rows if r['year'] == y])}")
    w.append("")
    w.append("## 按行业（T 版；只作描述，每个行业只有几家公司）\n")
    w.append("| 行业 | 公司数 | " + head)
    w.append("|---|---|---|---|---|---|---|")
    firms = {}
    for c in res["companies"]:
        firms[c["sector"]] = firms.get(c["sector"], 0) + 1
    for sec, k in sorted(firms.items(), key=lambda kv: (-kv[1], kv[0])):
        w.append(f"| {sec} | {k} | {group_cells([r for r in main_rows if r['sector'] == sec])}")
    w.append("")
    w.append("## 数据说明\n")
    reasons = {}
    for sym, rep in res["reports"].items():
        for k, n in rep["member_days_by_reason"].get("T", {}).items():
            reasons[k] = reasons.get(k, 0) + n
    tot = sum(reasons.values()) or 1
    w.append("- 在指数内的交易日里，T 版有区间的比例 {}；没有区间的原因：{}".format(
        pct(reasons.get("ok", 0) / tot), "，".join(f"{k} {pct(n / tot)}" for k, n in
                                                 sorted(reasons.items(), key=lambda kv: -kv[1]) if k != "ok") or "无"))
    for v, g in res.get("gates", {}).items():
        if g.get("below_mid"):
            w.append(f"- {v} 版收盘低于中位、本可起步的 {g['below_mid']} 天里：止损离计划均价超过 15% 挡掉 "
                     f"{pct(g['stop_too_far'] / g['below_mid'])}，盈亏比不够挡掉 {pct(g['reward_risk'] / g['below_mid'])}")
    tf = res.get("t_vs_f")
    if tf and tf.get("days"):
        w.append(f"- T 和 F 都有区间的 {tf['days']} 天里，两者对“低于中位”判断一致的占 {pct(tf['agree'] / tf['days'])}；"
                 f"抽样 {tf['sampled']} 天上两者分位的秩相关 {num(tf['spearman'])}")
    if ch:
        for k, name in (("calendar", "SPY 两份行情的交易日一致"), ("band", "区间和技能原函数逐一对数"),
                        ("pipeline", "最后一天和技能的 price_range 对数"), ("truncation", "删掉未来数据后结果不变"),
                        ("fills", "每笔成交的时点、价格和股数")):
            if k in ch:
                c = ch[k]
                n = c.get("checked", c.get("compared", c.get("fills")))
                w.append(f"- 检查：{name}，{n} 项，失败 {c['failed']}")
    sys.stdout.write("\n".join(w) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
