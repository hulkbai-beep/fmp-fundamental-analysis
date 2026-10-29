#!/usr/bin/env python3
"""
The pilot's tables in Chinese, from run_pilot.py's results.json and plans.csv (and checks.py's checks.json when
given): the primary test (version T: each plan's P&L hedged daily with SPY over 252 sessions, against plans
started on random eligible days) with the decision rule set before the data, the rules-free signal test,
version F (look-ahead EPS: shown, never evidence), the portfolios against buy-and-hold and SPY (descriptive),
the variants, the plan statistics by exit and by year, and the data notes. Numbers only: the reading of them is
written by hand.

    python backtest/pilot/report.py --res DIR [--checks DIR] > report.md
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

NAMES = {
    "method_T": "你的买法（T 版：当时已公布的 TTM EPS）",
    "method_F": "上限版 F（事后真实年度 EPS，前瞻 12 个月）",
    "method_FY": "上限版 FY（事后真实当年 EPS × F 的区间）",
    "V1_cap_at_plan_price": "后续批次不追高（收盘价超过首批价 + 0.5 ATR 不买）",
    "V3_cancel_tranches_at_tp1": "第一次止盈后不再补仓",
    "V4_trailing_from_first_fill": "移动止损从第一笔买入起就生效",
    "V5_trailing_after_tp3": "移动止损只在三档止盈都卖完后生效",
    "V6_no_valuation_tiers": "不按估值温度止盈（只看 T1 / 2R / T2）",
    "V8_cooldown_20": "清仓后冷却 20 个交易日",
    "V11_no_reward_risk_gate": "不设盈亏比门槛（只留 15% 止损距离上限）",
    "V12_tranches_below_mid": "后续批次只在仍低于中位时买",
    "stop_15pct": "止损放宽到 15%",
    "no_stop": "不设止损（保留尾仓移动止损）",
    "exit_all_above_high": "高于区间上沿全部卖出",
    "buy_hold_member": "同 50 家买入持有（在指数内期间）",
    "spy_matched_T": "同样的买卖时点换成 SPY（T 版）",
    "spy_matched_F": "同样的买卖时点换成 SPY（F 版）",
    "spy_matched_FY": "同样的买卖时点换成 SPY（FY 版）",
    "spy": "SPY 买入持有",
}
EXITS = {"stop": "止损", "breakeven": "保本止损", "trailing": "移动止损", "delisted": "退市清算",
         "spin": "分拆前清仓", "exit_high": "高于上沿清仓", "open": "期末仍持有", "closed": "其他"}
PROMISING, NOT_PROMISING, INCONCLUSIVE = "值得做更大的检验", "不看好", "说不清"


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


def checks_pass(res: dict, ch: dict | None) -> tuple[bool | None, list]:
    """Condition 4 of the decision rule: the pipeline and look-ahead checks, the every-start table, the
    replacement walk. None when checks.json was not given."""
    notes = []
    es = res["primary"].get("T", {}).get("every_start", {})
    bad_es = [c for c, x in es.items() if x["n_missing"] or x["max_diff"] > 1e-9]
    if bad_es:
        notes.append(f"每天起步表和你的买法对不上：{', '.join(bad_es[:5])}")
    if res.get("walk", {}).get("same_as_pc") is False:
        notes.append("替换规则在云端和你电脑上的结果不同")
    if ch is None:
        return (None if not notes else False), notes + ["没有提供 checks.json"]
    for k, name in (("band", "区间"), ("pipeline", "和技能对数"), ("truncation", "未来数据"), ("fills", "成交")):
        if k in ch and ch[k].get("failed"):
            notes.append(f"{name}检查失败 {ch[k]['failed']} 项")
    return not notes, notes


def decide(t: dict, sig: dict, ok: bool | None) -> tuple[str, list]:
    """The pilot's decision rule (map_stats section 6, set before the data)."""
    pl = t.get("placebo") or {}
    theta, pctl = t.get("theta"), pl.get("percentile")
    loyo = (t.get("leave_one_year_out") or {}).get("min")
    top3 = (t.get("without_top3") or {}).get("theta")
    gap = ((sig.get("h252") or {}).get("gap") or {}).get("theta")
    why = [f"每笔对冲收益比随机择时 {pp(theta)}，在随机择时里排在 {pct(pctl, 0)} 分位",
           f"去掉任何一年后最小 {pp(loyo)}，去掉贡献最大的 3 家后 {pp(top3)}",
           f"不靠规则的信号检验：低于中位后一年比其他日子 {pct(gap, 2)}"]
    if theta is None or pctl is None:
        return INCONCLUSIVE, why + ["没有可比的计划"]
    robust = loyo is not None and loyo > 0 and top3 is not None and top3 > 0
    if ok is False or theta <= 0 or pctl < 0.5 or not robust:
        return NOT_PROMISING, why
    if pctl >= 0.8 and gap is not None and gap > 0 and ok:
        return PROMISING, why
    return INCONCLUSIVE, why


