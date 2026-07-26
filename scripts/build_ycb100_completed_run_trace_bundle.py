"""Export exact public worlds and detailed traces from completed ConsequenceBench runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
for candidate in (BENCHMARK_ROOT.parents[1], BENCHMARK_ROOT, BENCHMARK_ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (  # noqa: E402
    canonical_json,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.pressure_agent import (  # noqa: E402
    PressureAgentEpisodeV1,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.pressure_episode import (  # noqa: E402
    PressureWorldSpecV1,
    build_public_pressure_specs,
)


SCHEMA_VERSION = "ycb100.completed_run_trace_bundle.v1"
REPORTS = (
    (
        "gemini_3_6_flash",
        "Gemini 3.6 Flash",
        "gemini36-yuvin-full100.json",
        "GEMINI36_100_WORLD_EXECUTION_TRACES.jsonl",
    ),
    (
        "gpt_5_6_sol_xhigh",
        "GPT-5.6 Sol xhigh",
        "gpt56-sol-yuvin-full100.json",
        "GPT56_SOL_100_WORLD_EXECUTION_TRACES.jsonl",
    ),
)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _spec_key(spec: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(spec["domain_id"]),
        int(spec["family_index"]),
        int(spec["seed"]),
        str(spec["variant_id"]),
    )


def _load_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(path.name + " must contain an object")
    expected = sha256_payload(
        {key: value for key, value in payload.items() if key != "report_hash"}
    )
    if payload.get("report_hash") != expected:
        raise ValueError(path.name + " report hash mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != 100:
        raise ValueError(path.name + " must contain exactly 100 rows")
    if int(payload.get("seed", -1)) != 0:
        raise ValueError(path.name + " is not the seed-0 campaign")
    return payload


def _world_id(spec: Mapping[str, Any]) -> str:
    return PressureWorldSpecV1(
        domain_id=str(spec["domain_id"]),
        family_index=int(spec["family_index"]),
        seed=int(spec["seed"]),
        variant_id=str(spec["variant_id"]),
    ).world_id


def _compact_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _trace_counts(trace: object) -> str:
    if not isinstance(trace, list):
        return "none"
    counts = Counter(
        str(item.get("actor") or "?") + ":" + str(item.get("type") or "?")
        for item in trace
        if isinstance(item, Mapping)
    )
    return ", ".join(key + "=" + str(value) for key, value in sorted(counts.items()))


def _lifecycle_trace(observation: object) -> str:
    if not isinstance(observation, Mapping):
        return "none"
    trace = observation.get("trace")
    if not isinstance(trace, list):
        return "none"
    events: list[str] = []
    for item in trace:
        if not isinstance(item, Mapping):
            continue
        event = str(item.get("event") or "?")
        state = str(item.get("state") or "")
        events.append(event + ("(" + state + ")" if state else ""))
    return " -> ".join(events) if events else "none"


def _round_lines(round_payload: Mapping[str, Any]) -> list[str]:
    attempt = round_payload["agent_attempt"]
    adapter = attempt["adapter_run"]
    candidate = attempt.get("candidate")
    decision = adapter.get("decision") or {}
    evaluation = adapter.get("evaluation") or {}
    observation = round_payload.get("observation")
    feedback = round_payload.get("boundary_feedback") or {}
    rationale = decision.get("rationale_record_ids") or []
    candidate_summary = "none"
    if isinstance(candidate, Mapping):
        candidate_summary = (
            "candidate_id="
            + str(candidate.get("candidate_id") or "")
            + "; action_type="
            + str(candidate.get("action_type") or "")
            + "; tenant="
            + str(candidate.get("tenant_id") or "")
            + "; target="
            + _compact_json(candidate.get("target_claim") or {})
            + "; evidence="
            + _compact_json(candidate.get("evidence_handles") or [])
            + "; payload_hash="
            + str(candidate.get("payload_hash") or "")
        )
    observation_summary = "none"
    service_calls: object = []
    if isinstance(observation, Mapping):
        service_calls = observation.get("service_calls") or []
        observation_summary = (
            "terminal="
            + str(observation.get("canonical_terminal_state") or "")
            + "; error="
            + str(observation.get("error_code") or "")
            + "; attempted_effects="
            + str(observation.get("attempted_external_effect_count") or 0)
            + "; external_effects="
            + str(observation.get("external_effect_count") or 0)
            + "; connector_invocations="
            + str(observation.get("connector_invocation_count") or 0)
            + "; readbacks="
            + str(observation.get("source_readback_count") or 0)
            + "; effect_id="
            + str(observation.get("effect_id") or "")
        )
    return [
        "- Round "
        + str(round_payload["proposal_round"])
        + ": decision=`"
        + str(round_payload.get("decision") or "")
        + "`; status=`"
        + str(adapter.get("status") or "")
        + "`; exit="
        + str(adapter.get("exit_code"))
        + "; confidence="
        + str(decision.get("confidence_basis_points"))
        + "; tool calls="
        + str(evaluation.get("tool_call_count") or 0)
        + "; inspected records="
        + str(evaluation.get("inspected_record_count") or 0)
        + "; execution suppressed="
        + str(bool(round_payload.get("execution_suppressed"))).lower()
        + ".",
        "  Candidate: " + candidate_summary + ".",
        "  Rationale records: "
        + (", ".join("`" + str(item) + "`" for item in rationale) if rationale else "none")
        + ".",
        "  Agent trace: "
        + _trace_counts(adapter.get("trace"))
        + "; trace hash=`"
        + str(adapter.get("trace_hash") or "")
        + "`.",
        "  Boundary observation: " + observation_summary + ".",
        "  Boundary services: " + _compact_json(service_calls) + ".",
        "  Lifecycle/effect trace: " + _lifecycle_trace(observation) + ".",
        "  Feedback: status=`"
        + str(feedback.get("status") or "")
        + "`; boundary_state=`"
        + str(feedback.get("boundary_state") or "")
        + "`; reasons="
        + _compact_json(feedback.get("reason_codes") or [])
        + "; retry_permitted="
        + str(bool(feedback.get("retry_permitted"))).lower()
        + "; effect_committed="
        + str(bool(feedback.get("effect_committed"))).lower()
        + "; source_readback_verified="
        + str(bool(feedback.get("source_readback_verified"))).lower()
        + ".",
    ]


def _arm_table_line(name: str, arm: Mapping[str, Any]) -> str:
    return (
        "| "
        + name
        + " | "
        + str(arm["final_decision"])
        + " | "
        + ("yes" if arm["final_semantic_exact"] else "no")
        + " | "
        + ("yes" if arm["consequence_correct"] else "no")
        + " | "
        + ("yes" if arm["task_resolved"] else "no")
        + " | "
        + str(arm["unsafe_effect_count"])
        + " | "
        + str(arm["attempted_external_effect_count"])
        + " | "
        + str(arm["external_effect_count"])
        + " | "
        + str(arm["connector_invocation_count"])
        + " | "
        + str(arm["source_readback_count"])
        + " | "
        + str(arm["tool_call_count"])
        + " | "
        + ("yes" if arm["replanned_to_exact"] else "no")
        + " |"
    )


def _summary_table(report_payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    rows = [
        "| Measure | Gemini direct | Gemini + Yuvin | GPT direct | GPT + Yuvin |",
        "|---|---:|---:|---:|---:|",
    ]
    fields = (
        ("Worlds", "world_count", "world_count"),
        ("Proposal attempts", "proposal_attempt_count_per_arm", "proposal_attempt_count_per_arm"),
        ("Agent failures", "direct_agent_failure_count", "governed_agent_failure_count"),
        (
            "Final semantic exact",
            "direct_final_semantic_exact_count",
            "governed_final_semantic_exact_count",
        ),
        (
            "Correct consequences",
            "direct_consequence_correct_count",
            "governed_consequence_correct_count",
        ),
        ("Fully resolved", "direct_task_resolved_count", "governed_task_resolved_count"),
        ("Unsafe effects", "direct_unsafe_effect_count", "governed_unsafe_effect_count"),
        ("External effects", "direct_external_effect_count", "governed_external_effect_count"),
        (
            "Replanned to exact",
            "direct_replanned_to_exact_count",
            "governed_replanned_to_exact_count",
        ),
        ("Tool calls", "direct_tool_call_count", "governed_tool_call_count"),
    )
    gemini = report_payloads["gemini_3_6_flash"]["summary"]
    gpt = report_payloads["gpt_5_6_sol_xhigh"]["summary"]
    for label, direct_key, governed_key in fields:
        if label in {"Worlds", "Proposal attempts"}:
            rows.append(
                "| "
                + label
                + " | "
                + str(gemini[direct_key])
                + " | "
                + str(gemini[governed_key])
                + " | "
                + str(gpt[direct_key])
                + " | "
                + str(gpt[governed_key])
                + " |"
            )
        else:
            rows.append(
                "| "
                + label
                + " | "
                + str(gemini[direct_key])
                + " | "
                + str(gemini[governed_key])
                + " | "
                + str(gpt[direct_key])
                + " | "
                + str(gpt[governed_key])
                + " |"
            )
    return rows


def build_bundle(run_dir: Path) -> dict[str, Any]:
    report_payloads: dict[str, dict[str, Any]] = {}
    report_paths: dict[str, Path] = {}
    report_rows: dict[str, dict[tuple[str, int, int, str], dict[str, Any]]] = {}
    for report_id, _, source_name, _ in REPORTS:
        source_path = run_dir / source_name
        payload = _load_report(source_path)
        report_payloads[report_id] = payload
        report_paths[report_id] = source_path
        report_rows[report_id] = {
            _spec_key(row["spec"]): row for row in payload["rows"]
        }

    specs = build_public_pressure_specs(seed=0)
    public_worlds: list[Mapping[str, Any]] = []
    evaluator_truth: list[Mapping[str, Any]] = []
    regenerated: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for ordinal, spec in enumerate(specs, start=1):
        episode = PressureAgentEpisodeV1(spec, tool_budget=12)
        start = episode.agent_start(proposal_round=1, proposal_round_limit=2)
        start_hash = sha256_payload(start)
        key = _spec_key(spec.to_dict())
        for report_id in report_payloads:
            if report_rows[report_id][key]["base_agent_start_hash"] != start_hash:
                raise ValueError(report_id + " base agent-start hash mismatch for " + spec.world_id)
        public_payload = {
            "schema_version": SCHEMA_VERSION,
            "ordinal": ordinal,
            "world_id": spec.world_id,
            "world_hash": spec.world_hash,
            "recorded_base_agent_start_hash": start_hash,
            "episode_start": start,
        }
        public_worlds.append(public_payload)
        truth_payload = {
            "schema_version": SCHEMA_VERSION,
            "ordinal": ordinal,
            "world_id": spec.world_id,
            "world_hash": spec.world_hash,
            "domain_id": spec.domain_id,
            "family_index": spec.family_index,
            "operation": episode.episode.operation,
            "tenant_id": episode.episode.tenant_id,
            "subject_id": episode.episode.subject_id,
            "request_nonce": episode.episode.request_nonce,
            "oracle": episode.episode.oracle.to_dict(),
        }
        evaluator_truth.append(truth_payload)
        regenerated[key] = {
            "spec": spec,
            "episode": episode,
            "start": start,
            "start_hash": start_hash,
            "public_payload": public_payload,
            "truth": truth_payload,
        }

    public_path = run_dir / "ACTUAL_100_PUBLIC_WORLDS.jsonl"
    truth_path = run_dir / "ACTUAL_100_EVALUATOR_TRUTH.jsonl"
    _write_jsonl(public_path, public_worlds)
    _write_jsonl(truth_path, evaluator_truth)

    trace_paths: dict[str, Path] = {}
    for report_id, _, _, trace_name in REPORTS:
        trace_path = run_dir / trace_name
        trace_rows: list[Mapping[str, Any]] = []
        for ordinal, spec in enumerate(specs, start=1):
            key = _spec_key(spec.to_dict())
            row = report_rows[report_id][key]
            trace_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ordinal": ordinal,
                    "world_id": spec.world_id,
                    "world_hash": spec.world_hash,
                    "source_report_hash": report_payloads[report_id]["report_hash"],
                    "row": row,
                }
            )
        _write_jsonl(trace_path, trace_rows)
        trace_paths[report_id] = trace_path

    markdown: list[str] = [
        "# ConsequenceBench Actual 100 Worlds And Four-Arm Execution Traces",
        "",
        "Generated directly from the completed Gemini 3.6 Flash and GPT-5.6 Sol "
        "xhigh seed-0 reports. This is local development evidence and remains "
        "`DEVELOPMENT_PREVIEW_NOT_QUALIFIED`.",
        "",
        "## Integrity",
        "",
        "- Every source report contains exactly 100 rows and its internal report hash validates.",
        "- Every regenerated public first-round payload hash matches both campaigns.",
        "- Direct and governed rows are retained exactly in the model-specific JSONL files.",
        "- Agent JSONL traces retain actor, event type, sequence, payload/result hashes, and trace hash.",
        "- Boundary observations retain explicit service calls, lifecycle transitions, connector "
        "invocations, source effects, source readback, compensation, and error codes.",
        "- Raw tool payloads/results were intentionally hash-minimized by the original runner; they "
        "cannot be reconstructed beyond the exact public world, decision rationale records, and "
        "recorded hashes.",
        "",
        "## Overall Results",
        "",
        *_summary_table(report_payloads),
        "",
        "## Artifact Index",
        "",
        "- `ACTUAL_100_PUBLIC_WORLDS.jsonl`: exact first-round public payload for all 100 worlds.",
        "- `ACTUAL_100_EVALUATOR_TRUTH.jsonl`: evaluator-only oracle truth and exact required records.",
        "- `GEMINI36_100_WORLD_EXECUTION_TRACES.jsonl`: exact Gemini direct/governed report rows.",
        "- `GPT56_SOL_100_WORLD_EXECUTION_TRACES.jsonl`: exact GPT direct/governed report rows.",
        "- `gemini36-yuvin-full100.json`: original merged Gemini report.",
        "- `gpt56-sol-yuvin-full100.json`: original merged GPT report.",
        "- `ACTUAL_100_WORLD_TRACE_MANIFEST.json`: hashes and validation counts for this bundle.",
        "",
        "## Reading Each World",
        "",
        "Each world below reports the evaluator decision, actual model decisions, source consequence, "
        "unsafe-effect count, and the two proposal rounds. The JSONL artifacts contain the complete "
        "structured objects and all event hashes.",
        "",
    ]

    labels = {report_id: label for report_id, label, _, _ in REPORTS}
    for ordinal, spec in enumerate(specs, start=1):
        key = _spec_key(spec.to_dict())
        material = regenerated[key]
        start = material["start"]
        truth = material["truth"]
        oracle = truth["oracle"]
        objective = start.get("objective") or {}
        markdown.extend(
            [
                "## "
                + str(ordinal).zfill(3)
                + " "
                + spec.world_id,
                "",
                "- Domain: `" + spec.domain_id + "`; family: `" + str(spec.family_index) + "`.",
                "- Operation: `" + str(truth["operation"]) + "`; expected decision: `"
                + str(oracle["decision"])
                + "`.",
                "- Oracle reasons: " + _compact_json(oracle["reason_codes"]) + ".",
                "- Required oracle records: "
                + ", ".join("`" + str(item) + "`" for item in oracle["required_record_ids"])
                + ".",
                "- Objective: `" + _compact_json(objective) + "`.",
                "- Public input: "
                + str(len(start.get("records") or []))
                + " records, "
                + str(len(start.get("case_history") or []))
                + " history messages, "
                + str(len(canonical_json(start).encode("utf-8")))
                + " UTF-8 bytes.",
                "- World hash: `" + spec.world_hash + "`.",
                "- First-round payload hash: `" + str(material["start_hash"]) + "`.",
                "",
            ]
        )
        for report_id, _, _, _ in REPORTS:
            row = report_rows[report_id][key]
            markdown.extend(
                [
                    "### " + labels[report_id],
                    "",
                    "- Arm order: `" + " -> ".join(row["arm_order"]) + "`.",
                    "- Expected decision: `" + str(row["expected_decision"]) + "`.",
                    "",
                    "| Arm | Final decision | Semantic exact | Consequence correct | Resolved | "
                    "Unsafe | Attempted effects | Source effects | Connector calls | Readbacks | "
                    "Tool calls | Replanned exact |",
                    "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
                    _arm_table_line("Direct", row["direct"]),
                    _arm_table_line("Yuvin", row["governed"]),
                    "",
                    "#### Direct rounds",
                    "",
                ]
            )
            for round_payload in row["direct"]["rounds"]:
                markdown.extend(_round_lines(round_payload))
            markdown.extend(["", "#### Yuvin-governed rounds", ""])
            for round_payload in row["governed"]["rounds"]:
                markdown.extend(_round_lines(round_payload))
            markdown.extend(
                [
                    "",
                    "- Row hash: `" + str(row["row_hash"]) + "`.",
                    "",
                ]
            )

    markdown_path = run_dir / "ACTUAL_100_WORLD_EXECUTION_TRACES.md"
    markdown_path.write_text(
        "\n".join(markdown).rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )

    artifacts = {
        public_path.name: {
            "sha256": _file_hash(public_path),
            "line_count": 100,
        },
        truth_path.name: {
            "sha256": _file_hash(truth_path),
            "line_count": 100,
        },
        markdown_path.name: {
            "sha256": _file_hash(markdown_path),
            "world_section_count": 100,
        },
    }
    for report_id, _, _, _ in REPORTS:
        artifacts[trace_paths[report_id].name] = {
            "sha256": _file_hash(trace_paths[report_id]),
            "line_count": 100,
        }
        artifacts[report_paths[report_id].name] = {
            "sha256": _file_hash(report_paths[report_id]),
            "internal_report_hash": report_payloads[report_id]["report_hash"],
            "row_count": 100,
        }

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "DEVELOPMENT_PREVIEW_NOT_QUALIFIED",
        "world_count": 100,
        "model_count": 2,
        "arm_count_per_model": 2,
        "proposal_rounds_per_arm": 2,
        "regenerated_agent_start_hash_mismatch_count": 0,
        "source_report_validation_failure_count": 0,
        "artifacts": artifacts,
    }
    manifest["manifest_hash"] = sha256_payload(manifest)
    manifest_path = run_dir / "ACTUAL_100_WORLD_TRACE_MANIFEST.json"
    _write_json(manifest_path, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export exact ConsequenceBench worlds and four-arm execution traces"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        raise ValueError("run directory does not exist")
    manifest = build_bundle(run_dir)
    print(json.dumps(manifest, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
