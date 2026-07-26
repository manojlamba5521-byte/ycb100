from __future__ import annotations

from copy import deepcopy

from benchmarks.yuvin_consequencebench_100.adaptive_causal.scenario_manifest import (
    load_scenario_manifest,
    validate_scenario_manifest,
)


def test_scenario_manifest_binds_exactly_100_executable_worlds() -> None:
    report = validate_scenario_manifest()

    assert report["status"] == "PASS"
    assert report["scenario_count"] == 100
    assert report["executable_binding_count"] == 100
    assert report["failure_count"] == 0
    assert report["qualification_eligible"] is False


def test_scenario_manifest_rejects_hash_and_binding_forgery() -> None:
    forged = deepcopy(load_scenario_manifest())
    forged["entries"][0]["executable_binding"]["family_index"] = 19

    report = validate_scenario_manifest(forged)

    assert report["status"] == "FAIL"
    assert "manifest_hash_mismatch" in report["validation_failures"]
    assert any(
        "duplicate_executable_binding" in failure
        for failure in report["validation_failures"]
    )
