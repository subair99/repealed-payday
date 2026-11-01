#!/usr/bin/env bash
# Pilot sweep: 1 run per variant, every task, for the models given (default: $MODELS).
# Control tasks (t10-t13) run at rung 0 (no written controls) and rung A (written controls).
# t09 (36-48 employees) is skipped for models listed in $EXPENSIVE to limit cost.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
MODELS_TO_RUN="${1:-$MODELS}"
EXPENSIVE="${EXPENSIVE:-openai/gpt-6-astra}"
TEMP="${TEMPERATURE:-none}"
for m in $MODELS_TO_RUN; do
  for t in t06_ambiguous t08_reconcile t09_monthend; do
    if [ "$t" = t09_monthend ] && [[ " $EXPENSIVE " == *" $m "* ]]; then echo "skip $t for $m"; continue; fi
    python run.py --task "$t" --agent "model:$m" --twin both --runs 1 --temperature "$TEMP" || echo "FAILED $t $m"
  done
  for t in t10_bank_change t11_authority t12_memo t13_callback; do
    for h in 0 A; do
      python run.py --task "$t" --agent "model:$m" --twin both --runs 1 --hint "$h" --temperature "$TEMP" || echo "FAILED $t $m $h"
    done
  done
done
python summarize.py
