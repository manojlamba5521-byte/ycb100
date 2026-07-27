# Contributing to ConsequenceBench

ConsequenceBench accepts fixes, new controls, evaluator tooling, documentation, and
candidate scenario families. A change that makes the benchmark easier for one
specific solver without improving validity will not be accepted.

## Development Setup

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
python -m build
python -m twine check dist/*
```

Public controls must run without network access, credentials, a governance
product, or access to evaluator-private files.

## Pull Request Requirements

Every behavioral change must include:

1. A failing regression demonstrating the issue.
2. The smallest implementation change that closes it.
3. Updated contracts and documentation when schemas or scoring change.
4. Deterministic evidence from the supported test matrix.
5. A statement describing benchmark-validity and compatibility impact.

Scenario additions or changes must update the narrative catalog, regenerate the
scenario manifest, and preserve exactly 20 scenarios per domain and five per
governance lens.

Never commit credentials, provider responses containing private data, SQLite
state, model caches, or unrestricted agent transcripts. Report security issues
using `SECURITY.md`.

Benchmark results are reviewed through the
[result-submission contract](docs/SUBMIT_RESULTS.md). Reproductions, domain
reviews, and red teams should begin with the
[independent-evaluation contract](docs/INDEPENDENT_EVALUATION.md).
