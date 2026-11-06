"""Regrade recorded traces with the current (final) grader, honestly.

Each recorded episode is replayed against a fresh environment built from the CURRENT task code:
every tool call the model made is re-issued in order and its result compared with what the model
actually saw. Then:

  - every result identical  -> the task is unchanged for this episode, so the final grader is applied
                               to the replayed state ("final grader")
  - any result differs      -> the task changed after this run; the grade recorded at run time is kept
                               and the row is marked "recorded (older task version)"

Usage:  python regrade.py [--dir pilot_results] [--out docs/RESULTS.md]
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter, defaultdict

from env.controls_env import ControlsEnv
from env.payroll_env import PayrollEnv
from grader import grade_controls
from grader.grade import grade
from run import TASKS

DIR = sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else "pilot_results"
OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None


def norm(x):
    return json.loads(json.dumps(x, sort_keys=True))


def regrade_record(r):
    task = TASKS.get(r["task"])
    if task is None or not r.get("transcript"):
        return r["grade"], "recorded"
    matches = [v for v in task.variants(r["twin"], r["hint"]) if v.seed == r["seed"]]
    if not matches:
        return r["grade"], "recorded (older task version)"
    controls = getattr(task, "GRADER", None) == "controls"
    env = (ControlsEnv if controls else PayrollEnv)(matches[0])
    for step in r["transcript"]:
        if not isinstance(step, dict) or "tool" not in step:
            continue
        if norm(env.call(step["tool"], step["args"])) != norm(step["result"]):
            return r["grade"], "recorded (older task version)"
    g = (grade_controls.grade if controls else grade)(env.snapshot(), r["final"], task.CHECK_DISCREPANCIES)
    return g, "final grader"


latest = {}
for f in sorted(glob.glob(f"{DIR}/*.jsonl")):
    recs = []
    for line in open(f):
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    if not recs or not recs[0]["agent"].startswith("model:"):
        continue
    full = {(r["twin"], r["seed"]) for r in recs}
    latest[(recs[0]["task"], recs[0]["agent"][6:], recs[0]["hint"])] = (f, recs, len(full))

lines = ["| task | model | rung | runs | clean pass | pressured pass | critical | failure labels | graded with | run (UTC) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
totals = defaultdict(int)
for key in sorted(latest):
    f, recs, _ = latest[key]
    by = defaultdict(list)
    how = Counter()
    labels = Counter()
    crit = 0
    for r in recs:
        g, h = regrade_record(r)
        how[h] += 1
        by[r["twin"]].append(g["pass"])
        crit += bool(g["critical"])
        if not g["pass"]:
            labels.update(g["labels"])
    rate = lambda xs: f"{sum(xs)}/{len(xs)}" if xs else "-"  # noqa: E731
    graded = ", ".join(f"{k} ×{n}" if len(how) > 1 else k for k, n in how.items())
    labs = ", ".join(f"{k}×{n}" for k, n in labels.most_common()) or "-"
    runs = max(r["run"] for r in recs) + 1
    lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {runs} | {rate(by['clean'])} | {rate(by['pressured'])} "
                 f"| {crit} | {labs} | {graded} | {recs[0]['utc']} |")
    totals["episodes"] += len(recs)
    totals["critical"] += crit

table = "\n".join(lines) + f"\n\nEpisodes: {totals['episodes']}; critical failures: {totals['critical']}\n"
print(table)
if OUT:
    with open(OUT, "w") as fh:
        fh.write(f"# Results (regraded from `{DIR}/` with `python regrade.py --dir {DIR}`)\n\n"
                 "*graded with*: **final grader** = episode replayed against the final task code with identical "
                 "tool results, then graded by the final grader; **recorded (older task version)** = the task "
                 "changed after this run (see docs/DESIGN_LOG.md), so the grade recorded at run time is shown.\n\n")
        fh.write(table)
