# ConsequenceBench

**Evaluating evidence-grounded agents under real-world consequences.**

ConsequenceBench is a universal synthetic benchmark for consequential AI agents. It
tests whether an agent investigates the right evidence, chooses the right
action, avoids unsafe effects, preserves legitimate effects, recovers from
faults, and proves outcomes through independent readback.

The benchmark is agent-, model-, framework-, and governance-system-neutral.
No vendor-specific governance adapter is included in this repository.

> **Release status:** `DEVELOPMENT_PREVIEW_NOT_QUALIFIED`
>
> ConsequenceBench 0.1.0 is engineering and research infrastructure. It is not a
> production-safety certification, regulatory assessment, or sealed benchmark
> qualification.

## What It Measures

ConsequenceBench keeps three studies separate:

1. **Direct Agent Capability** measures an arbitrary agent acting directly in
   evaluator-owned synthetic worlds.
2. **Governance Conformance** measures whether a named governance build
   enforces its declared lifecycle, evidence, authorization, execution,
   readback, obligation, and compensation contracts.
3. **Frozen-Candidate Incremental Effect** replays the exact same immutable
   candidate through direct and governed arms to isolate the governance layer's
   effect.

Never merge these tracks into one score. Report task correctness, consequence
correctness, unsafe effects, legitimate-effect preservation, evidence
grounding, recovery, and hard failures separately.

## Development Leaderboard

The [development leaderboard](docs/LEADERBOARD.md) publishes three completed
100-world paired studies across six configurations: Gemma4 e4b, Gemini 3.6
Flash, and GPT-5.6 Sol, each run directly and with Yuvin as the declared
governance layer. Its machine-readable receipt is
[`results/development_leaderboard.v1.json`](results/development_leaderboard.v1.json).

The leaderboard builder recomputes published counters from every row in the
source reports and rejects inconsistent summaries. These locally operated runs
remain unranked `SELF_REPORTED_LOCAL_DEVELOPMENT_EVIDENCE`; they are not model
ratings, safety certifications, or independent qualification results.

<!-- consequencebench-leaderboard:start -->
> **Evidence status:** `SELF_REPORTED_LOCAL_DEVELOPMENT_EVIDENCE`

| Candidate | Exact decision (Direct -> Yuvin) | Correct consequence (Direct -> Yuvin) | Unsafe effects (Direct -> Yuvin) |
| --- | ---: | ---: | ---: |
| GPT-5.6 Sol (xhigh) | 60/100 -> 69/100 | 79/100 -> 99/100 | 21/70 -> 0/70 |
| Gemini 3.6 Flash | 32/100 -> 58/100 | 41/100 -> 100/100 | 59/70 -> 0/70 |
| Gemma4 e4b | 19/100 -> 34/100 | 34/100 -> 92/100 | 63/70 -> 0/70 |

All three governed configurations recorded zero unsafe simulated effects.
See the [full leaderboard](docs/LEADERBOARD.md) for six configuration
rows, exact recoveries, regressions, tool calls, evidence hashes, and
qualification limits.
<!-- consequencebench-leaderboard:end -->

## Benchmark Scope

The public corpus contains 100 canonical scenarios: 20 each for banking,
healthcare, cybersecurity, energy, and software delivery. Every domain contains
five scenarios for each governance lens:

- authority and policy;
- evidence and provenance;
- execution and recovery;
- delayed consequence, obligation, and compensation.

The canonical Consequence Lifecycle pack materializes base, causal-sister, and
invariance-sister variants for 300 immutable worlds. Worlds include forged and stale records, identity collisions, conflicting
authority, time-sensitive policy changes, long noisy histories, partial
effects, retries, crash windows, delayed readback, and compensating actions.
All external effects are simulated and evaluator-observable.

The canonical machine-readable identity map is packaged as
`adaptive_causal/data/archetypes.v1.json`. It binds every narrative catalog ID
to exactly one executable development-world family. Catalog baseline outcomes
and generated variant decisions are deliberately distinct and are never
silently compared as the same track.

## Quick Start

Python 3.11 or newer is required.

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
consequencebench validate-scenarios
consequencebench public-controls
consequencebench pressure-controls
consequencebench lifecycle-controls
consequencebench lifecycle-reference-controls
```

These commands require no model, provider key, governance product, or network
access. They validate benchmark structure; they do not evaluate an agent or
produce qualification evidence.

Materialize and verify the deterministic 300-world lifecycle pack:

```bash
consequencebench lifecycle-materialize-pack --output-dir release/lifecycle-pack
consequencebench lifecycle-verify-pack \
  --receipt release/lifecycle-pack/consequencebench-lifecycle-pack.json
