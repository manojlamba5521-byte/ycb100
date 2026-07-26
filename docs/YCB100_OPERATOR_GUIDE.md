# YCB-100 Operator Guide

## Roles

| Role | Receives | Must not receive |
| --- | --- | --- |
| Agent participant | Public episode view and read-only tool replies | Oracle state, expected outcome, evaluator files, keys, or other-arm traces |
| Evaluator | World state, tool handlers, oracle, manifests, and counters | Authority to edit a participant trace after it starts |
| Official judge | Evaluator-owned traces and private oracle state | LLM-review conclusions as score inputs |
| Advisory LLM reviewer | A declared public review subject | Private oracle facts, expected answers, or credentials |

## Give a Task to an Agent

Yes. Give the benchmark to an AI agent directly, but through the YCB-100 JSONL
protocol rather than pasting an answerable question into a chat window. This
keeps evidence, tool budget, timing, and transcript identical across compared
arms.

1. Create an `agent-manifest.json` with the exact model, prompt, source
   revision, tool budget, environment allowlist, and command hash.
2. Create an `agent-command.json` whose command starts a JSONL adapter over
   standard input/output. The agent receives `episode.start`, may issue only
   declared `tool.call` messages, then finishes with `decision.submit` or a
   canonical proposal.
3. Run the same pinned agent in direct and governed arms in randomized order.
4. Let the evaluator-owned oracle calculate consequence correctness, evidence
   grounding, duplicate effects, unsafe effects, and recovery results.

Existing adapters are concrete examples:

```powershell
py -3 scripts/ycb100_vertex_gemini_jsonl_agent.py --help
py -3 scripts/ycb100_ollama_jsonl_agent.py --help
py -3 scripts/ycb100_codex_cli_jsonl_agent.py --help
ycb100 pressure-agent --help
ycb100 lifecycle-agent --help
```

Any model or framework can participate when its adapter follows the same JSONL
protocol. The participant must not read local benchmark source, inspect the
environment, access the network, or receive hidden oracle facts.

Pressure Worlds evaluates investigation and proposal behavior. The Consequence
Lifecycle Track makes the arbitrary candidate own preparation, reservation,
dispatch, restart recovery, source readback, obligations, compensation, and
terminal reporting. See `CONSEQUENCE_LIFECYCLE_PROTOCOL.md`.

For lifecycle episodes, the start message is deliberately not executable. It
contains an untrusted request claim. The adapter must let the agent discover
source services, join the distributed `proposal_binding.*` witnesses, and
compute the exact identity fingerprint before requesting preparation.

The public package runs the direct capability track. Paired direct/governed
studies require the separately operated integration for the governance system
under evaluation; they are not silently enabled by the universal wheel. Local
subprocess containment is not an OS sandbox, so hostile candidate qualification
requires an evaluator-operated microVM.

## Official Judge

The official judge is deterministic and evaluator-owned. It is not an LLM. It
replays validated traces against source state and the private oracle, then
derives the published scorecard and hard counters. A language model can write a
plausible explanation while still missing an unsafe effect, forged receipt,
stale authorization, or duplicate dispatch.

Before accepting an official result, verify that:

- The agent implementation, model, prompt, tools, budgets, and seed are
  recorded and hash-bound.
- Both arms use the same world snapshot and receive equal resources.
- The oracle is outside the agent boundary and its report hash validates.
- Every attempted run, including timeouts and malformed output, is retained.
- No unsafe effect, false verification, secret exposure, duplicate effect, or
  unmeasured hard counter is silently converted into success.
- Local studies are labelled `DEVELOPMENT_ONLY` until the qualification plan's
  independent-evaluator and sealed-corpus requirements are met.

## Optional LLM Reviewers

OpenAI, Gemini, and Anthropic can produce an additional qualitative review of
one **public** trace. This is useful for explaining why reasoning was weak,
mixed, or strong. The result is always `ADVISORY_ONLY`; it cannot change an
official decision, score, or safety counter.

Never put a key in the repository or in a review-subject file. Set exactly one
provider key in the terminal session, then run the review command:

```powershell
$env:OPENAI_API_KEY = "..."
py -3 scripts/run_ycb100_llm_review.py `
  --provider openai --model <model-id> `
  --input public-review-subject.json --output runs/reviews/openai-review.json
```

```powershell
$env:GEMINI_API_KEY = "..."
py -3 scripts/run_ycb100_llm_review.py `
  --provider gemini --model <model-id> `
  --input public-review-subject.json --output runs/reviews/gemini-review.json
```

```powershell
$env:ANTHROPIC_API_KEY = "..."
py -3 scripts/run_ycb100_llm_review.py `
  --provider anthropic --model <model-id> `
  --input public-review-subject.json --output runs/reviews/anthropic-review.json
```

The input contains only a public episode, agent trace, optional proposal, and
`review_id`. The result binds the subject, prompt, and provider response by
SHA-256. It contains no official score field; every published result still
needs a separate deterministic oracle receipt.
