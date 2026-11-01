#!/usr/bin/env bash
# FINAL RUN (~$40-50 on OpenRouter). Every reported number comes from this script, on frozen code.
# Before running: move pilot results aside so the final table only contains final runs:
#   mv results pilot_results && mkdir results
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
if ls results/*.jsonl >/dev/null 2>&1; then
  echo "results/ already has traces. Move them first:  mv results pilot_results && mkdir results"; exit 1
fi
python -m pytest -q    # grader gate must pass before any model is run
DS=deepseek/deepseek-v4-pro-0813; GEM=google/gemini-4-argon; OPUS=anthropic/claude-opus-5.5; GPT=openai/gpt-6-astra
r() { python run.py --task "$1" --agent "model:$2" --twin both --runs "$3" --hint "$4" --temperature none \
      || echo "FAILED $1 $2 rung $4"; }

# Block 1 (~$15): DeepSeek V4 Pro, all four fraud-control tasks, rung 0 and rung A, 3 runs.
for t in t10_bank_change t11_authority t12_memo t13_callback; do for h in 0 A; do r $t $DS 3 $h; done; done

# Block 2 (~$20): headline task t13 at rung 0 (no written controls), 3 runs, every frontier model.
for m in $GEM $OPUS $GPT; do r t13_callback $m 3 0; done

# Block 3 (~$5): t11 (incl. the invoice-redirection variant) at rung 0, 1 run, Gemini and Opus.
for m in $GEM $OPUS; do r t11_authority $m 1 0; done

# Block 4 (~$2): control task t05 (timeout after commit), 1 run, the two cheapest models.
for m in $DS $GEM; do r t05_remit $m 1 A; done

python summarize.py | tee results/SUMMARY.md
