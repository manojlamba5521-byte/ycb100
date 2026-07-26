# YCB-100 Threat Boundary

Status: local development boundary implemented. This document is not a sealed
evaluator attestation, penetration-test result, model qualification, or safety
certificate.

The public YCB-100 kit accepts arbitrary agent implementations only through the
contained JSONL protocol. It evaluates consequences in synthetic local worlds.
It must not receive production credentials, personal data, protected health
information, payment-card data, real SCADA access, or a private evaluator key.

## Trust Boundaries

| Component | Trust level | Required boundary |
| --- | --- | --- |
| Participant image and agent | Untrusted | Only declared JSONL messages and tools; no oracle, private generator, arm identity, or evaluator files. |
| Model relay | Untrusted transport | Binds submitted model/config/prompt/tool manifests; it cannot attest an outcome. |
| Tool gateway | Evaluator owned | Enforces declared tools, read/write budgets, response redaction, and an append-only audit hash. |
| World and mutation ledger | Evaluator owned | Holds hidden state and scheduled events; mutations require idempotency before synthetic source change. |
| Independent source reader | Evaluator owned | Separates source readback from the mutation connector. A connector acknowledgement is not verification. |
| Oracle | Evaluator owned | Recomputes causal state, effect identity, readback, and hard counters; public development uses a fresh worker process, not a sealed boundary. |
| Evidence and qualification receipts | Integrity checked | Reopen files under a declared root, recompute hashes, bind commits, reject unknown/duplicate/missing children, and fail on nonzero hard or unmeasured counters. |
| Sealed store, signing, evaluator operator | Not implemented locally | Required for qualification: microVM custody, key rotation/revocation, threshold signing, retention, disclosure, audit, and fresh post-digest worlds. |

## Current Mitigations

- Proposal candidates carry opaque handles and hash-bound semantic checkpoints.
  Checkpoints cannot assert authorization, canonical action state, trusted
  evidence, oracle state, or receipt identifiers.
- Banking requires real governed evidence intake, reservation, execution,
  settlement, compensation, and independent readback services. A post-effect
  crash can only resolve by source readback, not connector retry.
- The four non-banking public control planes are synthetic local episodes.
  Their agent views exclude expected dispositions, oracle labels, sister-world
  bindings, and future schedule data.
- The Adaptive Causal compositional public engine exposes fourteen generic raw records
  only through named bounded tools. Agent-visible metadata has no terminal
  category or required action prefix; causal and irrelevant-change sisters
  test sensitivity and invariance. The older bounded-fact route remains only
  a compatibility regression control.
- The Adaptive Causal paired adapter binds one frozen candidate and identical initial
  source snapshot to direct and governed arms. The governed arm receives source
  data only through connector-owned evidence ingestion and verifies an effect
  only through exact independent readback. Pre-dispatch revocation and durable
  evidence-command restart are exercised against fresh SQLite containers in
  every domain.
- The portable YCB-100 distribution is built from its own source tree and checked
  from a fresh source-distribution install. `setup.py` clears only the
  generated `build_lib/benchmarks` staging namespace before packaging, and a
  poisoned-staging regression proves it contains no unrelated monorepo
  benchmark module, model client, or credential.
- Qualification evidence schemas exclude live elapsed time from deterministic
  hashes. They fail closed for modified files, stale commits, invalid schemas,
  root escape, missing/unknown/duplicate children, negative counters, and
  nonzero hard or unmeasured counters.

## Known Non-Claims

- `CONTAINMENT_ONLY` is not OCI, microVM, or hostile-code isolation.
- A spawned oracle worker is not independent evaluator custody.
- Public generators and public corpus controls cannot establish private
  structural-OOD difficulty.
- No developer-authored review record is treated as a human/domain review.
  The admission contracts require genuine distinct reviewer records and
  measurable reliability before they can contribute to qualification.
- No public result demonstrates a direct-agent score, a governance-system advantage, zero
  unsafe production effects, or a nine-of-ten benchmark rating.

## Required Before Qualification

Implement and operate the sealed evaluator described in the
[nine-of-ten qualification plan](YCB100_QUALIFICATION_PLAN.md):
fresh evaluator-owned microVM worlds, protected structural-OOD generators,
authenticated artifact custody, strong direct and governed baselines, A/A
calibration, domain-review evidence, red-team rounds, external audits, and two
meaningful release epochs.
