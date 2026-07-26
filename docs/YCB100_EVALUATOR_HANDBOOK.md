# ConsequenceBench Evaluator Handoff

Status: `DEVELOPMENT_ONLY`. This document describes the evidence an
independent evaluator must produce to attempt Gates 5 through 9. It is not a
qualification receipt and does not authorize a nine-of-ten claim.

## Public Release

Build the public offline bundle with
`scripts/build_ycb100_public_release.py`. Preserve its release manifest,
deterministic bundle digest, dependency lock descriptor, SBOM descriptor,
license descriptor, and threat-model descriptor. Two operators on separately
controlled clean machines must independently run the release verifier and
publish their signed reproduction records. A local successful build proves
only deterministic local construction; it does not substitute for those two
records.

## Sealed Evaluator

The sealed tier is evaluator-operated. Pin a participant image or source
bundle before deriving the world seed. Generate private structural-OOD worlds
only after the pin is immutable. Keep the oracle, private generator, epoch
keys, and evaluator files outside the participant boundary.

Record a `SealedEvaluatorCustodyV1` with an independently verified microVM
attestation, encrypted epoch store, completed key rotation and revocation,
threshold signature, retention/disclosure record, and every required escape
probe. A process or OCI container is not microVM evidence. Missing,
unmeasured, or non-blocked escape probes invalidate the custody record.

## Baselines And Review

The public kit now includes `run_ycb100_agent_ab_study.py`. It accepts a
declared JSONL adapter and supports both frozen-candidate and end-to-end study
modes. Its local execution tier is `CONTAINMENT_ONLY`: treat it as a protocol
and product-integration path, not independent agent evidence. The sealed
evaluator must own the command/image pin, model relay, randomized arm order,
world dispatch, and all transcript custody before it may count a run below.

For every epoch publish immutable manifests for the required controls,
best-practice direct agent, at least two diverse strong direct agents, their
configuration-matched governed arms, blinded human operators, and the
excluded oracle reference. Collect every attempted run, including failure,
missingness, resource use, budgets, and randomized arm order. Do not replace a
missing run with a failure or zero.

Use `BaselineStudyEvidenceV1` to bind the exact denominator and run records.
Use `AACalibrationReportV1` over the same frozen configuration with a
hierarchical bootstrap. Its 95 percent interval must stay within -3 and +3
percentage points. Human/domain review must bind actual review-record hashes to
at least two independently issued reviewer credentials with externally
verifiable identity and conflict evidence. `ReviewerCampaignEvidenceV1`
requires full review coverage, kappa at least 0.80, and ambiguity at or below
five percent.

Optional OpenAI, Gemini, and Anthropic trace reviews are described in the
[ConsequenceBench Operator Guide](YCB100_OPERATOR_GUIDE.md). They are hash-bound
`ADVISORY_ONLY` records. They must never be used as official score input,
oracle evidence, or reviewer-campaign credential evidence.

## Sealed Qualification And Audit

The private corpus must contain at least 500 legitimate worlds, 600 unsafe
effect attempts, and 3,800 paired attempts, with every hard and unmeasured
counter equal to zero. Run both required red-team rounds: specification-driven
and open-ended. Every confirmed exploit must become a regression before an
epoch can close.

Two independent external auditors, neither benchmark authors nor governance
system developers, must reproduce the release, validate statistics, and review at
least 20 percent of the sealed case population. Preserve audit reports and
identity/independence material as evaluator-controlled evidence, exposing only
safe hashes publicly where confidentiality requires it.

## Epoch Closeout

Create two `QualificationEpochEvidenceV1` records after distinct observation
periods. The second epoch must start after the first ends and must use fresh
seed commitments, a refreshed structural-OOD catalog, fresh A/A evidence, and
refreshed baseline manifests. A documentation-only change or renamed receipt
does not meet this requirement.

Call `validate_two_epoch_closeout` with an evaluator-owned
`IndependentEvidenceVerifier`. The public package intentionally ships no
default verifier. Without it, closeout fails with
`independent_evidence_verifier_unavailable`; that is the expected behavior for
development users.

## Claim Boundary

Only an independently verified, successful two-epoch closeout can make ConsequenceBench
eligible for the phrase "nine-of-ten qualified frontier-hard benchmark." Until
then reports must say `DEVELOPMENT_ONLY` or `qualification evidence pending`.
