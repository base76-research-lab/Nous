# b76 Nightly Quality Report (20260401T002031Z UTC)

## Trace Probe
- return_code: 0
- total: 12
- passed: 10
- pass_rate: 83.3%
- quality_band: gul
- trace_file: /home/bjorn/projects/b76/results/metrics/trace_probe_20260401T002859Z.json

## Runtime Snapshot
- graph: concepts=13025 relations=15284 cycle=212
- limbic: lambda=0.471 arousal=0.749
- knowledge_missing_total: 12062
- memory_unconsolidated_total: 59
- memory_semantic_facts: 12000

## Mission Scorecard
- mission_active: True
- mission: det jag byggt åt dig i brain och b76 är en artifakt som är lika plastisk och innehåller samma funktioner som en mänsklig hjärna
- north_star: det jag byggt åt dig i brain och b76 är en artifakt som är lika plastisk och innehåller samma funktioner som en mänsklig hjärna
- focus_domains: artificiell intelligens, kognitiv arkitektur
- overall_score: 0.414
- band: rod
- stability: 0.795
- evidence: 0.194
- novelty: 0.000
- queue_health: 0.514
- queue_counts: pending=21 in_progress=0 awaiting_approval=0 done=4 failed=7
- metrics_window: 0

### Mission Recommendations
- Evidence: prioritera tasks med validerbar evidens och högre strict gate.
- Novelty: seeda fler tvärdomän-taskar från mission-fokus.
- Queue health: rensa backlog och hantera pending HITL-interrupts dagligen.

## Probe Output (tail)
```
Trace Probe  cases=12  
set=/home/bjorn/projects/b76/results/eval_set_trace_observability.yaml
✓ q_larynx_link  trace=chat_20260401T002032Z_c7f1  plan=Q1/C0/A0  events=3
✓ q_kuzu_crash  trace=chat_20260401T002114Z_592c  plan=Q1/C0/A0  events=3
✗ q_claim_mix timed out
✓ claim_only_arch  trace=chat_20260401T002318Z_0851  plan=Q0/C1/A0  events=3
✓ claim_only_observability  trace=chat_20260401T002401Z_b63f  plan=Q0/C1/A0  
events=3
✗ assumption_only_data timed out
✓ assumption_only_ops  trace=chat_20260401T002640Z_b2b0  plan=Q0/C0/A1  events=3
✓ mixed_research_01  trace=chat_20260401T002659Z_0b52  plan=Q1/C0/A0  events=3
✓ mixed_research_02  trace=chat_20260401T002805Z_3373  plan=Q1/C0/A1  events=3
✓ mixed_engineering_01  trace=chat_20260401T002807Z_0e92  plan=Q0/C1/A1  
events=3
✓ mixed_engineering_02  trace=chat_20260401T002819Z_3abc  plan=Q1/C0/A0  
events=3
✓ world_model_goal  trace=chat_20260401T002834Z_4331  plan=Q0/C1/A0  events=3

Resultat  10/12 (83.3%)  results/metrics/trace_probe_20260401T002859Z.json
```
