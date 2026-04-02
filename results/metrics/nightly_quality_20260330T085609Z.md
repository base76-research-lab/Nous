# b76 Nightly Quality Report (20260330T085609Z UTC)

## Trace Probe
- return_code: 1
- total: 1
- passed: 0
- pass_rate: 0.0%
- quality_band: rod
- trace_file: /home/bjorn/projects/b76/results/metrics/trace_probe_20260330T074410Z.json

## Runtime Snapshot
- graph: concepts=? relations=? cycle=?
- limbic: lambda=? arousal=?
- knowledge_missing_total: ?
- memory_unconsolidated_total: ?
- memory_semantic_facts: ?

## Mission Scorecard
- mission_active: True
- mission: Gör b76 till ny standard för mätbar, autonom AI-modellering
- north_star: Brain-first AI med evidens
- focus_domains: artificiell intelligens, neurovetenskap
- overall_score: 0.323
- band: rod
- stability: 0.475
- evidence: 0.125
- novelty: 0.000
- queue_health: 0.794
- queue_counts: pending=4 in_progress=0 awaiting_approval=0 done=0 failed=0
- metrics_window: 0

### Mission Recommendations
- Stability: öka timeout/backoff och minska samtidiga riskjobb.
- Evidence: prioritera tasks med validerbar evidens och högre strict gate.
- Novelty: seeda fler tvärdomän-taskar från mission-fokus.

## Probe Output (tail)
```
│   │   response = self._send_single_request(request)             │
│    980 │   │   │   try:                                                      │
│    981 │   │   │   │   for hook in self._event_hooks["response"]:            │
│    982 │   │   │   │   │   hook(response)                                    │
│                                                                              │
│ /home/bjorn/projects/b76/.venv/lib/python3.11/site-packages/httpx/_client.py │
│ :1014 in _send_single_request                                                │
│                                                                              │
│   1011 │   │   │   )                                                         │
│   1012 │   │                                                                 │
│   1013 │   │   with request_context(request=request):                        │
│ ❱ 1014 │   │   │   response = transport.handle_request(request)              │
│   1015 │   │                                                                 │
│   1016 │   │   assert isinstance(response.stream, SyncByteStream)            │
│   1017                                                                       │
│                                                                              │
│ /home/bjorn/projects/b76/.venv/lib/python3.11/site-packages/httpx/_transport │
│ s/default.py:249 in handle_request                                           │
│                                                                              │
│   246 │   │   │   content=request.stream,                                    │
│   247 │   │   │   extensions=request.extensions,                             │
│   248 │   │   )                                                              │
│ ❱ 249 │   │   with map_httpcore_exceptions():                                │
│   250 │   │   │   resp = self._pool.handle_request(req)                      │
│   251 │   │                                                                  │
│   252 │   │   assert isinstance(resp.stream, typing.Iterable)                │
│                                                                              │
│ /home/bjorn/.pyenv/versions/3.11.11/lib/python3.11/contextlib.py:158 in      │
│ __exit__                                                                     │
│                                                                              │
│   155 │   │   │   │   # tell if we get the same exception back               │
│   156 │   │   │   │   value = typ()                                          │
│   157 │   │   │   try:                                                       │
│ ❱ 158 │   │   │   │   self.gen.throw(typ, value, traceback)                  │
│   159 │   │   │   except StopIteration as exc:                               │
│   160 │   │   │   │   # Suppress StopIteration *unless* it's the same except │
│   161 │   │   │   │   # was passed to throw().  This prevents a StopIteratio │
│                                                                              │
│ /home/bjorn/projects/b76/.venv/lib/python3.11/site-packages/httpx/_transport │
│ s/default.py:118 in map_httpcore_exceptions                                  │
│                                                                              │
│   115 │   │   │   raise                                                      │
│   116 │   │                                                                  │
│   117 │   │   message = str(exc)                                             │
│ ❱ 118 │   │   raise mapped_exc(message) from exc                             │
│   119                                                                        │
│   120                                                                        │
│   121 class ResponseStream(SyncByteStream):                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
ConnectError: [Errno 111] Connection refused
```
