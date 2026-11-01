"""Print every failed episode for a model (latest trace file per task and rung), with the tool
calls that matter, so each failure can be checked by hand before it is counted.

Usage: python inspect_failures.py <model-substring> [task-substring]
"""
import glob
import json
import sys

model = sys.argv[1]
task_filter = sys.argv[2] if len(sys.argv) > 2 else ""
KEY_TOOLS = {"read_inbox", "verify_bank_change", "get_approval", "post_payment", "get_employee_contact",
             "call_phone", "get_payment_status"}

latest = {}
for f in sorted(glob.glob(f"results/*{model.replace('/', '_')}*.jsonl")):
    if task_filter and task_filter not in f:
        continue
    try:
        first = json.loads(open(f).readline())
    except (json.JSONDecodeError, ValueError):
        continue  # empty or broken file from an interrupted run
    latest[(first["task"], first["hint"])] = f

for (task, hint), f in sorted(latest.items()):
    for line in open(f):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        g = r["grade"]
        if g["pass"]:
            continue
        print(f"\n=== {task} rung {hint} | {r['twin']} | seed {r['seed']} | labels {g['labels']}")
        for k in ("missing", "duplicated", "wrong_amount", "diverted", "wrong_account", "unauthorized",
                  "missing_extras", "claim_issue", "recon_issue"):
            if g.get(k):
                print(f"  {k}: {g[k]}")
        for x in r["transcript"] or []:
            if "tool" not in x:
                continue
            res = x["result"]
            if x["tool"] in KEY_TOOLS or "error" in res:
                print(f"  {x['tool']} {json.dumps(x['args'])[:160]} -> {json.dumps(res)[:180]}")
        print(f"  FINAL: {(r['final'] or '')[:700]}")
