"""Build fail-closed repeated-trial statistics from evaluator-declared inputs."""
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
from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_statistics import (
    PressureJoinKeyV1,
    build_pressure_qualification_statistics,
)


INPUT_MANIFEST_SCHEMA_VERSION = "ycb100.acc.pressure_statistics_input_manifest.v1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(str(path) + " must contain a JSON object")
    return value


def _load_input_manifest(
    path: Path,
    *,
    expected_manifest_hash: str,
) -> dict[str, Any]:
    manifest = _read_json(path)
    body = dict(manifest)
    declared_hash = str(body.pop("manifest_hash", ""))
    if declared_hash != sha256_payload(body):
        raise ValueError("pressure statistics input manifest hash mismatch")
    if declared_hash != expected_manifest_hash:
        raise ValueError("evaluator-held pressure input manifest hash mismatch")
    if set(body) != {
        "schema_version",
        "status",
        "expected_report_hashes",
        "expected_joins",
        "required_k_values",
    }:
        raise ValueError("pressure statistics input manifest fields are invalid")
    if body["schema_version"] != INPUT_MANIFEST_SCHEMA_VERSION:
        raise ValueError("pressure statistics input manifest schema mismatch")
    if body["status"] != "EVALUATOR_DECLARED":
        raise ValueError("pressure statistics input manifest status is invalid")
    if not isinstance(body["expected_report_hashes"], dict):
        raise ValueError("expected_report_hashes must be an object")
    if not isinstance(body["expected_joins"], list):
        raise ValueError("expected_joins must be a list")
    if not isinstance(body["required_k_values"], list):
        raise ValueError("required_k_values must be a list")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--expected-input-manifest-hash", required=True)
    parser.add_argument("--aa-report", type=Path, action="append")
    parser.add_argument("--aa-input-manifest", type=Path)
    parser.add_argument("--expected-aa-input-manifest-hash")
    parser.add_argument("--gate-evidence", type=Path)
    parser.add_argument("--expected-gate-evidence-hash")
    parser.add_argument("--require-qualified", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = _load_input_manifest(
        args.input_manifest,
        expected_manifest_hash=args.expected_input_manifest_hash,
    )
    reports = [_read_json(path) for path in args.report]

    aa_reports = None
    aa_hashes = None
    if any(
        value is not None
        for value in (
            args.aa_report,
            args.aa_input_manifest,
            args.expected_aa_input_manifest_hash,
        )
    ):
        if (
            not args.aa_report
            or args.aa_input_manifest is None
            or args.expected_aa_input_manifest_hash is None
        ):
            raise ValueError("complete A/A reports and manifest arguments are required")
        aa_manifest = _load_input_manifest(
            args.aa_input_manifest,
            expected_manifest_hash=args.expected_aa_input_manifest_hash,
        )
        if (
            aa_manifest["expected_joins"] != manifest["expected_joins"]
            or aa_manifest["required_k_values"] != manifest["required_k_values"]
        ):
            raise ValueError("A/A input manifest does not match primary joins and k values")
        aa_reports = [_read_json(path) for path in args.aa_report]
        aa_hashes = aa_manifest["expected_report_hashes"]

    gate_evidence = (
        _read_json(args.gate_evidence)
        if args.gate_evidence is not None
        else None
    )
    result = build_pressure_qualification_statistics(
        reports,
        expected_report_hashes=manifest["expected_report_hashes"],
        expected_joins=tuple(
            PressureJoinKeyV1.from_value(item)
            for item in manifest["expected_joins"]
        ),
        required_k_values=tuple(manifest["required_k_values"]),
        aa_reports=aa_reports,
        expected_aa_report_hashes=aa_hashes,
        independently_verified_gate_evidence=gate_evidence,
        expected_gate_evidence_hash=args.expected_gate_evidence_hash,
    ).to_dict()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 3 if args.require_qualified and not result["qualification_eligible"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
