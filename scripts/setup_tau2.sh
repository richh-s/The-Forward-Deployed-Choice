#!/usr/bin/env bash
# Clone and configure tau2-bench, then run a 3-task smoke test.
# Run from the project root.
set -e

echo "=== Cloning tau2-bench ==="
if [ ! -d "tau2-bench" ]; then
    git clone https://github.com/sierra-research/tau2-bench tau2-bench
fi

cd tau2-bench
pip install -r requirements.txt
cd ..

echo ""
echo "=== Smoke test: 3 tasks ==="
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://openrouter.ai/api/v1}"
export OPENAI_API_KEY="${OPENROUTER_API_KEY}"

cd tau2-bench
python run_eval.py \
    --domain retail \
    --num_tasks 3 \
    --model openai/gpt-4o-mini \
    --output_dir ./eval/smoke/

echo ""
echo "Smoke test complete. Check output above for pass@1 > 0."
echo "If 0%, switch model or check OPENROUTER_API_KEY."
echo ""
echo "To run full dev slice (30 tasks, 5 trials):"
echo "  python run_eval.py --domain retail --num_tasks 30 --trials 5 \\"
echo "    --model openai/gpt-4o-mini --output_dir ./eval/"
