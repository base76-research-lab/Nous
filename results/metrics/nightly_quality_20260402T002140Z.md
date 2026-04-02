# b76 Nightly Quality Report (20260402T002140Z UTC)

## Trace Probe
- return_code: 0
- total: 12
- passed: 12
- pass_rate: 100.0%
- quality_band: gron
- trace_file: /home/bjorn/projects/b76/results/metrics/trace_probe_20260402T002152Z.json

## Runtime Snapshot
- graph: concepts=19093 relations=21520 cycle=829
- limbic: lambda=0.471 arousal=0.749
- knowledge_missing_total: 17947
- memory_unconsolidated_total: 40
- memory_semantic_facts: 12000

## Mission Scorecard
- mission_active: True
- mission: det jag byggt åt dig i brain och b76 är en artifakt som är lika plastisk och innehåller samma funktioner som en mänsklig hjärna
- north_star: det jag byggt åt dig i brain och b76 är en artifakt som är lika plastisk och innehåller samma funktioner som en mänsklig hjärna
- focus_domains: artificiell intelligens, kognitiv arkitektur
- overall_score: 0.478
- band: rod
- stability: 0.925
- evidence: 0.186
- novelty: 0.000
- queue_health: 0.656
- queue_counts: pending=16 in_progress=0 awaiting_approval=0 done=4 failed=0
- metrics_window: 0

### Mission Recommendations
- Evidence: prioritera tasks med validerbar evidens och högre strict gate.
- Novelty: seeda fler tvärdomän-taskar från mission-fokus.

## Probe Output (tail)
```
Trace Probe  cases=12  
set=/home/bjorn/projects/b76/results/eval_set_trace_observability.yaml
✓ q_larynx_link  trace=chat_20260402T002141Z_375a  plan=Q1/C0/A0  events=10
✓ q_kuzu_crash  trace=chat_20260402T002142Z_231e  plan=Q1/C0/A0  events=10
✓ q_claim_mix  trace=chat_20260402T002142Z_713e  plan=Q1/C1/A0  events=10
✓ claim_only_arch  trace=chat_20260402T002143Z_ed0e  plan=Q0/C1/A0  events=10
✓ claim_only_observability  trace=chat_20260402T002144Z_62b4  plan=Q0/C1/A0  
events=10
✓ assumption_only_data  trace=chat_20260402T002144Z_98a3  plan=Q0/C0/A1  
events=10
✓ assumption_only_ops  trace=chat_20260402T002145Z_d877  plan=Q0/C0/A1  
events=10
✓ mixed_research_01  trace=chat_20260402T002145Z_90da  plan=Q1/C0/A0  events=10
✓ mixed_research_02  trace=chat_20260402T002146Z_9c69  plan=Q1/C0/A1  events=10
✓ mixed_engineering_01  trace=chat_20260402T002148Z_20ae  plan=Q0/C1/A1  
events=10
✓ mixed_engineering_02  trace=chat_20260402T002151Z_99af  plan=Q1/C0/A0  
events=10
✓ world_model_goal  trace=chat_20260402T002152Z_200b  plan=Q0/C1/A0  events=10

Resultat  12/12 (100.0%)  results/metrics/trace_probe_20260402T002152Z.json
```
