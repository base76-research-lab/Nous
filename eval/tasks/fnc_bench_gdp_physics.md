Generate 20 factual questions about physics for the FNC-Bench GDP (Gap Detection Precision) benchmark.

Rules:
- 10 questions must be answerable from standard undergraduate physics knowledge
- 10 questions must require highly specialized knowledge that a typical LLM would NOT reliably know
  (obscure experimental results, unpublished findings, very specific numerical constants, etc.)
- Label each question: "in_scope" or "out_of_scope"
- For out_of_scope questions, briefly note WHY they are outside typical knowledge

Output JSON only:
{"questions": [{"q": "...", "scope": "in_scope|out_of_scope", "note": "..."}]}
