from __future__ import annotations

from dataclasses import replace

import pytest

from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.contracts import (
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.paired import (
    ArmRole,
    ExecutionTier,
    LifecycleComparisonMetricsV1,
    PairedArmManifestV1,
    PairedArmResultV1,
    PairedComparisonReportV1,
    PairedLifecyclePairV1,
)


def _hash(label: str) -> str:
    return sha256_payload({"fixture": label})


def _metrics(
    *,
    hard: int = 0,
    semantic: int = 8_000,
    legitimate: int = 1,
    refusals: int = 0,
    recovery: int = 9_000,
    obligations: int = 8_500,
    compensation: int = 7_500,
    tools: int = 20,
) -> LifecycleComparisonMetricsV1:
    return LifecycleComparisonMetricsV1(
        hard_violation_count=hard,
        semantic_resolution_basis_points=semantic,
        legitimate_effect_count=legitimate,
        false_refusal_count=refusals,
        recovery_basis_points=recovery,
        obligations_basis_points=obligations,
        compensation_basis_points=compensation,
        tool_call_count=tools,
    )


def _manifest(
    role: ArmRole,
    *,
    pair_id: str = "pair-000",
    sequence: int = 0,
    scenario_id: str = "BANK-A1",
    variant_id: str = "base",
    seed: int = 17,
    repetition: int = 0,
    governance_digest: str | None = None,
    governance_mode: str | None = None,
    tier: ExecutionTier = ExecutionTier.CONTAINMENT_ONLY,
    process_root: str | None = None,
    state_root: str | None = None,
) -> PairedArmManifestV1:
    suffix = role.value
    return PairedArmManifestV1(
        pair_id=pair_id,
        pair_sequence=sequence,
        arm_role=role,
        arm_ordinal=0 if role is ArmRole.DIRECT else 1,
        frozen_public_world_hash=_hash("public-world"),
        frozen_evaluator_world_hash=_hash("evaluator-world"),
        scenario_id=scenario_id,
        variant_id=variant_id,
        seed=seed,
        candidate_implementation_digest=_hash("candidate"),
        model_digest=_hash("model"),
        provider_digest=_hash("provider"),
        model_config_digest=_hash("model-config"),
        tool_schema_digest=_hash("tools"),
        time_budget_ms=120_000,
        token_budget=32_000,
        tool_call_budget=120,
        restart_budget=3,
        event_schedule_hash=_hash("events"),
        fault_schedule_hash=_hash("faults"),
        initial_source_hash=_hash("source"),
        repetition_index=repetition,
        governance_layer_digest=governance_digest or _hash("governance-" + suffix),
        governance_mode=governance_mode or suffix,
        process_root_digest=process_root or _hash("process-" + suffix + pair_id),
        state_root_digest=state_root or _hash("state-" + suffix + pair_id),
        sibling_state_present=False,
        execution_tier=tier,
    )


def _result(
    manifest: PairedArmManifestV1,
    *,
    metrics: LifecycleComparisonMetricsV1 | None = None,
    common_artifacts: bool = False,
) -> PairedArmResultV1:
    suffix = "aa" if common_artifacts else manifest.arm_role.value
    artifact_suffix = suffix + "-" + manifest.pair_id
    return PairedArmResultV1(
        pair_id=manifest.pair_id,
        pair_sequence=manifest.pair_sequence,
        arm_role=manifest.arm_role,
        arm_ordinal=manifest.arm_ordinal,
        manifest_hash=manifest.manifest_hash,
        lifecycle_run_result_hash=_hash("run-" + artifact_suffix),
        trace_hash=_hash("trace-" + artifact_suffix),
        source_receipts_hash=_hash("source-receipts-" + artifact_suffix),
        effect_receipts_hash=_hash("effect-receipts-" + artifact_suffix),
        oracle_hash=_hash("oracle-" + artifact_suffix),
        score_hash=_hash("score-" + artifact_suffix),
        metrics=metrics or _metrics(),
    )


def _pair(
    *,
    sequence: int = 0,
    pair_id: str = "pair-000",
    tier: ExecutionTier = ExecutionTier.CONTAINMENT_ONLY,
    direct_metrics: LifecycleComparisonMetricsV1 | None = None,
    governed_metrics: LifecycleComparisonMetricsV1 | None = None,
    aa: bool = False,
    common_artifacts: bool = False,
    scenario_id: str = "BANK-A1",
    repetition: int = 0,
) -> PairedLifecyclePairV1:
    common_governance = _hash("aa-governance") if aa else None
    common_mode = "disabled" if aa else None
    direct = _manifest(
        ArmRole.DIRECT,
        pair_id=pair_id,
        sequence=sequence,
        tier=tier,
        governance_digest=common_governance,
        governance_mode=common_mode,
        scenario_id=scenario_id,
        repetition=repetition,
    )
    governed = _manifest(
        ArmRole.GOVERNED,
        pair_id=pair_id,
        sequence=sequence,
        tier=tier,
        governance_digest=common_governance,
        governance_mode=common_mode,
        scenario_id=scenario_id,
        repetition=repetition,
    )
    return PairedLifecyclePairV1(
        direct_manifest=direct,
        governed_manifest=governed,
        direct_result=_result(
            direct, metrics=direct_metrics, common_artifacts=common_artifacts
        ),
        governed_result=_result(
            governed, metrics=governed_metrics, common_artifacts=common_artifacts
        ),
    )


def test_valid_pair_binds_equal_inputs_and_separate_deltas() -> None:
    pair = _pair(
        direct_metrics=_metrics(
            hard=3,
            semantic=4_000,
            legitimate=0,
            refusals=2,
            recovery=2_000,
            obligations=3_000,
            compensation=1_000,
            tools=15,
        ),
        governed_metrics=_metrics(
            hard=0,
            semantic=9_000,
            legitimate=1,
            refusals=0,
            recovery=10_000,
            obligations=9_500,
            compensation=9_000,
            tools=24,
        ),
    )

    assert pair.direct_manifest.shared_input_hash == pair.governed_manifest.shared_input_hash
    assert pair.delta.to_dict() == {
        "hard_violation_reduction": 3,
        "semantic_resolution_delta_basis_points": 5_000,
        "legitimate_effect_delta": 1,
        "false_refusal_reduction": 2,
        "recovery_delta_basis_points": 8_000,
        "obligations_delta_basis_points": 6_500,
        "compensation_delta_basis_points": 8_000,
        "tool_cost_delta": 9,
    }
    assert "aggregate_reward" not in pair.to_dict()


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("frozen_public_world_hash", _hash("other-public")),
        ("frozen_evaluator_world_hash", _hash("other-evaluator")),
        ("scenario_id", "BANK-A2"),
        ("variant_id", "causal-sister"),
        ("seed", 18),
        ("candidate_implementation_digest", _hash("other-candidate")),
        ("model_digest", _hash("other-model")),
        ("provider_digest", _hash("other-provider")),
        ("model_config_digest", _hash("other-config")),
        ("tool_schema_digest", _hash("other-tools")),
        ("time_budget_ms", 119_999),
        ("token_budget", 31_999),
        ("tool_call_budget", 119),
        ("restart_budget", 2),
        ("event_schedule_hash", _hash("other-events")),
        ("fault_schedule_hash", _hash("other-faults")),
        ("initial_source_hash", _hash("other-source")),
        ("repetition_index", 1),
        ("execution_tier", ExecutionTier.EVALUATOR_OPERATED_PROCESS),
    ],
)
def test_every_shared_input_mismatch_fails_closed(
    field_name: str, replacement: object
) -> None:
    direct = _manifest(ArmRole.DIRECT)
    governed = replace(
        _manifest(ArmRole.GOVERNED),
        **{field_name: replacement, "manifest_hash": ""},
    )
    with pytest.raises(ValueError, match="identical experimental inputs"):
        PairedLifecyclePairV1(
            direct,
            governed,
            _result(direct),
            _result(governed),
        )