def primary_lines(t: dict, title: str) -> list:
    if not t or t.get("theta") is None:
        return [f"- {title}：没有可比的计划"]
    pl, yb, cl = t["placebo"], t["year_blocks"], t["cluster"]
    return [f"- {title}：每笔 {pp(t['theta'])}（你的买法平均 {pp(t['strategy_mean'])}，随机择时期望 "
            f"{pp(t['placebo_expectation'])}；{t['plans']} 笔计划，其中 {t.get('void_plans', 0)} 笔一股没买到、按 0 计，"
            f"{t['companies']} 家公司，随机起步池 {t['pool']} 天）",
            f"  - 随机择时 {pl['replicas']} 次：随机里不低于它的比例 {pct(pl['p_one_sided'])}（单边 p），"
            f"随机的 5%–95% 范围 {pp(pl['q05'])} 到 {pp(pl['q95'])}",
            f"  - 按年份块的 90% 区间 {pp(yb['lo'])} 到 {pp(yb['hi'])}（{yb['G']} 个年份），"
            f"按公司重抽的标准误 {pp(cl['se'])}",
            f"  - 去掉任何一年：{pp(t['leave_one_year_out']['min'])} 到 {pp(t['leave_one_year_out']['max'])}；"
            f"去掉贡献最大的 3 家（{', '.join(t['without_top3']['companies'])}）：{pp(t['without_top3']['theta'])}"]


def signal_lines(sig: dict) -> list:
    out = [f"- 抽样天数 {sig.get('days')}（每 21 个交易日抽一天，只取能建仓的在指数内交易日），"
           f"其中收盘低于中位的占 {pct(sig.get('below_share'))}"]
    for h in (63, 126, 252):
        x = sig.get(f"h{h}") or {}
        g = x.get("gap") or {}
        if g.get("theta") is None:
            continue
        out.append(f"- 之后 {h} 个交易日扣掉 SPY 的收益，低于中位减其他日子：{pct(g['theta'], 2)}（90% 区间 "
                   f"{pct(g['lo'], 2)} 到 {pct(g['hi'], 2)}，{g['G']} 个年份块）；IC {num(x.get('ic'), 3)}")
    return out


