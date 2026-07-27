# ConsequenceBench Development Leaderboard

*Internal development runs using recorded provider configurations. Ranking
order:
safety-gate pass, exact decision, then correct consequence.*

![Ranked development views without Yuvin and with Yuvin](assets/development-leaderboard-ranked.svg)

## Without Yuvin

Models execute through the direct connector path.

| Rank | Model | Exact decision | Correct consequence | Resolved | Unsafe effects | Agent failures | Tool calls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | GPT-5.6 Sol (xhigh) | 60/100 (60%) | 79/100 (79%) | 60/100 (60%) | 21 | 0 | 2,375 |
| 2 | Gemini 3.6 Flash | 32/100 (32%) | 41/100 (41%) | 32/100 (32%) | 59 | 0 | 1,413 |
| 3 | Qwen3.6 35B | 23/100 (23%) | 23/100 (23%) | 22/100 (22%) | 73 | 8 | 918 |
| 4 | Gemma4 e4b | 19/100 (19%) | 34/100 (34%) | 19/100 (19%) | 63 | 22 | 875 |

## With Yuvin

The same models execute through the governed path.

| Rank | Model | Exact decision | Correct consequence | Resolved | Unsafe effects | Agent failures | Tool calls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | GPT-5.6 Sol (xhigh) | 69/100 (69%) | 99/100 (99%) | 69/100 (69%) | 0 | 0 | 2,384 |
| 2 | Gemini 3.6 Flash | 58/100 (58%) | 100/100 (100%) | 58/100 (58%) | 0 | 0 | 1,536 |
| 3 | Gemma4 e4b | 34/100 (34%) | 92/100 (92%) | 34/100 (34%) | 0 | 6 | 878 |
| 4 | Qwen3.6 35B | 32/100 (32%) | 95/100 (95%) | 32/100 (32%) | 0 | 6 | 1,024 |

## Paired Governance Effect

Each pair used the same model, 100 worlds, seed, tools, total budget,
fault schedule, and two proposal rounds. The governed arm could return
structured holds and permit the same frozen candidate to replan.

![Paired development leaderboard without Yuvin and with Yuvin](assets/development-leaderboard-paired.svg)

| Candidate | Exact decision | Correct consequence | Unsafe effects | Exact recoveries | Exact regressions |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPT-5.6 Sol (xhigh) | 60 -> 69 (+9) | 79 -> 99 (+20) | 21 -> 0 | 13 | 4 |
| Gemini 3.6 Flash | 32 -> 58 (+26) | 41 -> 100 (+59) | 59 -> 0 | 27 | 1 |
| Qwen3.6 35B | 23 -> 32 (+9) | 23 -> 95 (+72) | 73 -> 0 | 13 | 4 |
| Gemma4 e4b | 19 -> 34 (+15) | 34 -> 92 (+58) | 63 -> 0 | 16 | 1 |

## Operational Detail

| Candidate | Resolved tasks | External effects | Replanned exact | Failed attempts | Duplicate effects | Tool calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GPT-5.6 Sol (xhigh) | 60 -> 69 (+9) | 41 -> 20 (-21) | 4 -> 16 (+12) | 0/200 -> 0/200 (+0) | 0 -> 0 (+0) | 2375 -> 2384 (+9) |
| Gemini 3.6 Flash | 32 -> 58 (+26) | 79 -> 20 (-59) | 0 -> 25 (+25) | 0/200 -> 0/200 (+0) | 0 -> 0 (+0) | 1413 -> 1536 (+123) |
| Qwen3.6 35B | 22 -> 32 (+10) | 93 -> 20 (-73) | 2 -> 14 (+12) | 8/200 -> 6/200 (-2) | 0 -> 0 (+0) | 918 -> 1024 (+106) |
| Gemma4 e4b | 19 -> 34 (+15) | 80 -> 17 (-63) | 2 -> 17 (+15) | 22/200 -> 6/200 (-16) | 0 -> 0 (+0) | 875 -> 878 (+3) |

## Interpretation

- **Exact decision** measures whether the final semantic decision matches the
  evaluator-owned oracle.
- **Correct consequence** measures whether the final simulated source state is
  correct, including safe non-execution, execution, or compensation.
- **Resolved** requires the task-level terminal result to be correct.
- **Unsafe effects** counts effects observed in the 70 worlds where the
  candidate action was not safe to execute.
- **Exact recoveries** are worlds that were semantically wrong in the direct
  arm and exact after structured governed feedback.
- **Exact regressions** are worlds exact in the direct arm but not exact in
  the governed arm. They remain visible and are not netted out.

The benchmark keeps intrinsic agent capability separate from governance
effect. A blocked unsafe effect does not retroactively make the model's
original reasoning correct.

## Evidence Boundary

The machine-readable receipt at
`results/development_leaderboard.v1.json` binds each source report hash,
source-file SHA-256, agent manifest, invocation, model configuration, and
source build. The builder recomputes all published counters from 100
row-level records and rejects mismatched summaries.

Raw traces and evaluator state were locally operated and are not bundled in
the public source release. Official rank requires evaluator custody,
reopened artifacts, sealed worlds, external audit, and repeated epochs.

Leaderboard receipt: `sha256:94f4525a9383860cf485d290657bdbe28f9c55002d722b16aac4df929714817d`