def test_only_governance_layer_and_mode_may_differ() -> None:
    pair = _pair()
    assert (
        pair.direct_manifest.governance_layer_digest
        != pair.governed_manifest.governance_layer_digest
    )
    assert pair.direct_manifest.governance_mode != pair.governed_manifest.governance_mode


@pytest.mark.parametrize("root_kind", ["process", "state"])
def test_arm_roots_must_be_independent(root_kind: str) -> None:
    shared = _hash("reused-root")
    direct = _manifest(
        ArmRole.DIRECT,
        process_root=shared if root_kind == "process" else None,
        state_root=shared if root_kind == "state" else None,
    )
    governed = _manifest(
        ArmRole.GOVERNED,
        process_root=shared if root_kind == "process" else None,
        state_root=shared if root_kind == "state" else None,
    )
    with pytest.raises(ValueError, match="reused a " + root_kind + " root"):
        PairedLifecyclePairV1(
            direct,
            governed,
            _result(direct),
            _result(governed),
        )


def test_sibling_state_is_rejected_at_manifest_boundary() -> None:
    with pytest.raises(ValueError, match="must not have sibling-arm state"):
        replace(
            _manifest(ArmRole.DIRECT),
            sibling_state_present=True,
            manifest_hash="",
        )


def test_swapped_arms_and_results_are_rejected() -> None:
    direct = _manifest(ArmRole.DIRECT)
    governed = _manifest(ArmRole.GOVERNED)
    with pytest.raises(ValueError, match="direct manifest is swapped"):
        PairedLifecyclePairV1(
            governed,
            direct,
            _result(governed),
            _result(direct),
        )
    with pytest.raises(ValueError, match="direct result is swapped"):
        PairedLifecyclePairV1(
            direct,
            governed,
            _result(governed),
            _result(direct),
        )


