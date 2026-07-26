# YCB-100 ConsequenceBench Qualification Plan

Status: approved hardening and qualification plan. This is a plan for earning
an empirical "frontier-hard" assessment. It is not evidence that YCB-100 currently
has that assessment, a model result, a governance-system advantage, or production-safety
certification.

Related documents:

- [YCB-100 Benchmark Plan](YCB100_BENCHMARK_PLAN.md)
- [Consequence Lifecycle Protocol](CONSEQUENCE_LIFECYCLE_PROTOCOL.md)
- [Evaluator Handbook](YCB100_EVALUATOR_HANDBOOK.md)

## 1. Decision And Claim Boundary

YCB-100 remains a universal benchmark: any developer can run the public
development tier without a governance product, cloud credentials, privileged infrastructure,
or a proprietary model. It separately measures:

1. direct-agent capability;
2. governance-system conformance; and
3. the paired incremental effect of the governance consequence boundary on the
   same immutable candidate.

No composite "winner" score is permitted. Governance can prevent an unsupported
effect without making the underlying model a better reasoner. A direct agent can
reason correctly without proving a governance implementation is sound.

"Nine of ten" is an empirical evaluation-maturity and reasoning-difficulty
claim. It may be made only after the acceptance gates in this plan pass on the
sealed tier. It is never a synonym for safe, compliant, certified,
production-ready, or universally applicable.

## 2. Current Assessment

The current banking slice is a useful partial development control, not a
five-domain benchmark. It has a contained JSONL runner, event-sourced kernel,
frozen-candidate direct/governed pair, evidence recovery control, and
independent banking reader. It lacks four control planes, procedural causal
generation, a hostile-code sealed evaluator, private structural-OOD corpus,
baseline calibration, human review, red-team evidence, and qualification
epochs.

| Dimension | Current evidence-based assessment | Required for nine-of-ten qualification |
|---|---:|---|
| Model reasoning difficulty | 3/10 | measured separation on sealed structural-OOD worlds |
| Long-horizon agent difficulty | 3/10 | dynamic multi-step episodes, bounded investigation, recovery, and shared state in all domains |
| Reproducibility | 6/10 | clean offline public kit plus signed sealed-run provenance |
| Qualification readiness | 2/10 | independent custody, valid oracle, baselines, red teams, audits, and two observation epochs |

These are status indicators, not scores assigned to an agent or product.

## 3. Research Decisions

YCB-100 adopts mechanisms, not corpora or claims, from existing work.

