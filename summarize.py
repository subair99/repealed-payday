"""Print a results table from results/*.summary.json (latest run per task/model/rung).

Usage: python summarize.py [--all]   (--all keeps every run instead of only the latest)
"""
import glob
import json
import sys

RESULTS = sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else "results"


def episode_cost(rec):
    return sum((x.get("usage") or {}).get("cost") or 0 for x in (rec.get("transcript") or [])
               if isinstance(x, dict))
from collections import Counter

rows = {}
for f in sorted(glob.glob(f"{RESULTS}/*.jsonl")):
    recs = []
    for line in open(f):
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    if not recs or not recs[0]["agent"].startswith("model:"):
        continue
    r0 = recs[0]
    key = (r0["task"], r0["agent"][6:], r0["hint"]) if "--all" not in sys.argv else (r0["task"], r0["agent"][6:], r0["hint"], f)
    by = {}
    for r in recs:
        by.setdefault(r["twin"], []).append(r)
    labels = Counter(lab for r in recs if not r["grade"]["pass"] for lab in r["grade"]["labels"])
    rows[key] = {
        "clean": by.get("clean", []), "pressured": by.get("pressured", []), "labels": labels,
        "utc": r0["utc"], "runs": max(r["run"] for r in recs) + 1,
        "cost": sum(episode_cost(r) for r in recs)}

def rate(lst):
    return f"{sum(r['grade']['pass'] for r in lst)}/{len(lst)}" if lst else "-"

print("| task | model | rung | runs | clean pass | pressured pass | critical | failure labels | cost USD | utc |")
print("|---|---|---|---|---|---|---|---|---|---|")
for key in sorted(rows):
    v = rows[key]
    crit = sum(r["grade"]["critical"] for r in v["clean"] + v["pressured"])
    labs = ", ".join(f"{k}×{n}" for k, n in v["labels"].most_common()) or "-"
    print(f"| {key[0]} | {key[1]} | {key[2]} | {v['runs']} | {rate(v['clean'])} | {rate(v['pressured'])} | {crit} "
          f"| {labs} | {v['cost']:.2f} | {v['utc']} |")
print(f"\nTotal measured cost: ${sum(v['cost'] for v in rows.values()):.2f}")
