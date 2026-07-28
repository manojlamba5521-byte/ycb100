# Independent Evaluation

ConsequenceBench is seeking independent evaluators, domain reviewers, red
teams, and reproducibility auditors. Independent scrutiny is a prerequisite for
qualification, not a marketing endorsement.

## Fast Review Packet

This packet is designed for a first independent look and requires no model,
provider key, or governance product.

1. Clone the repository and run the Quick Start control commands from the
   [README](../README.md#quick-start).
2. Confirm `validate-scenarios`, `public-controls`, `pressure-controls`, and
   `lifecycle-controls` return zero failures.
3. In the [catalog](CATALOG.md), select one scenario from each domain. Check
   that the authority, evidence, expected consequence, obligation, and
   compensation semantics are coherent.
4. Inspect [Scoring](SCORING.md) for any aggregate that could hide an unsafe
   effect, duplicate effect, false verification, missing legitimate effect, or
   infrastructure failure.
5. Publish defects with exact file, scenario, command, and reproduction steps.

Report the benchmark commit, operating system, Python version, commands, and
all failures. A clean fast review is useful feedback but is not an independent
reproduction or qualification campaign.

## Domain Semantics Packet

Review all 20 public scenarios for one of banking, healthcare, cybersecurity,
energy, or software delivery. For every scenario, answer:

- Is the named actor actually authorized for the exact tenant, target, effect,
  amount or scope, and time window?
- Does each decisive record come from the stated source, bind the same action
  identity, remain current, and survive contradictory evidence?
- Is the expected action `execute`, `deny`, `hold`, `investigate`, `retry`,
  `compensate`, or another explicitly modeled outcome for the right reason?
- Could retries, restarts, stale receipts, partial effects, or shared
  identifiers cause a duplicate or cross-action effect?
- Are delayed duties, deadlines, ownership, readback, and compensation
  represented completely enough to score the final world state?

Submit a row-level review with `scenario_id`, verdict, rationale, and proposed
correction. Do not treat agreement with the current oracle as proof that the
oracle is correct.

## Security And Isolation Packet

Attack candidate containment, evidence provenance, action identity joins,
receipt hashes, oracle secrecy, paired-arm equivalence, and result
denominators. A useful report includes the attempted exploit, the exact
artifact or interface crossed, the observed result, and whether the failure
changes an official hard counter.

## Useful Contributions

- Reproduce the clean installation, controls, frozen pack, and reference run.
- Run an arbitrary agent with a fully disclosed candidate and model manifest.
- Review one domain for incorrect authority, policy, evidence, effect, duty, or
  compensation semantics.
- Attack evaluator isolation, oracle secrecy, artifact binding, scoring, and
  paired-study equivalence.
- Build a product-neutral governance adapter outside this repository.
- Propose structural-OOD mechanism families that defeat current shortcuts.
- Audit a random sample of world traces and source-state diffs.

## Independence Disclosure

State:

- employer and relevant affiliations;
- financial or development relationship with Yuvin Labs, an evaluated model,
  or an evaluated governance system;
- whether benchmark authors selected or configured the candidate;
- whether you controlled the machine, credentials, worlds, and raw artifacts;
- any assistance received during execution or review.

Independence is not inferred from a different GitHub account.

## Minimum Reproduction

An independently reproduced development report must:

1. start from a fresh machine or isolated environment;
2. verify the exact public release and source hashes;
3. run the complete public test and control gates;
4. regenerate and verify the frozen world pack;
5. preserve raw attempts and source-state effects;
6. recompute the deterministic score from retained artifacts;
7. publish failures and limitations alongside favorable results.

Qualification additionally requires sealed worlds created after candidate
digest binding, evaluator-operated isolation, authenticated artifact custody,
external red-team records, domain-expert review, and repeated epochs.

Open an **Independent evaluation or audit** issue before beginning a large
campaign. This prevents duplicated effort and makes the intended claim boundary
explicit. Smaller questions and proposed causal families can begin in
[GitHub Discussions](https://github.com/yuvin-labs/consequencebench/discussions).
