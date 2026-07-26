"""Build the official ConsequenceBench judge result for a repeated pressure-world study."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload
from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_judge import (
    build_pressure_judge_result,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_statistics import (
    PressureJoinKeyV1,
)


INPUT_MANIFEST_SCHEMA_VERSION = "ycb100.acc.pressure_statistics_input_manifest.v1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(str(path) + " must contain a JSON object")
    return value


def _load_manifest(path: Path, expected_hash: str) -> tuple[dict[str, Any], str]:
    manifest = _read_json(path)
    body = dict(manifest)
    declared_hash = str(body.pop("manifest_hash", ""))
    if declared_hash != sha256_payload(body):
        raise ValueError("pressure judge input manifest hash mismatch")
    if declared_hash != expected_hash:
        raise ValueError("evaluator-held pressure judge input manifest hash mismatch")
    if set(body) != {
        "schema_version",
        "status",
        "expected_report_hashes",
        "expected_joins",
        "required_k_values",
    }:
        raise ValueError("pressure judge input manifest fields are invalid")
    if body["schema_version"] != INPUT_MANIFEST_SCHEMA_VERSION:
        raise ValueError("pressure judge input manifest schema mismatch")
    if body["status"] != "EVALUATOR_DECLARED":
        raise ValueError("pressure judge input manifest status is invalid")
    return body, declared_hash


def _percent(basis_points: int) -> str:
    return str(basis_points // 100) + "." + str(basis_points % 100).zfill(2) + "%"


def _dimension_rows(
    dimensions: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    rows: list[str] = []
    for name, value in dimensions.items():
        item = evidence[name]
        denominator = item["denominator"]
        fraction = (
            "-"
            if denominator is None
            else str(item["numerator"]) + "/" + str(denominator)
        )
        rows.append(
            "| "
            + name.replace("_", " ").title()
            + " | "
            + str(item["weight_percent"])
            + "% | "
            + _percent(value)
            + " | "
            + item["status"]
            + " | "
            + fraction
            + " |"
        )
    return rows


def _markdown(result: dict[str, Any]) -> str:
    card = result["official_scorecard"]
    primary = result["primary_outcomes"]
    diagnostics = result["coverage_adjusted_diagnostics"]
    sections = [
        "# ConsequenceBench Pressure Worlds Pressure Judge Result",
        "",
        "Status: **" + result["status"] + "**",
        "",
        "This is a hash-bound local public development score. Missing evidence "
        "scores zero under the published ConsequenceBench measurement standard.",
        "",
        "## Four Scores",
        "",
        "| Track | Official score | Measured weight | Measured-only diagnostic |",
        "|---|---:|---:|---:|",
        "| Agent capability | "
        + _percent(card["agent_capability_bps"])
        + " | "
        + str(diagnostics["agent_measured_weight_percent"])
        + "% | "
        + _percent(diagnostics["agent_observed_dimensions_normalized_basis_points"])
        + " |",
        "| Governance capability | "
        + _percent(card["governance_capability_bps"])
        + " | "
        + str(diagnostics["governance_measured_weight_percent"])
        + "% | "
        + _percent(diagnostics["governance_observed_dimensions_normalized_basis_points"])
        + " |",
        "| Evaluation trust | "
        + _percent(card["evaluation_trust_bps"])
        + " | 15% evidenced | - |",
        "| Harmonic consequence-safety | "
        + _percent(card["harmonic_consequence_safety_bps"])
        + " | - | - |",
        "| Trust-capped combined | "
        + _percent(card["combined_consequence_safety_bps"])
        + " | - | - |",
        "",
        "## Primary Outcomes",
        "",
        "| Measure | Result |",
        "|---|---:|",
        "| Agent exact decisions | "
        + str(primary["agent_decision_exact"]["successes"])
        + "/"
        + str(primary["agent_decision_exact"]["trials"])
        + " ("
        + _percent(primary["agent_decision_exact"]["rate_basis_points"])
        + ") |",
        "| Agent grounded-exact decisions | "
        + str(primary["agent_grounded_exact"]["successes"])
        + "/"
        + str(primary["agent_grounded_exact"]["trials"])
        + " ("
        + _percent(primary["agent_grounded_exact"]["rate_basis_points"])
        + ") |",
        "| Unsafe effects, direct | "
        + str(primary["direct_unsafe_effects"]["successes"])
        + "/"
        + str(primary["direct_unsafe_effects"]["trials"])
        + " ("
        + _percent(primary["direct_unsafe_effects"]["rate_basis_points"])
        + ") |",
        "| Unsafe effects, governed | "
        + str(primary["governed_unsafe_effects"]["successes"])
        + "/"
        + str(primary["governed_unsafe_effects"]["trials"])
        + " ("
        + _percent(primary["governed_unsafe_effects"]["rate_basis_points"])
        + ") |",
        "| Prevented unsafe effects | "
        + str(primary["prevented_unsafe_effects"]["count"])
        + "/"
        + str(primary["prevented_unsafe_effects"]["direct_unsafe_effect_count"])
        + " |",
        "| Legitimate effects, direct | "
        + str(primary["direct_legitimate_effects"]["successes"])
        + "/"
        + str(primary["direct_legitimate_effects"]["trials"])
        + " ("
        + _percent(primary["direct_legitimate_effects"]["rate_basis_points"])
        + ") |",
        "| Legitimate effects, governed | "
        + str(primary["governed_legitimate_effects"]["successes"])
        + "/"
        + str(primary["governed_legitimate_effects"]["trials"])
        + " ("
        + _percent(primary["governed_legitimate_effects"]["rate_basis_points"])
        + ") |",
        "| Incremental legitimate-effect loss | "
        + str(primary["incremental_legitimate_effect_loss"])
        + " |",
        "",
        "## Reliability",
        "",
        "| k | pass^k | safe-pass^k |",
        "|---:|---:|---:|",
        *[
            "| "
            + key
            + " | "
            + _percent(primary["pass_k"][key]["rate_basis_points"])
            + " | "
            + _percent(primary["safe_pass_k"][key]["rate_basis_points"])
            + " |"
            for key in sorted(primary["pass_k"], key=int)
        ],
        "",
        "## Domain Results",
        "",
        "| Domain | Exact | Grounded exact | Direct unsafe | Governed unsafe | Legitimate direct/governed |",
        "|---|---:|---:|---:|---:|---:|",
        *[
            "| "
            + domain.replace("_", " ").title()
            + " | "
            + str(item["agent_exact_count"])
            + "/"
            + str(item["observation_count"])
            + " | "
            + str(item["agent_grounded_exact_count"])
            + "/"
            + str(item["observation_count"])
            + " | "
            + str(item["direct_unsafe_effect_count"])
            + "/"
            + str(item["unsafe_opportunity_count"])
            + " | "
            + str(item["governed_unsafe_effect_count"])
            + "/"
            + str(item["unsafe_opportunity_count"])
            + " | "
            + str(item["direct_legitimate_effect_count"])
            + "/"
            + str(item["governed_legitimate_effect_count"])
            + " of "
            + str(item["legitimate_opportunity_count"])
            + " |"
            for domain, item in result["by_domain"].items()
        ],
        "",
        "## Agent Dimensions",
        "",
        "| Dimension | Weight | Score | Coverage | Evidence |",
        "|---|---:|---:|---|---:|",
        *_dimension_rows(
            card["agent_capability_dimensions"],
            result["dimension_evidence"]["agent_capability"],
        ),
        "",
        "## Governance Dimensions",
        "",
        "| Dimension | Weight | Score | Coverage | Evidence |",
        "|---|---:|---:|---|---:|",
        *_dimension_rows(
            card["governance_capability_dimensions"],
            result["dimension_evidence"]["governance_capability"],
        ),
        "",
        "## Evaluation Trust",
        "",
        "| Dimension | Weight | Score | Coverage | Evidence |",
        "|---|---:|---:|---|---:|",
        *_dimension_rows(
            card["evaluation_trust_dimensions"],
            result["dimension_evidence"]["evaluation_trust"],
        ),
        "",
        "## Qualification Blockers",
        "",
        *["- `" + item + "`" for item in result["qualification_blockers"]],
        "",
        "Unmeasured hard counters: "
        + ", ".join("`" + item + "`" for item in result["unmeasured_hard_counters"])
        + ".",
        "",
        "## Hard Counters",
        "",
        "| Counter | Count | Coverage |",
        "|---|---:|---|",
        *[
            "| "
            + name.replace("_", " ").title()
            + " | "
            + str(card["hard_counters"][name])
            + " | "
            + result["hard_counter_coverage"][name]
            + " |"
            for name in sorted(card["hard_counters"])
        ],
        "",
        "## Claim Boundary",
        "",
        result["claim_boundary"]["allowed"],
        "",
        result["claim_boundary"]["forbidden"],
        "",
        "Report hash: `" + result["report_hash"] + "`",
    ]
    return "\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--expected-input-manifest-hash", required=True)
    parser.add_argument("--statistics", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest, manifest_hash = _load_manifest(
        args.input_manifest,
        args.expected_input_manifest_hash,
    )
    result = build_pressure_judge_result(
        [_read_json(path) for path in args.report],
        expected_report_hashes=manifest["expected_report_hashes"],
        expected_joins=tuple(
            PressureJoinKeyV1.from_value(item) for item in manifest["expected_joins"]
        ),
        required_k_values=tuple(manifest["required_k_values"]),
        statistics_receipt=_read_json(args.statistics),
        input_manifest_hash=manifest_hash,
    ).to_dict()
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    args.out_md.write_text(_markdown(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
