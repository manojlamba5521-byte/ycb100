"""Credential-free public controls for the portable ConsequenceBench package."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import AgentManifestV1
from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.admission import (
    run_lifecycle_admission_campaign,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.environment import (
    ConsequenceLifecycleEnvironment,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.frozen_pack import (
    RECEIPT_NAME,
    materialize_frozen_pack,
    verify_frozen_pack,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.generator import (
    generate_canonical_worlds,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.oracle import (
    assert_no_oracle_data,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.reference import (
    run_reference_campaign,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_capability import run_pressure_capability
from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_admission import (
    build_pressure_admission_report,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_redteam import (
    build_pressure_redteam_admission_report,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_trial_binding import (
    bind_pressure_trial_report,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.jsonl_adapter import AdapterInvocationV1
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.lifecycle_jsonl import (
    LifecycleJsonlInvocationV1,
    LifecycleJsonlRunner,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.review_judge import (
    ReviewSubjectV1,
    run_advisory_review,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.scenario_manifest import (
    validate_scenario_manifest,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.pressure_episode import (
    PRESSURE_TOOL_BUDGET,
    build_public_pressure_specs,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.family_corpus import (
    build_deterministic_shortcut_baselines,
    build_public_raw_causal_family_corpus,
    evaluate_shortcut_admission,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_episode import (
    CompositionalCausalEpisodeV1,
    build_causal_sister,
    build_invariance_sister,
    build_public_compositional_specs,
)


PUBLIC_CONTROLS_SCHEMA_VERSION = "ycb100.acc.public_controls.v1"
LIFECYCLE_CONTROLS_SCHEMA_VERSION = "ycb100.consequence_lifecycle.cli_controls.v1"
LIFECYCLE_AGENT_REPORT_SCHEMA_VERSION = "ycb100.consequence_lifecycle.cli_agent_report.v1"
_FORBIDDEN_AGENT_VIEW_TERMS = (
    "expected_disposition",
    "evaluator_expected",
    "oracle",
    "causal_edges",
    "shortcut_label",
    "mechanism_id",
)


def _hashed_report(payload: dict[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    report["report_hash"] = sha256_payload(report)
    return report


def _parse_command_payload(raw_json: str | None) -> tuple[str, ...]:
    if raw_json is None:
        raise ValueError("agent command JSON is required")
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("agent command must be valid JSON") from exc
    if (
        not isinstance(payload, list)
        or not payload
        or not all(isinstance(item, str) and item.strip() for item in payload)
    ):
        raise ValueError("agent command must be a non-empty JSON string array")
    return tuple(item.strip() for item in payload)


def run_lifecycle_controls(*, seed: int = 0) -> dict[str, Any]:
    """Run deterministic independent lifecycle admission without qualifying a release."""
    campaign = run_lifecycle_admission_campaign(seed=seed)
    failures = list(campaign.failure_reasons)
    if not campaign.valid_for_qualification and not failures:
        failures.append("independent_admission_not_valid")
    return _hashed_report(
        {
            "schema_version": LIFECYCLE_CONTROLS_SCHEMA_VERSION,
            "status": "CONTROL_ONLY",
            "release_status": "DEVELOPMENT_PREVIEW_NOT_QUALIFIED",
            "qualification_eligible": False,
            "seed": seed,
            "independent_admission": campaign.to_dict(),
            "control_failures": failures,
            "failure_count": len(failures),
        }
    )


def _selected_lifecycle_worlds(
    *,
    seed: int,
    scenario_ids: tuple[str, ...],
    limit: int | None,
) -> tuple[Any, ...]:
    worlds = generate_canonical_worlds(seed=seed, variant_id="base")
    by_scenario = {world.scenario_id: world for world in worlds}
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("lifecycle-agent scenario identifiers must be unique")
    unknown = sorted(set(scenario_ids).difference(by_scenario))
    if unknown:
        raise ValueError("unknown canonical scenario_id: " + ", ".join(unknown))
    selected = (
        tuple(by_scenario[scenario_id] for scenario_id in scenario_ids)
        if scenario_ids
        else worlds
    )
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("lifecycle-agent limit must be a positive integer")
        selected = selected[:limit]
    if not selected:
        raise ValueError("lifecycle-agent requires at least one canonical base world")
    return selected


def _effect_result(final_result: object) -> dict[str, Any]:
    if not isinstance(final_result, dict):
        return {
            "available": False,
            "source_effect_count": 0,
            "connector_invocation_count": 0,
            "duplicate_effect_count": 0,
            "unsafe_effect_count": 0,
            "false_verified_count": 0,
            "outstanding_obligation_count": 0,
            "compensation_count": 0,
        }
    fields = (
        "source_effect_count",
        "connector_invocation_count",
        "duplicate_effect_count",
        "unsafe_effect_count",
        "false_verified_count",
        "outstanding_obligation_count",
        "compensation_count",
    )
    return {
        "available": True,
        **{field: int(final_result.get(field, 0)) for field in fields},
    }


def run_lifecycle_agent(
    *,
    command: tuple[str, ...],
    campaign_id: str,
    seed: int = 0,
    scenario_ids: tuple[str, ...] = (),
    limit: int | None = None,
    state_root: Path | None = None,
    timeout_seconds: int = 180,
    max_messages: int = 256,
    max_restarts: int = 4,
) -> dict[str, Any]:
    """Run one arbitrary JSONL candidate over selected canonical base worlds."""
    normalized_campaign_id = str(campaign_id or "").strip()
    if not normalized_campaign_id or len(normalized_campaign_id) > 256 or "\x00" in normalized_campaign_id:
        raise ValueError("campaign_id must be a non-empty bounded string")
    invocation = LifecycleJsonlInvocationV1(
        command=command,
        timeout_seconds=timeout_seconds,
        max_messages=max_messages,
        max_restarts=max_restarts,
    )
    worlds = _selected_lifecycle_worlds(
        seed=seed,
        scenario_ids=scenario_ids,
        limit=limit,
    )
    command_hash = sha256_payload({"command": list(invocation.command)})
    selected_world_set_hash = sha256_payload(
        [
            {
                "scenario_id": world.scenario_id,
                "variant_id": world.variant_id,
                "world_hash": world.world_hash,
            }
            for world in worlds
        ]
    )

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if state_root is None:
        temporary = tempfile.TemporaryDirectory(prefix="ycb100-lifecycle-cli-")
        root = Path(temporary.name)
    else:
        root = state_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    try:
        for ordinal, world in enumerate(worlds):
            episode_root = root / f"{ordinal:03d}-{world.scenario_id}"
            if episode_root.exists():
                raise ValueError(
                    "lifecycle state directory already exists: " + episode_root.name
                )
            environment = ConsequenceLifecycleEnvironment(world, episode_root)
            candidate_start_view = environment.initial_agent_view
            assert_no_oracle_data(candidate_start_view)
            initial_source_state_hash = environment.source.state_hash
            run_result = LifecycleJsonlRunner().run_episode(
                invocation=invocation,
                environment=environment,
            )
            final_source_state_hash = environment.source.state_hash
            rows.append(
                {
                    "scenario_id": world.scenario_id,
                    "domain_id": world.domain_id,
                    "variant_id": "base",
                    "candidate_start_view": candidate_start_view,
                    "candidate_start_view_hash": sha256_payload(candidate_start_view),
                    "exact_source_hashes": {
                        "catalog_binding_hash": world.catalog_binding_hash,
                        "world_hash": world.world_hash,
                        "initial_external_source_state_hash": initial_source_state_hash,
                        "final_external_source_state_hash": final_source_state_hash,
                    },
                    "trace_result": run_result.to_dict(),
                    "effect_result": _effect_result(run_result.final_result),
                }
            )
    finally:
        if temporary is not None:
            temporary.cleanup()

    summary = {
        "attempt_count": len(rows),
        "completed_count": sum(
            row["trace_result"]["status"] == "COMPLETED" for row in rows
        ),
        "agent_failure_count": sum(
            row["trace_result"]["status"] != "COMPLETED" for row in rows
        ),
        "correct_consequence_count": sum(
            bool((row["trace_result"].get("final_result") or {}).get("correct_consequence"))
            for row in rows
        ),
        "fully_resolved_count": sum(
            bool((row["trace_result"].get("final_result") or {}).get("fully_resolved"))
            for row in rows
        ),
        "unsafe_effect_count": sum(
            row["effect_result"]["unsafe_effect_count"] for row in rows
        ),
        "false_verified_count": sum(
            row["effect_result"]["false_verified_count"] for row in rows
        ),
        "source_effect_count": sum(
            row["effect_result"]["source_effect_count"] for row in rows
        ),
        "connector_invocation_count": sum(
            row["effect_result"]["connector_invocation_count"] for row in rows
        ),
        "duplicate_effect_count": sum(
            row["effect_result"]["duplicate_effect_count"] for row in rows
        ),
        "outstanding_obligation_count": sum(
            row["effect_result"]["outstanding_obligation_count"] for row in rows
        ),
        "compensation_count": sum(
            row["effect_result"]["compensation_count"] for row in rows
        ),
    }
    return _hashed_report(
        {
            "schema_version": LIFECYCLE_AGENT_REPORT_SCHEMA_VERSION,
            "status": "DEVELOPMENT_PREVIEW_NOT_QUALIFIED",
            "qualification_eligible": False,
            "track": "consequence_lifecycle",
            "campaign_id": normalized_campaign_id,
            "seed": seed,
            "variant_id": "base",
            "candidate_command_hash": command_hash,
            "selected_world_set_hash": selected_world_set_hash,
            "execution_tier": "CONTAINMENT_ONLY",
            "isolation_claim": "NOT_OS_SANDBOXED",
            "summary": summary,
            "failure_count": summary["agent_failure_count"],
            "rows": rows,
        }
    )


def run_public_controls() -> dict[str, Any]:
    """Run pure ConsequenceBench structural controls without model, Yuvin, or credentials."""
    corpus = build_public_raw_causal_family_corpus()
    rendered_views = [json.dumps(view, sort_keys=True).casefold() for view in corpus.agent_views()]
    leakage = [
        {"family_index": index, "term": term}
        for index, view in enumerate(rendered_views)
        for term in _FORBIDDEN_AGENT_VIEW_TERMS
        if term in view
    ]
    shortcut = evaluate_shortcut_admission(
        corpus,
        build_deterministic_shortcut_baselines(corpus),
    )
    compositional_rows: list[dict[str, Any]] = []
    compositional_leakage: list[dict[str, Any]] = []
    for spec in build_public_compositional_specs(seed=17):
        base = CompositionalCausalEpisodeV1(spec)
        causal = CompositionalCausalEpisodeV1(build_causal_sister(spec))
        invariant = CompositionalCausalEpisodeV1(build_invariance_sister(spec))
        view = base.agent_view()
        rendered = json.dumps(view, sort_keys=True).casefold()
        for term in (
            "required_outcome",
            "expected_disposition",
            "terminal_strategy",
            "required_prefix",
            "source_match",
            "authority_gap",
            "safety_conflict",
        ):
            if term in rendered:
                compositional_leakage.append({"world_id": spec.world_id, "term": term})
        base_result = base.reference_execute()
        causal_result = causal.reference_execute()
        invariant_result = invariant.reference_execute()
        compositional_rows.append(
            {
                "world_hash": spec.world_hash,
                "base_terminal": base_result.terminal_disposition,
                "causal_sister_terminal": causal_result.terminal_disposition,
                "invariance_sister_terminal": invariant_result.terminal_disposition,
                "base_solved": base_result.correct_disposition,
                "causal_sister_solved": causal_result.correct_disposition,
                "invariance_sister_solved": invariant_result.correct_disposition,
                "causal_change_observed": base_result.terminal_disposition != causal_result.terminal_disposition,
                "invariance_preserved": base_result.terminal_disposition == invariant_result.terminal_disposition,
            }
        )
    compositional_failure_count = len(compositional_leakage) + sum(
        int(
            not row["base_solved"]
            or not row["causal_sister_solved"]
            or not row["invariance_sister_solved"]
            or not row["causal_change_observed"]
            or not row["invariance_preserved"]
        )
        for row in compositional_rows
    )
    report = {
        "schema_version": PUBLIC_CONTROLS_SCHEMA_VERSION,
        "status": "CONTROL_ONLY",
        "qualification_eligible": False,
        "corpus_hash": corpus.corpus_hash,
        "family_count": len(corpus.families),
        "domain_counts": {
            domain_id: sum(family.domain_id == domain_id for family in corpus.families)
            for domain_id in sorted({family.domain_id for family in corpus.families})
        },
        "agent_view_leakage": leakage,
        "shortcut_baseline_admission": {
            "accuracy_basis_points": shortcut.accuracy_basis_points,
            "maximum_basis_points": shortcut.maximum_basis_points,
            "admitted": shortcut.admitted,
            "baseline_scores": [
                {
                    "baseline_id": score.baseline_id,
                    "accuracy_basis_points": score.accuracy_basis_points,
                    "tool_call_count": 0,
                }
                for score in shortcut.baseline_scores
            ],
        },
        "compositional_public_control": {
            "world_count": len(compositional_rows),
            "causal_sister_count": len(compositional_rows),
            "invariance_sister_count": len(compositional_rows),
            "agent_view_leakage": compositional_leakage,
            "failure_count": compositional_failure_count,
            "rows": compositional_rows,
        },
    }
    report["failure_count"] = len(leakage) + int(not shortcut.admitted) + compositional_failure_count
    report["report_hash"] = sha256_payload(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ConsequenceBench public controls")
    subcommands = parser.add_subparsers(dest="command", required=True)
    control = subcommands.add_parser("public-controls", help="run credential-free public ConsequenceBench controls")
    control.add_argument("--out", type=Path)
    manifest = subcommands.add_parser(
        "validate-scenarios",
        help="validate all 100 catalog-to-executable-world bindings",
    )
    manifest.add_argument("--out", type=Path)
    pressure = subcommands.add_parser(
        "pressure-controls",
        help="run credential-free Pressure Worlds long-context pressure-world admission",
    )
    pressure.add_argument("--seed", type=int, default=0)
    pressure.add_argument("--out", type=Path)
    lifecycle_controls = subcommands.add_parser(
        "lifecycle-controls",
        help="run deterministic independent Consequence Lifecycle admission controls",
    )
    lifecycle_controls.add_argument("--seed", type=int, default=0)
    lifecycle_controls.add_argument("--out", type=Path)
    lifecycle_reference = subcommands.add_parser(
        "lifecycle-reference-controls",
        help="prove evaluator-only reachability across all 100 canonical base worlds",
    )
    lifecycle_reference.add_argument("--seed", type=int, default=23)
    lifecycle_reference.add_argument("--out", type=Path)
    lifecycle_agent = subcommands.add_parser(
        "lifecycle-agent",
        help="run an arbitrary JSONL candidate on canonical base lifecycle worlds",
    )
    lifecycle_command = lifecycle_agent.add_mutually_exclusive_group(required=True)
    lifecycle_command.add_argument("--agent-command-json")
    lifecycle_command.add_argument("--agent-command-file", type=Path)
    lifecycle_agent.add_argument("--campaign-id", required=True)
    lifecycle_agent.add_argument("--seed", type=int, default=0)
    lifecycle_agent.add_argument("--scenario-id", action="append", default=[])
    lifecycle_agent.add_argument("--limit", type=int)
    lifecycle_agent.add_argument("--state-root", type=Path)
    lifecycle_agent.add_argument("--timeout-seconds", type=int, default=180)
    lifecycle_agent.add_argument("--max-messages", type=int, default=256)
    lifecycle_agent.add_argument("--max-restarts", type=int, default=4)
    lifecycle_agent.add_argument("--out", type=Path)
    materialize_pack = subcommands.add_parser(
        "lifecycle-materialize-pack",
        help="materialize deterministic public and evaluator 300-world archives",
    )
    materialize_pack.add_argument("--output-dir", type=Path, required=True)
    materialize_pack.add_argument("--seed", type=int, default=23)
    materialize_pack.add_argument("--out", type=Path)
    verify_pack = subcommands.add_parser(
        "lifecycle-verify-pack",
        help="verify a frozen lifecycle receipt, archives, children, joins, and sources",
    )
    verify_pack.add_argument("--receipt", type=Path, required=True)
    verify_pack.add_argument("--out", type=Path)
    redteam = subcommands.add_parser(
        "pressure-redteam-controls",
        help="run evaluator-keyed Pressure Worlds adaptive red-team admission",
    )
    redteam.add_argument("--seed", type=int, default=0)
    redteam.add_argument("--evaluator-key-file", type=Path, required=True)
    redteam.add_argument("--out", type=Path)
    bind_trial = subcommands.add_parser(
        "pressure-bind-trial",
        help="bind an immutable pressure receipt to a repeated-trial identity",
    )
    bind_trial.add_argument("--report", type=Path, required=True)
    bind_trial.add_argument("--expected-source-hash", required=True)
    bind_trial.add_argument("--model-id", required=True)
    bind_trial.add_argument("--seed", type=int, required=True)
    bind_trial.add_argument("--trial-index", type=int, required=True)
    bind_trial.add_argument("--out", type=Path, required=True)
    agent = subcommands.add_parser(
        "pressure-agent",
        help="run a declared JSONL agent on the direct Pressure Worlds capability track",
    )
    agent.add_argument("--agent-manifest", type=Path, required=True)
    command_input = agent.add_mutually_exclusive_group(required=True)
    command_input.add_argument("--agent-command-json")
    command_input.add_argument("--agent-command-file", type=Path)
    agent.add_argument("--campaign-id", required=True)
    agent.add_argument("--seed", type=int, default=0)
    agent.add_argument("--limit", type=int)
    agent.add_argument("--timeout-seconds", type=int, default=180)
    agent.add_argument("--max-messages", type=int, default=64)
    agent.add_argument("--tool-budget", type=int, default=PRESSURE_TOOL_BUDGET)
    agent.add_argument("--out", type=Path)
    review = subcommands.add_parser(
        "advisory-review",
        help="produce an advisory-only qualitative review of a public agent trace",
    )
    review.add_argument("--input", type=Path, required=True)
    review.add_argument("--provider", choices=("openai", "gemini", "anthropic"), required=True)
    review.add_argument("--model", required=True)
    review.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "public-controls":
        report = run_public_controls()
    elif args.command == "validate-scenarios":
        report = validate_scenario_manifest()
    elif args.command == "pressure-controls":
        report = build_pressure_admission_report(seed=args.seed).to_dict()
        report["failure_count"] = len(report["admission_failures"])
        report["report_hash"] = sha256_payload(
            {key: value for key, value in report.items() if key != "report_hash"}
        )
    elif args.command == "lifecycle-controls":
        report = run_lifecycle_controls(seed=args.seed)
    elif args.command == "lifecycle-reference-controls":
        report = run_reference_campaign(seed=args.seed, variant_id="base").to_dict()
    elif args.command == "lifecycle-agent":
        command_json = (
            args.agent_command_file.read_text(encoding="utf-8-sig")
            if args.agent_command_file is not None
            else args.agent_command_json
        )
        report = run_lifecycle_agent(
            command=_parse_command_payload(command_json),
            campaign_id=args.campaign_id,
            seed=args.seed,
            scenario_ids=tuple(args.scenario_id),
            limit=args.limit,
            state_root=args.state_root,
            timeout_seconds=args.timeout_seconds,
            max_messages=args.max_messages,
            max_restarts=args.max_restarts,
        )
    elif args.command == "lifecycle-materialize-pack":
        report = materialize_frozen_pack(args.output_dir, seed=args.seed)
        if not (args.output_dir / RECEIPT_NAME).is_file():
            raise RuntimeError("frozen pack receipt was not published")
    elif args.command == "lifecycle-verify-pack":
        report = verify_frozen_pack(args.receipt)
    elif args.command == "pressure-redteam-controls":
        report = build_pressure_redteam_admission_report(
            seed=args.seed,
            evaluator_key=args.evaluator_key_file.read_bytes(),
        ).to_dict()
        report["failure_count"] = len(report["admission_failures"])
        report["report_hash"] = sha256_payload(
            {key: value for key, value in report.items() if key != "report_hash"}
        )
    elif args.command == "pressure-bind-trial":
        if args.report.resolve() == args.out.resolve():
            raise ValueError("bound output must differ from the immutable source report")
        report = bind_pressure_trial_report(
            json.loads(args.report.read_text(encoding="utf-8-sig")),
            model_id=args.model_id,
            seed=args.seed,
            trial_index=args.trial_index,
            expected_source_report_hash=args.expected_source_hash,
        )
    elif args.command == "pressure-agent":
        manifest_payload = json.loads(args.agent_manifest.read_text(encoding="utf-8-sig"))
        command_json = (
            args.agent_command_file.read_text(encoding="utf-8-sig")
            if args.agent_command_file is not None
            else args.agent_command_json
        )
        command_payload = json.loads(command_json)
        if not isinstance(manifest_payload, dict):
            raise ValueError("agent manifest must be a JSON object")
        if (
            not isinstance(command_payload, list)
            or not command_payload
            or not all(isinstance(item, str) and item for item in command_payload)
        ):
            raise ValueError("agent command must be a non-empty JSON string array")
        specs = list(build_public_pressure_specs(seed=args.seed))
        if args.limit is not None:
            specs = specs[: args.limit]
        if not specs:
            raise ValueError("pressure-agent requires at least one world")
        report = run_pressure_capability(
            specs=specs,
            invocation=AdapterInvocationV1(
                command=tuple(command_payload),
                timeout_seconds=args.timeout_seconds,
                max_messages=args.max_messages,
            ),
            agent_manifest=AgentManifestV1(**manifest_payload),
            campaign_id=args.campaign_id,
            tool_budget=args.tool_budget,
        ).to_dict()
        report["failure_count"] = report["summary"]["agent_failure_count"]
        report["report_hash"] = sha256_payload(
            {key: value for key, value in report.items() if key != "report_hash"}
        )
    elif args.command == "advisory-review":
        subject_payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(subject_payload, dict):
            raise ValueError("advisory review input must be a JSON object")
        report = run_advisory_review(
            subject=ReviewSubjectV1.from_mapping(subject_payload),
            provider=args.provider,
            model=args.model,
        ).to_dict()
    else:
        raise AssertionError("unreachable command")
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.out is None:
        print(rendered, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    return 0 if report.get("failure_count", 0) == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
