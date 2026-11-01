#!/usr/bin/env bash
# One command: grader gate, then every model in $MODELS on both twins, then the ablation ladder.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
: "${MODELS:?set MODELS in .env}"
RUNS="${RUNS:-3}"
TEMP="${TEMPERATURE:-0}"   # set TEMPERATURE=none for models that reject it
python -m pytest -q                      # grader gate: abort if any fake agent scores wrongly
TASKS="${TASKS:-t05_remit t06_ambiguous t08_reconcile t09_monthend t10_bank_change t11_authority t12_memo}"
for t in $TASKS; do
  for m in $MODELS; do
    python run.py --task "$t" --agent "model:$m" --twin both --runs "$RUNS" --temperature "$TEMP"
  done
done
# Ablation rungs B and C: run only on tasks/models whose pressured twin failed, e.g.
#   python run.py --task t06_ambiguous --agent model:<id> --twin pressured --hint B --runs 3 --temperature none
