# Runtime Policy Gates May Prevent Harm in Simple Worlds; Consequence Closure Requires Durability Tests

**Preprint - preliminary self-reported local development evidence. This is not
a qualification, certification, independent benchmark result, or product
comparison.**

- Date: 2026-08-03
- Benchmark: ConsequenceBench Pressure Worlds (public archetype corpus, seed 0)
- Models: Gemini 3.6 Flash (Vertex AI), Gemma4 e4b (local, Ollama)
- Configurations discussed: Microsoft Agent Governance Toolkit (AGT) 4.1.0 integration; Yuvin Consequence Governance Runtime

> **Evidence availability warning.** This release contains the manuscript, not
> the complete raw evidence package. Two retained local Yuvin reports are
> identified by hash in [Data availability](#data-availability); a row-level
> AGT receipt is not publicly available. The numerical table therefore records
> local observations, not independently reproducible comparative evidence. It
> must not guide procurement, safety, or regulatory decisions.

---

## Abstract

We examine whether runtime governance reduces unsafe simulated effects when
agents act in ten-world ConsequenceBench Pressure selections. The study contains
four Yuvin configuration records and **two** AGT-versus-Yuvin head-to-head
cells: the Untested-10 selection with Gemini 3.6 Flash and with Gemma4 e4b.
It does not contain four head-to-head comparisons.

In the observed single runs, each governed configuration recorded zero unsafe
simulated effects. The two shared cells produced the same safety counter under
both integrations. Yuvin configuration records also showed four or five
repaired decisions, while the AGT configuration records showed none. That
difference cannot be attributed to either product architecture: the
integrations differ in implementation, feedback, and recovery semantics, and
the AGT integration adds locally written source readback.

The appropriate conclusion is narrow. A policy gate can prevent unsafe effects
in these simple, single-process worlds. This evidence does not establish that
pre-dispatch policy is a commodity, that the two products are equivalent, or
that either is suitable for deployment. Contention, ambiguous dispatch,
crash-recovery, delayed settlement, and independent evidence custody remain
unmeasured.

## 1. Question and scope

An operator investigating an agent incident needs more than an allow-or-deny
record: whether authority was current at dispatch, whether another worker
already owned the effect, whether the source changed, and whether a durable
record can be independently checked.

This note distinguishes two broad designs:

- A **pre-dispatch policy gate** evaluates an execution-context rule before a
  tool call.
- A **consequence closure** layer manages evidence admission, authority,
  reservation, dispatch, readback, and recovery across an action lifecycle.

The study only tests simple synthetic worlds. It does not measure production
reliability, legal compliance, or a product's shipped capabilities.

## 2. Method

### 2.1 Corpus and selections

ConsequenceBench Pressure Worlds are evaluator-owned synthetic environments.
The evaluator determines the correct disposition; neither model nor governance
configuration receives that answer key.

Two ten-world selections were used:

- **First-10:** banking families 0-9: execute (4), deny (5), defer (1).
- **Untested-10:** banking families 13-19, healthcare families 18-19, and
  cybersecurity family 18: escalate (5), compensate (5).

Untested-10 adds escalate and compensate dispositions, which had not appeared
in the First-10 selection. Each selected world identity was checked by hash.

### 2.2 Observed configurations

| Corpus | Model | Configuration | Correct consequence | Unsafe simulated effects | Exact decisions | Reported repairs |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| First-10 | Gemini 3.6 | Yuvin | 10/10 | 0 | 6 | 1 |
| First-10 | Gemma4 e4b | Yuvin | 9/10 | 0 | 3 | 0 |
| Untested-10 | Gemini 3.6 | Yuvin | 10/10 | 0 | 6 | 5 |
| Untested-10 | Gemini 3.6 | AGT integration | 9/10 | 0 | 7 | 0 |
| Untested-10 | Gemma4 e4b | Yuvin | 8/10 | 0 | 4 | 4 |
| Untested-10 | Gemma4 e4b | AGT integration | 8/10 | 0 | 4 | 0 |

Only the two Untested-10 model rows are like-for-like AGT-versus-Yuvin cells.
The First-10 rows are Yuvin configuration records, not comparisons with AGT.

### 2.3 Controls and integration limits

The reported runs used the same world identities, model temperature (0), a
24-tool budget split into two 12-tool proposal rounds, counterbalanced arm
ordering, separate process and state roots, and hash-bound local receipts.

The AGT configuration is a locally built integration, not AGT as distributed.
It applies a deny-by-default policy to evaluator-owned evidence predicates and
adds a locally written source-readback step. It also supplies generic,
structured feedback after a denied or incomplete attempt. Consequently, this
study cannot isolate AGT's product behavior, a policy gate alone, the feedback
loop, or the source adapter.

The Yuvin configuration uses canonical proposal intake, trusted evidence
admission, short-lived authority closure, effect reservation, controlled
dispatch, and source-bound readback before `VERIFIED`. The study does not test
these mechanisms under concurrent or durable-recovery failures.

## 3. Observations

### 3.1 Governance configurations recorded zero unsafe simulated effects

All six governed configuration records in the table above recorded zero unsafe
simulated effects. On Untested-10, Gemma4 moved from 0/10 correct consequences
and nine unsafe simulated effects in the associated direct run to 8/10 and zero
under each governed configuration. Gemini's associated direct run moved from
4/10 correct and six unsafe effects to 10/10 under Yuvin and 9/10 under the AGT
integration.

These are single-run observations with a denominator of ten. They demonstrate
neither zero risk nor a stable performance difference.

### 3.2 Repair is an end-to-end configuration observation

The Yuvin records report four or five repaired decisions on Untested-10. The
AGT records report zero, meaning the final governance disposition did not
become semantically exact when the model's final disposition was not exact.

This is not a causal product comparison. Both configurations expose feedback,
but their feedback schemas, dispatcher behavior, lifecycle ownership, and
source-adapter logic are not held identical. A suitable ablation would compare
the same candidate and source adapter under: policy only; policy plus readback;
policy plus readback and structured retry; and consequence closure with repair
disabled and enabled.

### 3.3 A one-point difference is not a result

An AGT campaign re-run at temperature 0 reportedly moved from 10/10 to 9/10
correct consequences, and from seven to six model-exact decisions. With one
run per ten-world cell, differences of one or two worlds are not distinguishable
from run variance. Repeated paired trials, predefined analysis, and confidence
intervals are required before comparing rates.

## 4. What follows and what does not

This limited corpus supports one operational hypothesis: an independently
enforced policy gate may stop unsafe effects in simple synthetic, single-process
worlds. The evidence does **not** support any of the following:

- that runtime governance is optional;
- that policy enforcement is a commodity;
- that AGT and Yuvin are equivalent;
- that source readback, reservation, compensation, or durable recovery are
  unnecessary; or
- a safety, regulatory, procurement, or production-readiness claim.

The missing cases are material. The selection has no multi-worker contention
for the same effect, process termination after dispatch, retry following an
ambiguous connector response, delayed settlement, or adversarially conflicting
readback. Those are the cases where durable action ownership, idempotency,
reservations, and compensation are expected to matter. They must be introduced
as versioned, new capability tests rather than silently changing the existing
corpus.

## 5. Threats to validity

1. **Common authorship and implementation.** The benchmark, both integrations,
   and one product are controlled by the same party. Independent implementation
   and review are required.
2. **AGT integration scope.** Local code supplies source readback and the
   execution-context adapter. Results do not describe AGT as shipped.
3. **Feedback and recovery confounding.** The observed repair count is a
   property of end-to-end integrations, not a clean architecture measurement.
4. **Single runs, n = 10.** No confidence interval or repeat trial supports a
   comparative performance statement.
5. **Evidence availability.** The complete row-level AGT receipt and integration
   release are not publicly available in this release.
6. **Synthetic scope.** No production system, customer data, financial account,
   clinical workflow, or security environment was contacted.

## 6. Next study

Before making a comparative claim, publish immutable report bundles for every
configuration and run a preregistered, repeated paired study. The protocol
should hold the frozen candidate, model, prompt, tools, budgets, faults, retry
policy, source adapter, and readback mechanism constant. It should then add
contention, crash windows, ambiguous dispatch, duplicate attempts, conflicting
readback, delayed settlement, and failed compensation.

The benchmark's governance conformance and frozen-candidate incremental-effect
tracks should be reported separately, with all failures and row-level receipts.
An independent operator should reproduce the published hashes before any vendor
or procurement conclusion is drawn.

## Data availability

The two retained local Yuvin Untested-10 report hashes are:

- Gemini 3.6 Flash: `sha256:5753baba811f21ad85478da76fab282ae6a3c35db75e6010af6554abdb428257`
- Gemma4 e4b: `sha256:e339917fbc16bd247fea7c4844397e6d4416af5d1f386542172b12a3c8f76918`

Those files are not included in this public release archive. The AGT row-level
report, complete integration source release, and repeat-run receipt have not
been supplied for public verification. This document is therefore labelled
`SELF_REPORTED_LOCAL_DEVELOPMENT_EVIDENCE` and remains a research note, not a
ConsequenceBench result submission.

## Status

`SELF_REPORTED_LOCAL_DEVELOPMENT_EVIDENCE` - not evaluator-custodied, not
hostile-code isolated, not independently reproduced, and not a certification.
