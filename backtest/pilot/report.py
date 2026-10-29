#!/usr/bin/env python3
"""
The pilot's tables in Chinese, from run_pilot.py's results.json and plans.csv (and checks.py's checks.json when
given): the main result (version T) against the random-timing placebo, buy-and-hold and SPY, the ceilings F and
FY, the variants, the plan statistics by exit and by year, and the data notes. Numbers only: the reading of
them is written by hand.

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
         "exit_high": "高于上沿清仓", "open": "期末仍持有", "closed": "其他"}


def pct(x, d=1):
    return "—" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def ci(o):
    if not o or o.get("theta") is None:
        return "—"
    return f"{pct(o['theta'], 2)}（90% 区间 {pct(o['lo'], 2)} 到 {pct(o['hi'], 2)}，{o['G']} 个年份块）"


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
    s, cmp_ = res["summary"], res["compare"]
    w = []
    w.append(f"# 50 家试点结果（{res['first_day']} 到 {res['snapshot']['last_day']}）\n")
    w.append(f"公司 {len(res['companies'])} 家；替换 {len(res['replacements'])} 家"
             + ("：" + "，".join(f"{x['out']} → {x['in']}（{x['why']}）" for x in res["replacements"])
                if res["replacements"] else "") + "\n")
    w.append("## 组合层面（每家等权一份资金，空仓部分拿 3 个月国债利息）\n")
    w.append("| 方案 | 年化 | 夏普 | 最大回撤 | 平均仓位 | 计划数 |")
    w.append("|---|---|---|---|---|---|")
    for run in [k for k in NAMES if k in s]:
        x = s[run]
        w.append(f"| {NAMES[run]} | {pct(x['cagr'])} | {num(x['sharpe'])} | {pct(x['max_dd'])} | "
                 f"{pct(x.get('held_share'))} | {x.get('plans', '—')} |")
    w.append("")
    for v, c in cmp_.items():
        w.append(f"## {NAMES['method_' + v]}\n")
        w += plan_table([r for r in plans if r["run"] == f"method_{v}"])
        w.append(f"- 每笔平均收益：{ci(c['plan_mean'])}")
        if "placebo" in c:
            pl = c["placebo"]
            w.append(f"- 对随机择时（{pl['replicas']} 次，计划数 {pl['plans']['method']} 对 "
                     f"{pl['plans']['placebo_mean']:.0f}，平均仓位 {pct(pl['held_share']['method'])} 对 "
                     f"{pct(pl['held_share']['placebo_mean'])}）：")
            for k, name in (("plan_mean", "每笔平均收益"), ("cagr", "组合年化"), ("max_dd", "最大回撤")):
                r = pl[k]
                if r.get("placebo_mean") is not None:
                    w.append(f"  - {name}：你的买法 {pct(r['value'], 2)}，随机择时平均 {pct(r['placebo_mean'], 2)}，"
                             f"随机里不低于你的比例 {pct(r['p_one_sided'])}")
            if c.get("plan_vs_placebo", {}).get("theta") is not None:
                w.append(f"  - 每笔收益差（你的买法减随机）：{ci(c['plan_vs_placebo'])}")
        for k, name in (("vs_buy_hold_member", "同 50 家买入持有"), (f"vs_spy_matched_{v}", "同时点换成 SPY"),
                        ("vs_spy", "SPY 买入持有")):
            if k in c:
                w.append(f"- 每年收益减{name}：{ci(c[k]['mean'])}")
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
    if a.checks:
        ch = json.loads((Path(a.checks) / "checks.json").read_text(encoding="utf-8"))
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
