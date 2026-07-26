from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from benchmarks.yuvin_consequencebench_100.adaptive_causal import cli
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle import source
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.oracle import (
    oracle_contamination_paths,
)


def _reference_command() -> list[str]:
    return [sys.executable, "-u", str(Path(source.__file__).resolve())]


def test_lifecycle_commands_are_advertised_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--help"])

    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "lifecycle-controls" in output
    assert "lifecycle-agent" in output


def test_lifecycle_controls_are_deterministic_and_non_qualifying() -> None:
    first = cli.run_lifecycle_controls(seed=17)
    second = cli.run_lifecycle_controls(seed=17)

    assert first == second
    assert first["failure_count"] == 0
    assert first["status"] == "CONTROL_ONLY"
    assert first["release_status"] == "DEVELOPMENT_PREVIEW_NOT_QUALIFIED"
    assert first["qualification_eligible"] is False
    assert first["independent_admission"]["evaluated_world_count"] == 300
    assert first["report_hash"].startswith("sha256:")


def test_lifecycle_agent_rejects_unknown_scenario(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown canonical scenario_id"):
        cli.main(
            [
                "lifecycle-agent",
                "--agent-command-json",
                json.dumps(_reference_command()),
                "--campaign-id",
                "unknown-scenario-test",
                "--scenario-id",
                "NOT-A-CANONICAL-SCENARIO",
                "--state-root",
                str(tmp_path / "state"),
            ]
        )


def test_lifecycle_agent_runs_reference_subprocess_without_oracle_leakage(
    tmp_path: Path,
) -> None:
    output = tmp_path / "report.json"
    exit_code = cli.main(
        [
            "lifecycle-agent",
            "--agent-command-json",
            json.dumps(_reference_command()),
            "--campaign-id",
            "reference-candidate-test",
            "--seed",
            "53",
            "--scenario-id",
            "COD-C02",
            "--state-root",
            str(tmp_path / "state"),
            "--timeout-seconds",
            "30",
            "--max-messages",
            "64",
            "--max-restarts",
            "2",
            "--out",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["status"] == "DEVELOPMENT_PREVIEW_NOT_QUALIFIED"
    assert report["qualification_eligible"] is False
    assert report["execution_tier"] == "CONTAINMENT_ONLY"
    assert report["isolation_claim"] == "NOT_OS_SANDBOXED"
    assert report["summary"]["attempt_count"] == 1
    assert report["summary"]["agent_failure_count"] == 0
    assert report["rows"][0]["trace_result"]["status"] == "COMPLETED"
    assert report["rows"][0]["effect_result"]["available"] is True
    assert report["rows"][0]["exact_source_hashes"]["world_hash"].startswith("sha256:")
    assert report["rows"][0]["exact_source_hashes"][
        "initial_external_source_state_hash"
    ].startswith("sha256:")
    assert report["rows"][0]["exact_source_hashes"][
        "final_external_source_state_hash"
    ].startswith("sha256:")

    candidate_view = report["rows"][0]["candidate_start_view"]
    assert oracle_contamination_paths(candidate_view) == ()
    assert "oracle" not in json.dumps(candidate_view, sort_keys=True).casefold()
    assert "expected_state_diff" not in candidate_view
    assert "catalog_baseline_outcome" not in candidate_view
    assert report["rows"][0]["trace_result"]["execution_tier"] == "CONTAINMENT_ONLY"
    assert report["rows"][0]["trace_result"]["isolation_claim"] == "NOT_OS_SANDBOXED"


def test_lifecycle_agent_report_hash_is_deterministic_for_deterministic_candidate(
    tmp_path: Path,
) -> None:
    common = {
        "command": tuple(_reference_command()),
        "campaign_id": "deterministic-reference-test",
        "seed": 0,
        "scenario_ids": ("FIN-B01",),
        "timeout_seconds": 30,
        "max_messages": 64,
        "max_restarts": 2,
    }

    first = cli.run_lifecycle_agent(
        **common,
        state_root=tmp_path / "first",
    )
    second = cli.run_lifecycle_agent(
        **common,
        state_root=tmp_path / "second",
    )

    assert first["report_hash"] == second["report_hash"]
    assert first == second
