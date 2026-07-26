"""Validate and merge 100 resumable ConsequenceBench paired-world reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
for candidate in (BENCHMARK_ROOT.parents[1], BENCHMARK_ROOT, BENCHMARK_ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (  # noqa: E402
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.pressure_episode import (  # noqa: E402
    PressureWorldSpecV1,
    build_public_pressure_specs,
)


def _without_hash(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "report_hash"}


def _identity(spec: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(spec["domain_id"]),
        int(spec["family_index"]),
        int(spec["seed"]),
        str(spec["variant_id"]),
    )


def _world_id(spec: Mapping[str, Any]) -> str:
    return PressureWorldSpecV1(
        domain_id=str(spec["domain_id"]),
        family_index=int(spec["family_index"]),
        seed=int(spec["seed"]),
        variant_id=str(spec["variant_id"]),
    ).world_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--pattern", default="world-*.json")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    paths = sorted(args.report_dir.resolve().glob(args.pattern))
    if len(paths) != 100:
        raise ValueError("exactly 100 single-world reports are required")
    reports: list[dict[str, Any]] = []
    rows_by_identity: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    report_hashes: dict[str, str] = {}
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        if report.get("report_hash") != sha256_payload(_without_hash(report)):
            raise ValueError("child report hash mismatch: " + path.name)
        if report.get("status") != "DEVELOPMENT_PREVIEW_NOT_QUALIFIED":
            raise ValueError("child report overstates evidence: " + path.name)
        if report.get("qualification_eligible") is not False:
            raise ValueError("child report claims qualification: " + path.name)
        rows = report.get("rows")
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("child must contain one world: " + path.name)
        if report.get("summary", {}).get("world_count") != 1:
            raise ValueError("child summary world count mismatch: " + path.name)
        row = rows[0]
        identity = _identity(row["spec"])
        if identity in rows_by_identity:
            raise ValueError("duplicate world identity: " + str(identity))
        if report.get("selected_domain") != identity[0]:
            raise ValueError("selected domain mismatch: " + path.name)
        rows_by_identity[identity] = row
        report_hashes[_world_id(row["spec"])] = report["report_hash"]
        reports.append(report)

    expected_specs = build_public_pressure_specs(seed=0)
    expected_identities = [_identity(spec.to_dict()) for spec in expected_specs]
    if set(rows_by_identity) != set(expected_identities):
        missing = set(expected_identities) - set(rows_by_identity)
        unexpected = set(rows_by_identity) - set(expected_identities)
        raise ValueError(
            "world coverage mismatch; missing="
            + repr(sorted(missing))
            + "; unexpected="
            + repr(sorted(unexpected))
        )

    binding_fields = (
        "schema_version",
        "agent_manifest_hash",
        "invocation_hash",
        "proposal_rounds_per_arm",
        "total_tool_budget_per_arm",
        "source_binding",
        "model",
        "agent_manifest",
        "seed",
    )
    for field in binding_fields:
        values = {json.dumps(report[field], sort_keys=True) for report in reports}
        if len(values) != 1:
            raise ValueError("child binding mismatch: " + field)

    summary_keys = set(reports[0]["summary"])
    if any(set(report["summary"]) != summary_keys for report in reports):
        raise ValueError("child summary schemas differ")
    summary = {
        key: sum(int(report["summary"][key]) for report in reports)
        for key in sorted(summary_keys)
    }
    if summary["world_count"] != 100:
        raise ValueError("merged summary must contain 100 worlds")

    first = reports[0]
    ordered_rows = [rows_by_identity[identity] for identity in expected_identities]
    payload = {
        "schema_version": "ycb100.yuvin_pressure_feedback_merged.v1",
        "status": "DEVELOPMENT_PREVIEW_NOT_QUALIFIED",
        "qualification_eligible": False,
        "difficulty_claim_eligible": False,
        "claim_boundary": "source_operated_local_development_comparison",
        "campaign_id": args.campaign_id,
        "agent_manifest_hash": first["agent_manifest_hash"],
        "invocation_hash": first["invocation_hash"],
        "proposal_rounds_per_arm": first["proposal_rounds_per_arm"],
        "total_tool_budget_per_arm": first["total_tool_budget_per_arm"],
        "source_binding": first["source_binding"],
        "model": first["model"],
        "agent_manifest": first["agent_manifest"],
        "seed": first["seed"],
        "world_report_hashes": {
            world_id: report_hashes[world_id] for world_id in sorted(report_hashes)
        },
        "summary": summary,
        "rows": ordered_rows,
    }
    payload["report_hash"] = sha256_payload(payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {"report_hash": payload["report_hash"], "summary": summary},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
