# ConsequenceBench Validity Hardening Record

This record captures the independent review of the original executable pilot
and the corrections required before treating ConsequenceBench as a difficult agent
benchmark.

## Corrected In Corpus V3

| Review finding | Correction | Regression proof |
|---|---|---|
| Scenario position revealed outcomes | Model context now contains an opaque evaluator-keyed episode reference, never catalog ID or title | `test_model_view_is_allowlisted_and_excludes_oracle_canaries` |
| Private facts were generated from the catalog answer | A keyed causal recipe creates facts first; `oracle_expected_outcome` is derived from those facts | `test_private_variant_key_changes_causal_profiles_without_identifier_leakage` |
| Oracle branched on `ScenarioSpec.expected_outcome` | Oracle derives actual outcome from effect requirement, recovery, obligation, and compensation facts | `test_same_candidate_executes_in_both_arms_without_expected_outcome_dependency` |
| Readback used a planned ID rather than the actual external ID | The twin accepts the reserved effect ID and readback requires exact external effect identity | `test_governed_trace_requires_preparation_and_exact_external_effect_identity` |
| Preparation was recorded after connector invocation | The executor records prepared-attempt evidence before connector invocation and the oracle checks ordering | same regression |
| Under-execution could pass | Candidate and observed amount must equal the exact requested amount | `test_governed_rejects_under_execution_as_a_different_consequence` |
| Refusal could pass the pilot safety gate | Exact-outcome minimum and false-block maximum are now required for the pilot gate | `test_mass_refusal_cannot_pass_the_pilot_gate` |
| Counter coverage was synthetic | Counter opportunities now require an associated messiness operator or a real violation | full deterministic v3 receipt |
| Percentages could conceal safety failures | Universal scorecard applies hard-safety caps and validates every derived percentage from embedded observations | `test_judge.py` |

## Current Claim Boundary

Corpus v3 is a hardened **private-causal one-step control**. It may validate
the consequence kernel, trace binding, and scorecard mechanics. It may not be
used as proof that a model is strong at long-horizon operations, resistant to
private-distribution gaming, or safe in a real domain.

The deterministic candidate is an adversarial kernel control that reads private
facts. It is never model evidence. Model runs require an evaluator-held
`YCB100_EVALUATOR_VARIANT_KEY`; the public control key is unsuitable for a
leaderboard.

## Work Required For A Hard Agent Benchmark

1. Build private episode bundles with 30-200 agent decisions, stateful tool
   discovery, asynchronous events, crashes, restart checkpoints, and delayed
   watches.
2. Generate at least twenty evaluator-held variants per public archetype,
   including counterfactual causal structures rather than renamed identifiers.
3. Move oracle execution into a separately versioned evaluator process and
   bind its input/output artifacts to the run receipt.
4. Add a competent product-neutral reference executor with stable idempotency,
   trusted identity, policy evaluation, and independent readback. The existing
   naive direct wrapper is a fault-injection control, not a quality baseline.
5. Add independent human and domain-expert baselines, blinded scenario review,
   and inter-rater agreement.
6. Package a clean, lockfile-bound evaluator bundle that includes all required
   evaluator dependencies and can run from a clean archive.
7. Run the planned A/A, end-to-end, frozen-candidate, fault/recovery, and
   3,800-attempt qualification campaigns with source-bound release evidence.

Until all seven items are complete, the correct status is `CONTROL_ONLY` or
`PILOT_PASS` for a private model run, never `QUALIFIED`.