def test_missing_or_stale_results_are_rejected() -> None:
    direct = _manifest(ArmRole.DIRECT)
    governed = _manifest(ArmRole.GOVERNED)
    with pytest.raises(ValueError, match="missing or invalid"):
        PairedLifecyclePairV1(  # type: ignore[arg-type]
            direct, governed, None, _result(governed)
        )
    stale = replace(
        _result(direct),
        manifest_hash=_hash("stale-manifest"),
        result_hash="",
    )
    with pytest.raises(ValueError, match="stale for its manifest"):
        PairedLifecyclePairV1(direct, governed, stale, _result(governed))


def test_pair_identifier_and_sequence_mismatches_are_rejected() -> None:
    direct = _manifest(ArmRole.DIRECT)
    governed_id = _manifest(ArmRole.GOVERNED, pair_id="pair-other")
    with pytest.raises(ValueError, match="mismatched pair identifiers"):
        PairedLifecyclePairV1(
            direct,
            governed_id,
            _result(direct),
            _result(governed_id),
        )

    governed_sequence = _manifest(ArmRole.GOVERNED, sequence=1)
    with pytest.raises(ValueError, match="stale or out of order"):
        PairedLifecyclePairV1(
            direct,
            governed_sequence,
            _result(direct),
            _result(governed_sequence),
        )


def test_duplicate_missing_and_out_of_order_pairs_fail_closed() -> None:
    first = _pair()
    second_same_id = _pair(
        sequence=1,
        pair_id="pair-000",
        scenario_id="BANK-A2",
    )
    with pytest.raises(ValueError, match="duplicate pair identifier"):
        PairedComparisonReportV1((first, second_same_id))
    with pytest.raises(ValueError, match="non-empty tuple"):
        PairedComparisonReportV1(())

    second = _pair(sequence=1, pair_id="pair-001", scenario_id="BANK-A2")
    with pytest.raises(ValueError, match="out of order"):
        PairedComparisonReportV1((second, first))


def test_duplicate_logical_run_is_rejected_even_with_distinct_pair_ids() -> None:
    first = _pair()
    duplicate = _pair(sequence=1, pair_id="pair-001")
    with pytest.raises(ValueError, match="duplicate logical lifecycle run"):
        PairedComparisonReportV1((first, duplicate))


def test_process_and_state_roots_cannot_be_reused_across_pairs() -> None:
    first = _pair()
    for root_kind in ("process", "state"):
        direct = _manifest(
            ArmRole.DIRECT,
            pair_id="pair-001",
            sequence=1,
            scenario_id="BANK-A2",
            process_root=(
                first.direct_manifest.process_root_digest
                if root_kind == "process"
                else None
            ),
            state_root=(
                first.direct_manifest.state_root_digest
                if root_kind == "state"
                else None
            ),
        )
        governed = _manifest(
            ArmRole.GOVERNED,
            pair_id="pair-001",
            sequence=1,
            scenario_id="BANK-A2",
        )
        second = PairedLifecyclePairV1(
            direct,
            governed,
            _result(direct),
            _result(governed),
        )
        with pytest.raises(ValueError, match=root_kind + " root across runs"):
            PairedComparisonReportV1((first, second))


def test_bound_artifacts_cannot_be_reused_across_logical_runs() -> None:
    first = _pair()
    second = _pair(sequence=1, pair_id="pair-001", scenario_id="BANK-A2")
    reused = replace(
        second.direct_result,
        lifecycle_run_result_hash=first.direct_result.lifecycle_run_result_hash,
        result_hash="",
    )
    second = replace(second, direct_result=reused, pair_hash="")

    with pytest.raises(ValueError, match="reused an artifact"):
        PairedComparisonReportV1((first, second))


@pytest.mark.parametrize(
    "value",
    ["", "sha256:abc", "sha256:" + ("G" * 64), "not-a-hash", None],
)
def test_forged_or_missing_artifact_hashes_are_rejected(value: object) -> None:
    manifest = _manifest(ArmRole.DIRECT)
    with pytest.raises(ValueError, match="lowercase sha256"):
        replace(
            _result(manifest),
            trace_hash=value,  # type: ignore[arg-type]
            result_hash="",
        )


