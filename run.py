"""Run Task 5 for a fake agent or a real model and write graded results.

Examples:
  python run.py --task t05_remit --agent fake:blind_retry --twin pressured
  python run.py --task t06_ambiguous --agent model:<openrouter-id> --twin both --runs 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

from agents.fakes.more_fakes import FAKES as _MORE
from agents.fakes.t05_fakes import FAKES as _T05
from env.controls_env import ControlsEnv
from env.payroll_env import PayrollEnv
from grader import grade_controls
from grader.grade import grade
from tasks import (t05_remit, t06_ambiguous, t08_reconcile, t09_monthend, t10_bank_change, t11_authority,
                   t12_memo, t13_callback)

FAKES = {**_T05, **_MORE}
TASKS = {t.TASK_ID: t for t in (t05_remit, t06_ambiguous, t08_reconcile, t09_monthend,
                                       t10_bank_change, t11_authority, t12_memo, t13_callback)}


def run_one(task, agent: str, variant, temperature):
    controls = getattr(task, "GRADER", None) == "controls"
    env = (ControlsEnv if controls else PayrollEnv)(variant)
    transcript = None
    if agent.startswith("fake:"):
        final = FAKES[agent.split(":", 1)[1]](env)
    else:
        from agents.llm_agent import run
        final, transcript = run(env, task.prompt(variant.hint_level), task.tools(variant.hint_level),
                                agent.split(":", 1)[1], temperature)
    grader = grade_controls.grade if controls else grade
    return grader(env.snapshot(), final, task.CHECK_DISCREPANCIES), final, transcript


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=list(TASKS), default="t05_remit")
    ap.add_argument("--agent", required=True, help="fake:<name> or model:<openrouter-id>")
    ap.add_argument("--twin", choices=["clean", "pressured", "both"], default="both")
    ap.add_argument("--hint", choices=["0", "A", "B", "C"], default="A",
                    help="ablation rung; 0 = no written controls (tasks t10-t13 only)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--temperature", default="0", help="number, or 'none' to use the provider default")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    task = TASKS[a.task]
    a.temperature = None if str(a.temperature).lower() == "none" else float(a.temperature)

    twins = ["clean", "pressured"] if a.twin == "both" else [a.twin]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = pathlib.Path(a.out) / f"{task.TASK_ID}_{a.agent.replace('/', '_').replace(':', '-')}_{a.hint}_{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {}
    partial = out.with_suffix(".partial")  # renamed to .jsonl only when the whole run completes
    with partial.open("w") as f:
        for twin in twins:
            passes = total = crit = 0
            for v in task.variants(twin, a.hint):
                for r in range(a.runs):
                    g, final, transcript = run_one(task, a.agent, v, a.temperature)
                    total += 1
                    passes += g["pass"]
                    crit += g["critical"]
                    f.write(json.dumps({
                        "task": task.TASK_ID, "twin": twin, "hint": a.hint, "agent": a.agent,
                        "temperature": a.temperature, "seed": v.seed, "n_employees": v.n_employees,
                        "fault_on_call": v.fault_on_call, "run": r, "utc": stamp,
                        "grade": g, "final": final, "transcript": transcript}) + "\n")
            summary[twin] = {"pass_rate": passes / total, "critical": crit, "n": total}
    partial.rename(out)
    if len(twins) == 2:
        summary["pressure_gap_pts"] = round(100 * (summary["clean"]["pass_rate"] - summary["pressured"]["pass_rate"]), 1)
    out.with_suffix(".summary.json").write_text(json.dumps({"agent": a.agent, "hint": a.hint, "runs": a.runs, "temperature": a.temperature, "utc": stamp,
        "max_output_tokens": int(__import__("os").environ.get("MAX_OUTPUT_TOKENS", "16000")), **summary}, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"traces -> {out}")


if __name__ == "__main__":
    main()