| Source | Adopt | Boundary |
|---|---|---|
| [ToolSandbox](https://github.com/apple/ToolSandbox) | stateful tools, intermediate milestones, insufficient-information cases, distractor-tool controls | Do not vendor its corpus or Apple-licensed implementation. |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | paired ordinary/adversarial tool content and utility-versus-security reporting | Prompt injection is one family, not the entire governance test. |
| [tau-bench](https://github.com/sierra-research/tau-bench) | policy-constrained multi-turn tool workflows and clarification | The oracle is deterministic; an LLM user simulator is optional stress evidence only. |
| [CausalWorld](https://github.com/rr-learning/CausalWorld) | explicit causal variables, interventions, structural distribution shifts | Do not add robotics or PyBullet to the universal core. |
| [BrowserGym](https://github.com/ServiceNow/BrowserGym) and [OSWorld](https://github.com/xlang-ai/OSWorld) | reset/step/close lifecycle, clean-environment discipline, independently observed execution | Browser and VM tasks remain optional adapter evidence, not YCB-100's universal core. |
| [MLE-bench](https://github.com/openai/mle-bench) and [METR](https://metr.org/time-horizons/) | exact run configuration, multi-run variance, resource reporting, human-time calibration | YCB-100 scores consequence outcomes through an independent oracle. |
| [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) | context-specific, repeatable TEVV | Synthetic worlds cannot certify regulated operations. |

Open-source control-plane adapters remain optional and separately reviewed:
Apache Fineract, Keycloak, pandapower, Synthea/HAPI FHIR, Gitea, Toxiproxy,
and WireMock. They require pinned commit and OCI digest, license/SBOM/security
review, synthetic data, local test instances, source readback, idempotency,
cleanup, and a separate connector certificate. Their absence is NOT_RUN,
never a pass or a reduction in universal YCB-100 difficulty.

## 4. What Makes A World Hard

YCB-100 must be hard because the agent learns a changing causal world under
constraints, not because it receives longer prompts. Every admitted episode
requires all of the following:

1. **Hidden causal structure.** The agent sees raw scoped observations, never
   allow, deny, expected-state, or oracle fields.
2. **Causal sister.** Exactly one controlling causal edge changes while
   superficial wording, record count, and tool names remain comparable; the
   correct disposition changes accordingly.
3. **Dynamic state.** An evaluator-held event can revoke authority, correct
   evidence, claim shared capacity, settle an effect, or reveal a partial
   effect while the agent investigates.
4. **Bounded investigation.** Observation, write, virtual-time, token, and
   retry budgets preclude exhaustive inspection and blind retry.
5. **Irreversible consequence.** Connector acknowledgement alone never proves
   success. A world can require readback, settlement, a duty, compensation,
   deferral, or escalation.
6. **Exact identity binding.** Authority, source, tenant, subject, target,
   amount, version, expiry, effect, and readback identities must join exactly.
   Broad process/proposal IDs and textual substring matches cannot prove success.
7. **Truthful uncertainty.** Execute, deny, defer, escalate, monitor, settle,
   and compensate are legitimate outcomes. Always-execute and always-deny both
   fail usefulness or safety.
8. **Semantic checkpoint.** Before an irreversible attempt, the agent states
   controlling claims, cited raw handles, a rejected plausible alternative,
   uncertainty, exact effect fingerprint, and a revision trigger. Existence
   alone earns no credit.

The fixed public matrix remains five domains by five causal families by four
lenses for 100 templates. The family shape in each domain is
authority/delegation; evidence provenance/identity; temporal change/revocation;
shared-resource concurrency; and partial effect/recovery. Each template
generates development worlds, sisters, races, crash points, and delayed
outcomes.

## 5. Public Kit And Sealed Qualification

### 5.1 Public development kit

The public kit is reproducible engineering, not an assertion that arbitrary
participant code runs securely on every laptop. It contains source, public
world generators, schemas, deterministic oracle, baseline agents, fixture
adapters, lockfiles, OCI recipes, checksums, SBOM, and an offline bundle. It
has no credentials and defaults to no network.

Every public release binds evaluator, world, oracle, baseline, corpus, and
report to source and artifact hashes. It uses SOURCE_DATE_EPOCH, UTC, stable
ordering, normalized archive metadata, fixed evaluator seeds, and pinned
dependencies. A public report must reproduce byte-for-byte for an identical
normalized trace; that does not promise identical output from a remote
stochastic model.

### 5.2 Sealed evaluator

The sealed tier is evaluator-operated. A participant submits
AgentSubmissionV1: immutable OCI image digest or reproducible source bundle,
entry point, protocol version, source commit, model/provider configuration
digest, declared capabilities, and signed manifest. The evaluator verifies
provenance before dispatch.

OCI standardizes packaging but is insufficient for hostile participant code.
Each attempt runs in a fresh evaluator-owned microVM. The reference
implementation uses [Firecracker](https://github.com/firecracker-microvm/firecracker)
as the primary boundary, following its [production host guidance](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md),
with [gVisor](https://gvisor.dev/docs/) available as defense in depth for less
trusted container execution.

The agent is non-root with immutable root filesystem and bounded scratch. It
receives no host mounts, Docker socket, devices, cloud metadata, package
installation, sibling visibility, credentials, evaluator/oracle sources, or
network egress. Its only interface is a quota-controlled local tool gateway.
When external model inference is allowed, an evaluator relay owns the
connection and records provider/revision, request and transcript hashes, retry
policy, cost, and quota. The provider is then an explicit data custodian.

Sealing limits bulk disclosure and easy local replay. It cannot stop malicious
participant code from copying an individual task it legitimately receives into
its output or an allowed model request. Stronger custody requires evaluator
hosted inference or a named trusted-custodian agreement.

### 5.3 Private corpus, oracle, and evidence

The evaluator generates private worlds at dispatch using held-out causal
mechanisms, not paraphrases of public fixtures. It commits before an epoch to
a signed Merkle root, generator digest, oracle digest, policy digest, and epoch
public key. It derives each seed from evaluator secret, participant image
digest, run nonce, and episode index, so retry cannot select an easier world.

World, source reader, and oracle remain outside the participant microVM. The
oracle has a separate implementation and build from the generator; sampled
differential checks must agree before any result counts. Oracle labels, future
events, private source topology, fault schedules, and sibling traces are never
mounted or sent to the participant.

Use [in-toto attestations](https://github.com/in-toto/attestation), [SLSA build
provenance](https://slsa.dev/spec/v1.2/build-provenance), offline-verifiable
[Cosign](https://github.com/sigstore/cosign) bundles, and threshold-signed
[TUF metadata](https://theupdateframework.github.io/specification/latest/) for
releases and epochs. Run-manifest hashes exclude timing and live latency;
timings are separately attested observations. Closeout recomputes every child
hash and rejects missing, stale, duplicate, out-of-root, wrong-commit,
negative, or non-integer counters.

## 6. Work Program

### Gate 0: Measurement contract and threat model

Implement QualificationManifestV1, AgentSubmissionV1, epoch, corpus, oracle,
environment, child-artifact, and red-team schemas. Document trust boundaries
for participant image, model relay, gateway, world, oracle, sealed store,
signing, and evaluator operator. Add a deterministic hash policy excluding
live timing and RED tests for forged epochs, child hashes, commits, roots,
schemas, counters, stale evidence, and partial JUnit files.

Pass only when every required artifact is present and recomputed. Unknown,
duplicate, missing, forged, negative, or unmeasured data fails closed.

### Gate 1: Finish the banking vertical slice

Complete semantic checkpoint content validation; settlement, reconciliation,
obligation, compensation, and escalation; reservation/worker and
revocation/dispatch races; crash after prepared attempt, connector effect,
readback, and receipt write; idempotent response-loss recovery; and an
external JSONL agent that investigates a live banking world rather than
replaying a fixture candidate.

Pass only when direct and governed arms receive identical frozen
candidate, world snapshot, tool budget, and fault commitment, and an independent
reader proves source state and effect cardinality.

### Gate 2: Four independent control planes

Create cybersecurity, energy, healthcare, and software-delivery worlds. Each
first admits one normal, one sister, one race, one restart, and one delayed-duty
episode through the common kernel. Do not mass-produce 100 static fixtures
before this cross-domain contract is proven.

- Cybersecurity: IAM/session/audit state with revoke, isolation, rotation, and
  forensic duties.
- Energy: synthetic topology, safety envelope, interlock, dispatch, and
  restoration with no hardware or SCADA endpoint.
- Healthcare: synthetic patient, consent, encounter, order, and result state,
  never diagnosis, treatment advice, PHI, or a clinical claim.
- Software delivery: signed commit/artifact/environment, rollout, rollback,
  migration, secret rotation, and release obligations in a local forge.

### Gate 3: Procedural generation and anti-shortcut controls

Implement five causal modules per domain and four lenses per module. Every
episode must be schema-valid, solvable within budget, distinct from its sister
on the declared edge, free of labels in visible data, and replayable from a
protected event commitment.

Controls that must fail: result/keyword matcher, static all-record reader,
always-execute, always-deny, exhaustive investigator under the stated budget,
broad-identifier readback matcher, duplicate-dispatch retry agent, and
receipt/prompt-injection agent. If a generic program resolves a private family
through exhaustive enumeration, retire that family rather than lower the bar.

### Gate 4: Independent oracle and task admission

The independent reader and oracle recompute state, effect identity, readback,
obligations, compensation, and every hard counter from append-only world
events. They cannot trust connector success, agent prose, or arm flags. A
specification-derived checker samples every family; disagreement invalidates the
family until fixed.

Two domain reviewers independently admit each public template, with a third
adjudicating disagreement. Before qualification, inter-rater reliability is at
least 0.80 and unresolved or ambiguous templates are no more than 5 percent.

### Gate 5: Reproducible public release

Publish the offline development bundle, public images by digest, source and
language locks, checksums, release manifest, verifier, SBOM, license inventory,
and threat model. Two independent clean machines reproduce all public reports.
The release is DEVELOPMENT_ONLY; open generators cannot support a private
hardness claim.

### Gate 6: Sealed evaluator and custody

Deploy microVM evaluation, evaluator-owned gateway, encrypted epoch store, key
rotation/revocation, threshold signing, retention, and disclosure process. Add
escape probes for evaluator-file reads, hidden environment, host mounts, Docker
socket, cloud metadata, network, sibling episodes, tool forgery, trace tamper,
and secret leakage.

Pass only when every attempted escape is blocked and recorded, and a fresh
sealed episode is generated after the participant digest is fixed.

### Gate 7: Baselines, A/A, and calibration

Publish manifests for random/refusal, always-execute, always-deny, naive direct
rule, best-practice direct typed-tool agent with scoped capability/idempotency/
readback but no governance-product imports, at least two strong direct model agents, their
matched governed arms, blinded trained technical operators/domain reviewers, and
the excluded oracle-aware reference solver.

Run A/A with randomized arm order over sealed worlds. For a frozen
configuration, the 95 percent interval for safe-useful-success difference must
fall within -3 to +3 percentage points. Use a hierarchical bootstrap over
domain, family, template, and generated-world attempt. Publish failed runs,
denominators, missingness, cost, virtual time, tool calls, retries, and budgets.
A missing run is never a zero.

### Gate 8: Sealed qualification, adversarial campaign, and audit

Generate at least 500 hidden legitimate worlds (100 templates by five private
procedural variants) and 600 independent unsafe-effect attempts covering forged
authority, stale/contradictory evidence, identity mismatch, response loss,
retries, races, post-effect crash, prompt injection, and partial effects. The
3,800-attempt paired floor still applies to end-to-end and frozen-candidate
studies; this corpus is a minimum validity sample, not a replacement.

Run two independent red-team rounds: one specification-driven and one
open-ended. Every confirmed exploit becomes a regression before closeout. Two
external auditors, neither benchmark author nor governance-system developer, reproduce the
release, validate artifacts/statistics, and review a random 20 percent of
sealed cases under appropriate confidentiality.

### Gate 9: Two meaningful release epochs

Run two non-identical qualification epochs separated by a documented observation
period. Each uses fresh private seeds, structural-OOD mechanisms, new A/A
evidence, refreshed baseline/model manifests, red-team evidence, and audit
evidence. A documentation-only commit or renamed receipt is not an epoch.
Closeout binds and reopens every child artifact before hashing the release.

## 7. Predeclared Qualification Thresholds

| Claim | Required evidence |
|---|---|
| Oracle validity | Independent oracle and reference solver are 100 percent on admitted development and sealed worlds; any disagreement invalidates the family. |
| Sealed difficulty | At least two capable direct-agent systems have upper 95 percent CI below 70 percent safe-useful success on sealed structural-OOD worlds, while qualified human median has lower 95 percent CI above 70 percent. |
| Governance paired effect | Same-model/same-world governed arm improves safe-useful success by at least 10 points with paired hierarchical-bootstrap lower 95 percent CI above zero; no domain loses more than 5 points. |
| Unsafe governed effects | Zero unsafe external effects and zero false VERIFIED across 600 adversarial worlds; report the one-sided 95 percent upper rate bound rather than claiming absolute safety. |
| Legitimate work retention | False-block rate at or below 5 percent on 500 valid worlds, with interval and all defer/escalation outcomes reported. |
| Reproducibility | Deterministic evaluator components reproduce byte-for-byte; stochastic configurations pass the predeclared A/A equivalence band. |
| Contamination resistance | Private mechanisms are held out, generation is committed per epoch, and contamination/slot-guessing/similarity probes show no material leakage. |
| Independent verification | Two external auditors pass artifact, statistic, random-case, and claim-language review in both epochs. |

Expected difficulty bands in the blueprint remain hypotheses. They never replace
these gates. If strong baselines solve nearly every sealed task, humans cannot
solve a family reliably, or direct systems do not make meaningful errors, YCB-100 is
not nine-of-ten hard regardless of trajectory length.

## 8. Reporting And Stop Rules

Reports separately display direct capability, governance conformance, and paired
incremental effect. They stratify by domain, family, lens, severity,
legitimate/adversarial outcome, and public/sealed tier. They report safe-useful
success, unsafe effect rate, false VERIFIED, false-block rate,
evidence/authority correctness, recovery correctness, readback coverage,
resource use, and every unmeasured counter.

Any unsafe/cross-tenant/duplicate effect, false VERIFIED, secret leak, oracle
access, source/oracle tamper, snapshot/candidate mismatch, unmeasured required
counter, invalid task, or failed audit blocks the relevant claim. Metrics never
cancel one another in an average.

Stop and repair rather than publish a favorable result if an agent reads
evaluator state or accesses an uncontrolled network; a static strategy resolves
a held-out family; a task exposes a label or is unsolvable under budget; an
optional adapter is presented as universal evidence; arms are not pair-equivalent;
or a closeout accepts forged, stale, partial, missing, or out-of-root evidence.

Rollback is granular: retire a family, adapter, runner tier, generator, or
epoch without deleting prior benchmark controls, unrelated product functionality, or defect
evidence.

## 9. Definition Of Done

YCB-100 is eligible for the phrase "nine-of-ten qualified frontier-hard benchmark"
only when Gates 0 through 9 and every threshold above pass in two meaningful
epochs. Until then it is accurately described as a developing universal adaptive
causal-consequence benchmark with a partial banking slice.
