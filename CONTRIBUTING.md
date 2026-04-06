# Contributing to NoUse

Welcome — and thank you for considering a contribution to **NoUse**, an epistemic memory layer for LLMs. Whether you're fixing a bug, improving documentation, or proposing a new feature, your help is appreciated.

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
- Environment details (OS, Python version, NoUse version).

## Feature Discussions

Feature ideas and design discussions are welcome! Open a GitHub Issue tagged as a feature request or start a discussion. Describe the use case and the behavior you'd like to see.

## Ways to Contribute Beyond Code

You don't need to write Python to make a meaningful contribution to NoUse.

### Domain Benchmark Question Banks

The current benchmark is intentionally narrow. The hypothesis only holds if it generalises across domains. You can contribute by submitting a domain-specific question bank using the [Domain Benchmark issue template](../../issues/new?template=domain_benchmark.md).

**Format:** A JSON or CSV file with 60 questions in your domain, each with a reference answer. The evaluation script runs against it automatically.

Good domains to add: medicine, law, history, chemistry, climate science, economics, philosophy.

### Integration Examples

If you've built something with NoUse — a LangChain wrapper, a CrewAI integration, a custom daemon plugin — a working example in `examples/` is worth more than a feature request. Open a PR with the script and a one-paragraph explanation.

### Documentation and Tutorials

The gap between "it works" and "people understand it" is large. Contributions welcome:
- Step-by-step tutorials for specific use cases
- Wiki pages explaining architecture decisions
- Translations of the README
- Corrections and clarifications anywhere in the docs

### Research Replication

If you replicate the benchmark on your own domain and get results (even negative ones), open a [GitHub Discussion](../../discussions) in the **Research** category. Null results are useful. Unexpected results are especially welcome.

---

## Maintainer

**Björn Wikström** — [bjorn@base76.se](mailto:bjorn@base76.se)

## Response Times

- **Pull requests** — Reviewed within **1 week**.
- **Issues** — Triaged within **3 days**.

## License

By contributing, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
