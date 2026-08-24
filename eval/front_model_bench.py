#!/usr/bin/env python3
"""Ad hoc benchmark: which local model is best suited as the Jarvis
conversational front-end (not extraction, not deep reasoning).

Criteria that matter for this role: latency (must feel conversational),
correct short-form instruction-following, and NOT trying to do heavy
work itself (should stay in scope, a router will handle escalation).
"""
import json
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434/api/chat"
MODELS = [
    "gemma4:e2b",
    "dolphin3:8b",
    "qwen3.5:9b",
    "lfm2.5:latest",
    "richardyoung/qwen3-8b-abliterated:Q4_K_M",
]

SYSTEM = (
    "Du är Jarvis, en lokal röststyrd assistent för Björn. Svara kort, "
    "naturligt och på svenska. Om en uppgift är stor (skriv kod, analysera "
    "ett helt dokument, större projekt) ska du INTE försöka göra den själv "
    "- säg bara att du skickar den vidare för bearbetning."
)

PROMPTS = [
    ("smalltalk", "God morgon! Hur mår du idag?"),
    ("system_awareness", "Vilken zon i mitt IIC-system ska ett nytt forskningsprojekt läggas i?"),
    ("simple_command", "Påminn mig om mötet med Anna klockan 15 imorgon."),
    ("escalation_judgement", "Kan du skriva om hela min artikel om digital sociologi och förbättra argumentationen?"),
]

TIMEOUT = 50

def call(model, prompt):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "options": {"num_predict": 200},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
        elapsed = time.monotonic() - t0
        content = data.get("message", {}).get("content", "")
        return {"ok": True, "elapsed_sec": round(elapsed, 2), "content": content.strip()}
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return {"ok": False, "elapsed_sec": round(elapsed, 2), "error": str(exc)}

results = {}
for model in MODELS:
    print(f"=== {model} ===", flush=True)
    results[model] = {}
    for tag, prompt in PROMPTS:
        r = call(model, prompt)
        results[model][tag] = r
        status = "OK" if r["ok"] else "FAIL"
        print(f"  [{status}] {tag}: {r['elapsed_sec']}s", flush=True)
        if r["ok"]:
            print(f"    -> {r['content'][:160]!r}", flush=True)
        else:
            print(f"    -> {r['error']}", flush=True)

out_path = "/tmp/claude-1000/-home-bjornwikstrom/a283a515-2bb8-4771-9c04-304800722527/scratchpad/jarvis_front_bench_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\nSaved to {out_path}")