def test_stale_manifest_result_pair_report_and_receipt_hashes_are_rejected() -> None:
    manifest = _manifest(ArmRole.DIRECT)
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        replace(manifest, manifest_hash=_hash("forged"))
    result = _result(manifest)
    with pytest.raises(ValueError, match="result hash mismatch"):
        replace(result, result_hash=_hash("forged"))
    pair = _pair()
    with pytest.raises(ValueError, match="pair hash mismatch"):
        replace(pair, pair_hash=_hash("forged"))
    report = PairedComparisonReportV1((pair,))
    with pytest.raises(ValueError, match="report hash mismatch"):
        replace(report, report_hash=_hash("forged"))
    with pytest.raises(ValueError, match="receipt hash mismatch"):
        replace(report, receipt_hash=_hash("forged"))


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("hard_violation_count", -1),
        ("hard_violation_count", 1.5),
        ("hard_violation_count", True),
        ("legitimate_effect_count", -1),
        ("false_refusal_count", -1),
        ("tool_call_count", -1),
        ("semantic_resolution_basis_points", -1),
        ("semantic_resolution_basis_points", 10_001),
        ("recovery_basis_points", "9000"),
        ("obligations_basis_points", False),
        ("compensation_basis_points", 10_001),
    ],
)
def test_negative_noninteger_and_out_of_range_counters_are_rejected(
    field_name: str, value: object
) -> None:
    values: dict[str, object] = _metrics().to_dict()
    values[field_name] = value
    with pytest.raises(ValueError):
        LifecycleComparisonMetricsV1(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("tier", tuple(ExecutionTier))
def test_in_memory_report_cannot_claim_external_qualification(
    tier: ExecutionTier,
) -> None:
    with pytest.raises(ValueError, match="artifact-custody verifier"):
        PairedComparisonReportV1((_pair(tier=tier),), qualification_claimed=True)


def test_qualification_cannot_hide_governed_hard_violations() -> None:
    pair = _pair(
        tier=ExecutionTier.EVALUATOR_OPERATED_MICROVM,
        direct_metrics=_metrics(hard=0, semantic=1_000),
        governed_metrics=_metrics(hard=1, semantic=10_000),
    )
    report = PairedComparisonReportV1((pair,))
    assert report.aggregate_delta.semantic_resolution_delta_basis_points == 9_000
    assert report.hard_safety_regressed is True
    assert report.qualification_eligible is False
    assert report.qualification_status == "DEVELOPMENT_PREVIEW_NOT_QUALIFIED"
    with pytest.raises(ValueError, match="qualification claim"):
        PairedComparisonReportV1((pair,), qualification_claimed=True)


def test_microvm_enum_is_not_an_authenticated_custody_attestation() -> None:
    report = PairedComparisonReportV1(
        (_pair(tier=ExecutionTier.EVALUATOR_OPERATED_MICROVM),)
    )
    assert report.qualification_eligible is False
    assert report.qualification_status == "DEVELOPMENT_PREVIEW_NOT_QUALIFIED"
    assert report.to_dict()["summary"]["evidence_tier"] == (
        "SELF_REPORTED_DEVELOPMENT_EVIDENCE"
    )


def test_report_and_receipt_hashes_are_deterministic() -> None:
    first = PairedComparisonReportV1((_pair(),))
    second = PairedComparisonReportV1((_pair(),))
    assert first.to_dict() == second.to_dict()
    assert first.report_hash == second.report_hash
    assert first.receipt_hash == second.receipt_hash


def test_aa_calibration_detects_exact_equality() -> None:
    pair = _pair(
        aa=True,
        common_artifacts=True,
        direct_metrics=_metrics(),
        governed_metrics=_metrics(),
    )
    report = PairedComparisonReportV1((pair,))
    assert pair.is_aa_calibration is True
    assert pair.aa_equal is True
    assert pair.aa_calibration_status == "PASS"
    assert report.aa_pair_count == 1
    assert report.aa_unequal_count == 0
    assert all(value == 0 for value in report.aggregate_delta.to_dict().values())


def test_aa_calibration_detects_drift_and_blocks_qualification() -> None:
    pair = _pair(
        aa=True,
        common_artifacts=True,
        tier=ExecutionTier.EVALUATOR_OPERATED_MICROVM,
        direct_metrics=_metrics(tools=20),
        governed_metrics=_metrics(tools=21),
    )
    report = PairedComparisonReportV1((pair,))
    assert pair.aa_calibration_status == "FAIL"
    assert report.aa_unequal_count == 1
    assert report.qualification_eligible is False
    with pytest.raises(ValueError, match="qualification claim"):
        PairedComparisonReportV1((pair,), qualification_claimed=True)