```

Run the public regression gate:

```bash
python -m pytest \
  tests/test_public_repository.py \
  tests/test_scenario_manifest.py \
  tests/test_adaptive_causal_portable_entrypoint.py \
  tests/test_adaptive_causal_package_isolation.py
```

## Evaluate an Agent

Agents participate through a JSONL subprocess adapter. The evaluator sends an
episode, owns all tools and source state, enforces budgets, records every
attempt, and scores the resulting trace with a deterministic oracle. Candidate
code must not read repository files, evaluator state, other-arm traces, or
private oracle material.

```bash
consequencebench pressure-agent \
  --agent-manifest agent-manifest.json \
  --agent-command-file agent-command.json \
  --campaign-id my-development-run \
  --out result.json
```

Run a candidate that owns the complete mutating consequence lifecycle:

```bash
consequencebench lifecycle-agent \
  --agent-command-json '["python","my_lifecycle_agent.py"]' \
  --campaign-id my-lifecycle-run \
  --out lifecycle-result.json
```

See the [Consequence Lifecycle protocol](docs/CONSEQUENCE_LIFECYCLE_PROTOCOL.md),
[operator guide](docs/YCB100_OPERATOR_GUIDE.md), and
[evaluator handbook](docs/YCB100_EVALUATOR_HANDBOOK.md) before publishing
results.

## Governance-System Studies

The universal wheel contains no governance-product runtime, dashboard,
provider, or credential dependency. It includes the product-neutral
deterministic oracles, lifecycle contracts, and paired-study protocol needed to
evaluate a governance system. Product integrations must live outside this
repository and must bind the exact benchmark artifact, candidate artifact, and
governance-system build used for the run.

An external governed adapter must preserve the frozen candidate proposal, world
snapshot, model, tools, budgets, faults, and retry policy. It may mediate
consequences, return structured proof holds, and expose independently measurable
readback, but it may not edit candidate reasoning or oracle truth.

## Repository Layout

```text
src/                  canonical installable public implementation
tests/                public and benchmark-development regressions
scripts/              evaluator, evidence, and release commands
docs/                 protocol, scoring, operations, and limitations
results/               public summary receipts for completed development runs
runs/                  ignored raw local development evidence
.github/               CI and contribution templates
```

The public wheel excludes vendor-specific arms and private qualification evidence.
The deterministic repository exporter also excludes local runs, databases,
caches, provider experiments, and historical research controls.

## Compatibility Identifiers

The `ycb100` CLI alias and `ycb100.*` machine schema identifiers remain
supported for receipts produced before the ConsequenceBench research rename.
They are compatibility contracts, not the public benchmark name. New operator
documentation and examples use `consequencebench`.

## Build a Clean Release

```bash
python -m build --sdist --wheel
python -m twine check dist/*
python scripts/build_public_repository.py --out release/consequencebench-0.1.0
```

The exporter uses an explicit allowlist, scans credential-like markers, hashes
every source file, and creates a deterministic ZIP plus integrity receipt.
Always publish the generated release archive, never a ZIP of the working
directory.

## Result Reporting

Every public result must include:

- ConsequenceBench version, source commit, wheel hash, and scenario-manifest hash;
- complete agent implementation and model configuration hashes;
- tool policy, prompt, budget, retry, fault, seed, and trial manifests;
- all attempts, including malformed outputs and timeouts;
- separate official scorecards for the selected study tracks;
- hard counters and confidence intervals;
- an explicit `DEVELOPMENT_ONLY` or independently qualified claim label.

LLM reviewers may explain traces but cannot change deterministic hard scores.

## Documentation

- [Benchmark protocol](docs/YCB100_BENCHMARK_PLAN.md)
- [Consequence Lifecycle protocol](docs/CONSEQUENCE_LIFECYCLE_PROTOCOL.md)
- [Development leaderboard](docs/LEADERBOARD.md)
- [100-scenario catalog](docs/CATALOG.md)
- [Scoring](docs/SCORING.md)
- [Threat model](docs/YCB100_THREAT_MODEL.md)
- [Operator guide](docs/YCB100_OPERATOR_GUIDE.md)
- [Evaluator handbook](docs/YCB100_EVALUATOR_HANDBOOK.md)
- [Limitations](docs/LIMITATIONS.md)
- [Qualification requirements](docs/YCB100_QUALIFICATION_PLAN.md)
- [Documentation index](docs/INDEX.md)

## License

Code and documentation are available under the [MIT License](LICENSE).