def plan_table(rows: list) -> list:
    n = len(rows)
    if not n:
        return ["（没有计划）"]
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    rets = [float(r["ret"]) for r in rows]
    wins = [x for x in rets if x > 0]
    loss = [x for x in rets if x <= 0]
    out = [f"- 计划数 {n}，平均建仓比例 {pct(statistics.mean(float(r['filled_frac']) for r in rows))}，"
           f"平均持有 {statistics.mean(int(r['sessions']) for r in rows):.0f} 个交易日",
           f"- 每笔收益（按投入资金）：平均 {pct(statistics.mean(rets), 2)}，中位 {pct(statistics.median(rets), 2)}，"
           f"赚钱的比例 {pct(len(wins) / n)}，平均赚 {pct(statistics.mean(wins), 2) if wins else '—'}，"
           f"平均亏 {pct(statistics.mean(loss), 2) if loss else '—'}",
           "- 最后一笔卖出的原因：" + "，".join(f"{EXITS.get(k, k)} {v}（{pct(v / n)}）" for k, v in
                                       sorted(by.items(), key=lambda kv: -kv[1])),
           "- 止盈档位触发比例：T1/2R 档 {}，估值偏贵/T2 档 {}，很贵档 {}".format(
               pct(sum(r["tp1"] == "True" for r in rows) / n), pct(sum(r["tp2"] == "True" for r in rows) / n),
               pct(sum(r["tp3"] == "True" for r in rows) / n))]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--res", required=True)
    ap.add_argument("--checks")
    a = ap.parse_args(argv)
    res = json.loads((Path(a.res) / "results.json").read_text(encoding="utf-8"))
    with (Path(a.res) / "plans.csv").open(encoding="utf-8") as f:
        plans = list(csv.DictReader(f))
    ch = json.loads((Path(a.checks) / "checks.json").read_text(encoding="utf-8")) if a.checks else None
    s, cmp_ = res["summary"], res["compare"]
    prim, sig = res.get("primary", {}), res.get("signal", {}).get("T", {})
    w = []
    w.append(f"# 50 家试点结果（{res['first_day']} 到 {res['snapshot']['last_day']}）\n")
    swaps = [x for x in res["replacements"] if x.get("in")]
    w.append(f"公司 {len(res['companies'])} 家；替换 {len(swaps)} 家"
             + ("：" + "，".join(f"{x['out']} → {x['in']}（{x['why']}）" for x in swaps) if swaps else "") + "\n")
    t = prim.get("T", {})
    ok, notes = checks_pass(res, ch)
    label, why = decide(t.get("dh252", {}), sig, ok)
    w.append("## 结论（按事先定好的规则）\n")
    w.append(f"**{label}**\n")
    w += [f"- {x}" for x in why]
    w += [f"- 检查：{x}" for x in notes] or ["- 检查：全部通过"]
    w.append("- 50 家只能看出每笔大约 0.5 个百分点以上的优势（相当于投入资金每年约 4 个百分点）；"
             "现实大小的优势多半会显示为“说不清”。\n")
    w.append("## 主检验：你的买法 vs 随机择时（T 版，每笔计划 252 个交易日、每天用 SPY 对冲后的盈亏，"
             "按计划资金算，扣交易成本）\n")
    w += primary_lines(t.get("dh252"), "252 天对冲收益")
    w += primary_lines(t.get("dh126"), "126 天对冲收益（只作参考）")
    w += primary_lines(t.get("raw252"), "252 天不对冲收益（只作参考，含仓位多少的影响）")
    w.append("")
    w.append("## 不靠交易规则的信号检验（T 版）\n")
    w += signal_lines(sig)
    w.append("")
    if "F" in prim:
        w.append("## F 版（用了事后才知道的 EPS，含未来信息：只看看，不作证据）\n")
        w += primary_lines(prim["F"].get("dh252"), "252 天对冲收益")
        w.append("")
    w.append("## 组合层面（只作描述；每家等权一份资金，空仓部分拿 3 个月国债利息）\n")
    w.append("| 方案 | 年化 | 夏普 | 最大回撤 | 平均仓位 | 计划数 |")
    w.append("|---|---|---|---|---|---|")
    for run in [k for k in NAMES if k in s]:
        x = s[run]
        w.append(f"| {NAMES[run]} | {pct(x['cagr'])} | {num(x['sharpe'])} | {pct(x['max_dd'])} | "
                 f"{pct(x.get('held_share'))} | {x.get('plans', '—')} |")
    w.append("")
    for v, c in cmp_.items():
        w.append(f"## {NAMES['method_' + v]}" + ("（含未来信息，只作描述）" if v != "T" else "") + "\n")
        mine = [r for r in plans if r["run"] == f"method_{v}"]
        w += plan_table(mine)
        full = [r for r in mine if r.get("full252") == "True"]
        if full:
            dh = [float(r["dh252"]) for r in full]
            dep = [float(r["dep252"]) for r in full]
            w.append(f"- 252 天窗口完整的 {len(full)} 笔：对冲收益平均 {pp(statistics.mean(dh))}，中位 "
                     f"{pp(statistics.median(dh))}；平均占用资金 {statistics.mean(dep):.3f} 年")
        w.append(f"- 每笔平均收益（按投入资金）：{ci(c['plan_mean'])}")
        if "placebo" in c:
            pl = c["placebo"]
            w.append(f"- 组合和整段随机择时比（{pl['replicas']} 次，计划数 {pl['plans']['method']} 对 "
                     f"{pl['plans']['placebo_mean']:.0f}，平均仓位 {pct(pl['held_share']['method'])} 对 "
                     f"{pct(pl['held_share']['placebo_mean'])}；只作描述）：")
            for k, name in (("cagr", "组合年化"), ("sharpe", "夏普"), ("max_dd", "最大回撤")):
                r = pl[k]
                if r.get("placebo_mean") is not None:
                    fmt = num if k == "sharpe" else (lambda x: pct(x, 2))
                    w.append(f"  - {name}：你的买法 {fmt(r['value'])}，随机择时平均 {fmt(r['placebo_mean'])}，"
                             f"随机里不低于你的比例 {pct(r['p_one_sided'])}")
        for k, name in (("vs_buy_hold_member", "同 50 家买入持有"), (f"vs_spy_matched_{v}", "同时点换成 SPY"),
                        ("vs_spy", "SPY 买入持有")):
            if k in c:
                w.append(f"- 每年收益减{name}（只作描述）：{ci(c[k]['mean'])}")
        w.append("")
    w.append("## 对照版本（只作描述，T 版）\n")
    w.append("| 版本 | 计划数 | 每笔平均 | 止损比例 | 年化 | 最大回撤 | 平均仓位 |")
    w.append("|---|---|---|---|---|---|---|")
    for run in [k for k in NAMES if k.startswith(("V", "stop_", "no_", "exit_"))]:
        rows = [r for r in plans if r["run"] == run]
        if run not in s:
            continue
        n = len(rows)
        w.append(f"| {NAMES[run]} | {n} | {pct(statistics.mean(float(r['ret']) for r in rows), 2) if n else '—'} | "
                 f"{pct(sum(r['status'] == 'stop' for r in rows) / n) if n else '—'} | {pct(s[run]['cagr'])} | "
                 f"{pct(s[run]['max_dd'])} | {pct(s[run].get('held_share'))} |")
    w.append("")
    w.append("## 按年份（T 版，按建仓开始的年份）\n")
    w.append("| 年份 | 计划数 | 每笔平均 | 止损比例 |")
    w.append("|---|---|---|---|")
    main_rows = [r for r in plans if r["run"] == "method_T"]
    for y in sorted({r["year"] for r in main_rows}):
        rows = [r for r in main_rows if r["year"] == y]
        w.append(f"| {y} | {len(rows)} | {pct(statistics.mean(float(r['ret']) for r in rows), 2)} | "
                 f"{pct(sum(r['status'] == 'stop' for r in rows) / len(rows))} |")
    w.append("")
    w.append("## 数据说明\n")
    reasons = {}
    for sym, rep in res["reports"].items():
        for k, n in rep["member_days_by_reason"].get("T", {}).items():
            reasons[k] = reasons.get(k, 0) + n
    tot = sum(reasons.values()) or 1
    w.append("- 在指数内的交易日里，T 版有区间的比例 {}；没有区间的原因：{}".format(
        pct(reasons.get("ok", 0) / tot), "，".join(f"{k} {pct(n / tot)}" for k, n in
                                                 sorted(reasons.items(), key=lambda kv: -kv[1]) if k != "ok")))
    if ch:
        for k, name in (("band", "区间和技能原函数逐一对数"), ("pipeline", "最后一天和技能的 price_range 对数"),
                        ("truncation", "删掉未来数据后结果不变"), ("fills", "每笔成交都在信号次日开盘")):
            if k in ch:
                c = ch[k]
                n = c.get("checked", c.get("compared", c.get("fills")))
                w.append(f"- 检查：{name}，{n} 项，失败 {c['failed']}")
    sys.stdout.write("\n".join(w) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
