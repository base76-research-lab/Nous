---
name: Domain Benchmark Contribution
about: Submit a domain-specific question bank to extend the NoUse benchmark
title: "[Benchmark] <Domain name>"
labels: benchmark, help wanted
assignees: ''
---

## Domain

<!-- What domain does this question bank cover? e.g. Medicine, Law, Climate Science -->

## File

<!-- Attach or link to your question bank file. Accepted formats: JSON, CSV -->

Format expected:

```json
[
  {
    "question": "What is the primary mechanism of action of beta blockers?",
    "answer": "Competitive antagonism of beta-adrenergic receptors",
    "domain": "medicine"
  }
]
```

Minimum: **60 questions**. More is better. Reference answers should be factual and verifiable.

## Source

<!-- Where did the questions come from? Textbook, exam bank, your own expertise? -->

## Notes

<!-- Anything else the maintainer should know about this domain or the question set -->

---

Once submitted, the maintainer will run `eval/run_eval.py` against your question bank and publish the results in a GitHub Discussion under **Research**.
