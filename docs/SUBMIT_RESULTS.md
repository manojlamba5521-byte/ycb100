# Submit Results

ConsequenceBench accepts reproducible development-result submissions through a
GitHub issue. A submission is an evidence review request, not an automatic
leaderboard entry.

## Required Artifacts

Provide immutable public locations and SHA-256 hashes for:

1. Benchmark commit, package, scenario manifest, and world pack.
2. Complete candidate implementation or runnable container.
3. Agent manifest, model configuration, system prompt, and tool schemas.
4. Budget, retry, seed, event, and fault manifests.
5. Every row-level result and attempt, including failures.
6. Deterministic score receipt and summary.
7. Environment and hardware manifest.
8. Secret-scan and license report.

Do not submit screenshots as evidence. Do not upload credentials, private
provider responses, customer data, model cache contents, or evaluator-private
oracle material.

## Required Reporting

Report direct-agent capability, governance conformance, and frozen-candidate
incremental effect as separate studies. For each applicable study, include:

- denominator and confidence interval for every rate;
- exact decision, correct consequence, and resolved task;
- unsafe, duplicate, and missing legitimate effects;
- evidence, readback, recovery, obligation, and compensation failures;
- all candidate, provider, evaluator, and infrastructure failures;
- paired recoveries and paired regressions;
- tool calls, retries, tokens when available, and elapsed time.

Unknown or excluded attempts remain visible. Negative counters and denominator
changes invalidate the submission.

## Evidence Labels

Use exactly one:

- `SELF_REPORTED_LOCAL_DEVELOPMENT_EVIDENCE`
- `INDEPENDENTLY_REPRODUCED_DEVELOPMENT_EVIDENCE`
- `EXTERNALLY_CUSTODIED_QUALIFICATION_EVIDENCE`

The last label is unavailable unless the complete qualification protocol has
been satisfied. The repository's current published rows use the first label.

## Review Process

Open a **Result submission** issue and complete every field. Maintainers:

1. reopen all referenced artifacts;
2. verify hashes, schemas, denominators, and commit bindings;
3. recompute hard counters and score summaries;
4. check candidate isolation and paired-study equivalence;
5. record unresolved limitations;
6. accept, request correction, or reject with a public reason.

Accepted development rows remain unranked unless a published ranking protocol
applies. Maintainers may remove a row if its artifacts disappear or a validity
defect is discovered.
