# b76 Nightly Quality Report (20260331T002417Z UTC)

## Trace Probe
- return_code: 0
- total: 12
- passed: 6
- pass_rate: 50.0%
- quality_band: rod
- trace_file: /home/bjorn/projects/b76/results/metrics/trace_probe_20260331T003459Z.json

## Runtime Snapshot
- graph: concepts=6323 relations=5405 cycle=4
- limbic: lambda=0.9 arousal=1.032
- knowledge_missing_total: 5210
- memory_unconsolidated_total: 47
- memory_semantic_facts: 4240

## Mission Scorecard
- mission_active: True
- mission: Gör b76 till ny standard för mätbar, autonom AI-modellering
- north_star: Brain-first AI med evidens
- focus_domains: artificiell intelligens, neurovetenskap
- overall_score: 0.391
- band: rod
- stability: 0.612
- evidence: 0.256
- novelty: 0.000
- queue_health: 0.665
- queue_counts: pending=9 in_progress=0 awaiting_approval=0 done=4 failed=7
- metrics_window: 0

### Mission Recommendations
- Evidence: prioritera tasks med validerbar evidens och högre strict gate.
- Novelty: seeda fler tvärdomän-taskar från mission-fokus.

## Probe Output (tail)
```
Trace Probe  cases=12  
set=/home/bjorn/projects/b76/results/eval_set_trace_observability.yaml
✗ q_larynx_link timed out
✗ q_kuzu_crash timed out
✗ q_claim_mix timed out
✗ claim_only_arch timed out
✗ claim_only_observability timed out
✗ assumption_only_data timed out
✓ assumption_only_ops  trace=chat_20260331T003319Z_45bc  plan=Q0/C0/A1  events=3
✓ mixed_research_01  trace=chat_20260331T003329Z_84f8  plan=Q1/C0/A0  events=3
✓ mixed_research_02  trace=chat_20260331T003415Z_6dc0  plan=Q1/C0/A1  events=3
✓ mixed_engineering_01  trace=chat_20260331T003420Z_f310  plan=Q0/C1/A1  
events=3
✓ mixed_engineering_02  trace=chat_20260331T003432Z_e893  plan=Q1/C0/A0  
events=3
✓ world_model_goal  trace=chat_20260331T003443Z_34f4  plan=Q0/C1/A0  events=3

Resultat  6/12 (50.0%)  results/metrics/trace_probe_20260331T003459Z.json
```
