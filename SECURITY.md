# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in Nous, please report it responsibly:

**Email:** bjorn@base76.se

- **Do NOT** open public GitHub issues for security vulnerabilities.
- We will acknowledge your report within 72 hours.
- We follow a 90-day coordinated disclosure policy.

## Security Practices

- All code is reviewed before merge.
- Dependencies are monitored for known CVEs.
- No secrets are committed to source code.

## Data Handling

Nous is **local-first** by design:

- Knowledge graphs are stored locally on your machine.
- **No telemetry.** Nous does not phone home or collect usage data.
- **No cloud dependency.** The daemon runs entirely on your hardware.
- API keys for LLM providers are passed at runtime — never stored in the graph.
- Graph data is stored unencrypted in SQLite. Encryption at rest is the user's responsibility.

## Supported Versions

| Version | Supported |
| ------- | :-------: |
| 0.3.x   | ✅        |
| < 0.3   | ✗         |
