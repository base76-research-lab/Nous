# Evaluation Results Index

This index distinguishes complete, auditable runs from exploratory or invalid
runs. A result is not treated as evidence of an effect unless its dataset,
configuration, code revision, raw outputs, and scoring record are available.

## Current Status

The repository currently has no complete, independently scored benchmark that
demonstrates a Nous improvement over a bare model.

## Saved Runs

| Run | Status | Model | Questions | Summary |
| --- | --- | --- | ---: | --- |
| `truthfulqa_run2_20260824` | exploratory, incomplete judge records | NVIDIA Nemotron 3.5 Lightning | 40 per condition | MC1: bare 50.0%, RAG 50.0%, Nous-meta 47.5%; judge validity must be checked before comparison |
| `longmemeval_20260824_000702` | valid negative result for this task shape | GPT-OSS 120B via Groq | 24 | bare 4.2%, Nous 0.0%; the adapter's relation vocabulary does not represent LongMemEval's personal-fact task |
| `run_20260403_094211` | historical domain-specific pilot; incomplete provenance | Cerebras Llama 3.1 8B / Groq Llama 3.3 70B | 60 | Raw records report 46.1% bare, 96.1% Nous, 46.7% larger baseline; custom scoring and no immutable manifest, dataset hash, or independent scorer |

## Reproduction Requirements

Every future public result must record:

- commit SHA and package version
- dataset identifier and hash
- model, provider, prompts, sampling settings, and seed
- isolated graph/bootstrap state and context coverage
- raw model and judge responses
- scorer version and invalid-record count
- per-question results and a human-readable summary

Incomplete judge output must be reported as invalid data, never silently counted
as a zero score.