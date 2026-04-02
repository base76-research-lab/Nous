# Results Directory

This directory stores reproducible study outputs for b76.

## Layout
- `baselines/` - baseline run artifacts (`run_baseline.sh` output)
- `ablation/` - controlled ablation outputs
- `longitudinal/` - continual-learning and retention studies
- `metrics/` - aggregated metric snapshots
- `summaries/` - weekly/monthly synthesis notes
- `templates/` - run manifest templates
- `eval_set_trace_observability.yaml` - problem set for trace/attack-plan verification

## Rule
Every research iteration should produce:
1. a code/config delta
2. a saved result artifact in this directory
