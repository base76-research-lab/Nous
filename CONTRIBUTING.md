# Contributing to Nous

Welcome — and thank you for considering a contribution to **Nous**, a persistent epistemic substrate for AI.

Nous treats language models as the larynx, not the mind. Good contributions help make that claim more legible, more reproducible, and more falsifiable.

Whether you are fixing a bug, improving docs, building benchmark infrastructure, or stress-testing the core thesis, your help matters.

## What Matters Most

- **Epistemic clarity** — make the system's knowledge boundaries, contradictions, and uncertainty easier to inspect.
- **Benchmark rigor** — help us measure what current LLM benchmarks miss.
- **Local-first reliability** — keep the runtime observable, inspectable, and useful on real machines.
- **Conceptual legibility** — help the repo explain what category of system `Nous` is, and what it is not.

## Setting Up the Dev Environment

1. Clone the repository and enter the project directory.
2. Create a virtual environment (recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. Install in editable mode with dev dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. Run the test suite to verify everything works:
   ```bash
   pytest tests/
   ```

## Code Standards

- **Type hints** — All function signatures must include type annotations.
- **Clear naming** — Prefer descriptive variable and function names over abbreviations.
- **Docstrings** — Every public function, class, and module must have a docstring explaining its purpose, parameters, and return value.
- Keep functions focused and files reasonably sized.

## Pull Request Process

1. **Fork** the repository and create a **feature branch** from `main`.
2. Make your changes, ensuring all existing and new **tests pass**.
3. **Submit a PR** with a clear description of what the change does and why.
4. Reference any related issues (e.g., `Closes #42`).

Please keep PRs focused — one logical change per PR makes review faster for everyone.

## Reporting Bugs

Open a [GitHub Issue](../../issues) with:

- A clear title and description.
- Steps to reproduce the problem.
- Expected vs. actual behavior.
- Environment details (OS, Python version, Nous version).

## Feature Discussions

Feature ideas and design discussions are welcome! Open a GitHub Issue tagged as a feature request or start a discussion. Describe the use case and the behavior you'd like to see.

## Ways to Contribute Beyond Code

You do not need to write Python to make a meaningful contribution to Nous.

### Benchmark Datasets and Protocols

The current benchmark work is still intentionally incomplete. The category claim only becomes credible if it survives contact with more domains, better scoring, and harder longitudinal tests.

You can contribute by submitting:

- domain-specific question banks
- gap-detection datasets
- contradiction-injection protocols
- longitudinal evaluation ideas for GDP, LPI, and CLC
- replication runs, including negative results

The [Domain Benchmark issue template](../../issues/new?template=domain_benchmark.md) is still a good starting point.

### Integration Examples and Runtime Experiments

If you've built something with Nous — a LangChain wrapper, a CrewAI integration, a custom daemon plugin, a research workflow, or a model-routing setup — a working example in `examples/` is worth more than a vague feature request. Open a PR with the script and a short explanation.

### Documentation, Wiki, and Explanatory Writing

The gap between "it runs" and "people understand what category of system this is" is still large. Contributions are especially welcome for:
- Step-by-step tutorials for specific use cases
- Wiki pages explaining architecture and benchmark decisions
- Better explanations of the Larynx Problem, FNC-Bench, and epistemic substrate framing
- Translations of the README
- Corrections and clarifications anywhere in the docs

### Research Replication

If you replicate the benchmark on your own domain and get results (even negative ones), open a [GitHub Discussion](../../discussions) in the **Research** category. Null results are useful. Unexpected results are especially welcome.

### Naming and Narrative Cleanup

There are still places in the repo where older `NoUse` naming survives for compatibility or because the cleanup is incomplete. Targeted cleanup PRs are welcome as long as they preserve working APIs where needed and explain the compatibility tradeoff clearly.

---

## Maintainer

**Björn Wikström** — [bjorn@base76.se](mailto:bjorn@base76.se)

## Response Times

- **Pull requests** — Reviewed within **1 week**.
- **Issues** — Triaged within **3 days**.

## License

By contributing, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
