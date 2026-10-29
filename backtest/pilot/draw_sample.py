"""Draw the 50-company sample for the forward-P/E band pilot (fundamental buy method).

Pool: ladder V3 entities.json, kind "pool" (S&P 500 members on some day 2008-01..2025-10 with FMP bars
covering membership + 3 years before; without the seven large caps and the 96 previously tested stocks).
Excluded: every company V3 drew (main, held out, the six reserve batches, the spares), so no V3 list is touched.
Stratified by FMP sector, largest remainder in proportion to the remaining pool, seeded order per stratum.
"""
import json, sys
from pathlib import Path
import numpy as np

V3 = Path(sys.argv[1])
SEED, N, SPARES = 20261029, 50, 3
ents = json.loads((V3 / "entities.json").read_text())["entities"]
s = json.loads((V3 / "sample.json").read_text())
v3_drawn = set(s["drawn"])            # main incl. mag7, holdout, reserves, spares
pool = {}
for k in sorted(ents):
    if ents[k]["kind"] == "pool" and k not in v3_drawn:
        pool.setdefault(ents[k]["sector"], []).append(k)
total = sum(len(v) for v in pool.values())
quota = {k: N * len(v) / total for k, v in pool.items()}
alloc = {k: int(q) for k, q in quota.items()}
for k in sorted(quota, key=lambda k: (-(quota[k] - alloc[k]), k))[: N - sum(alloc.values())]:
    alloc[k] += 1
rng = np.random.default_rng(SEED)
order = {k: [v[i] for i in rng.permutation(len(v))] for k, v in sorted(pool.items())}
sample = [x for k in order for x in order[k][: alloc[k]]]
spares = {k: order[k][alloc[k]: alloc[k] + SPARES] for k in order}
last = lambda e: max(b for a, b in e["spans"])
out = {"seed": SEED, "rule": __doc__.strip(), "pool_size": total,
       "pool_by_sector": {k: len(v) for k, v in pool.items()}, "alloc": alloc,
       "sample": sample, "spares": spares, "order": order,
       "records": {k: ents[k] for k in sample + [x for v in spares.values() for x in v]}}
Path("sample_fa_pilot.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print("pool", total, out["pool_by_sector"])
print("alloc", alloc)
left = [k for k in sample if last(ents[k]) < "2026-08-01"]
print(f"{len(left)} of {len(sample)} left the index before 2026-08:", " ".join(left))
for k in sample:
    e = ents[k]
    print(f"{k:6s} series={e['series']!s:6s} {e['sector']:24s} spans={e['spans']} bars_from={e['bars_from']}")
