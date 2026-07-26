"""Universal, fail-closed paired comparison contracts for lifecycle runs.

The contracts in this module bind experiment identity and measured consequences.
They deliberately do not know about, import, or privilege any governance product.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.contracts import (
    bounded_identifier,
    sha256_payload,
)


PAIRED_MANIFEST_SCHEMA_VERSION = "ycb100.consequence_lifecycle.paired_manifest.v1"
PAIRED_RESULT_SCHEMA_VERSION = "ycb100.consequence_lifecycle.paired_result.v1"
PAIRED_REPORT_SCHEMA_VERSION = "ycb100.consequence_lifecycle.paired_report.v1"
PAIRED_RECEIPT_SCHEMA_VERSION = "ycb100.consequence_lifecycle.paired_receipt.v1"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArmRole(StrEnum):
    DIRECT = "direct"
    GOVERNED = "governed"


class ExecutionTier(StrEnum):
    CONTAINMENT_ONLY = "CONTAINMENT_ONLY"
    EVALUATOR_OPERATED_PROCESS = "EVALUATOR_OPERATED_PROCESS"
    EVALUATOR_OPERATED_MICROVM = "EVALUATOR_OPERATED_MICROVM"


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(field_name + " must be a lowercase sha256 digest")
    return value


def _integer(
    value: object,
    field_name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(field_name + " must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(field_name + " is outside the valid range")
    return value


def _role_ordinal(role: ArmRole) -> int:
    return 0 if role is ArmRole.DIRECT else 1


@dataclass(frozen=True)
class PairedArmManifestV1:
    """Immutable identity and fairness boundary for one experimental arm."""

    pair_id: str
    pair_sequence: int
    arm_role: ArmRole
    arm_ordinal: int
    frozen_public_world_hash: str
    frozen_evaluator_world_hash: str
    scenario_id: str
    variant_id: str
    seed: int
    candidate_implementation_digest: str
    model_digest: str
    provider_digest: str
    model_config_digest: str
    tool_schema_digest: str
    time_budget_ms: int
    token_budget: int
    tool_call_budget: int
    restart_budget: int
    event_schedule_hash: str
    fault_schedule_hash: str
    initial_source_hash: str
    repetition_index: int
    governance_layer_digest: str
    governance_mode: str
    process_root_digest: str
    state_root_digest: str
    sibling_state_present: bool
    execution_tier: ExecutionTier
    manifest_hash: str = ""
    schema_version: str = PAIRED_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PAIRED_MANIFEST_SCHEMA_VERSION:
            raise ValueError("paired manifest schema version mismatch")
        if not isinstance(self.arm_role, ArmRole):
            raise ValueError("arm_role must be ArmRole")
        if not isinstance(self.execution_tier, ExecutionTier):
            raise ValueError("execution_tier must be ExecutionTier")
        object.__setattr__(self, "pair_id", bounded_identifier(self.pair_id, "pair_id"))
        object.__setattr__(
            self, "scenario_id", bounded_identifier(self.scenario_id, "scenario_id")
        )
        object.__setattr__(
            self, "variant_id", bounded_identifier(self.variant_id, "variant_id")
        )
        object.__setattr__(
            self,
            "governance_mode",
            bounded_identifier(self.governance_mode, "governance_mode"),
        )
        _integer(self.pair_sequence, "pair_sequence")
        _integer(self.arm_ordinal, "arm_ordinal")
        if self.arm_ordinal != _role_ordinal(self.arm_role):
            raise ValueError("arm_ordinal contradicts arm_role")
        _integer(self.seed, "seed")
        _integer(self.time_budget_ms, "time_budget_ms", minimum=1)
        _integer(self.token_budget, "token_budget", minimum=1)
        _integer(self.tool_call_budget, "tool_call_budget", minimum=1)
        _integer(self.restart_budget, "restart_budget")
        _integer(self.repetition_index, "repetition_index")
        for field_name in (
            "frozen_public_world_hash",
            "frozen_evaluator_world_hash",
            "candidate_implementation_digest",
            "model_digest",
            "provider_digest",
            "model_config_digest",
            "tool_schema_digest",
            "event_schedule_hash",
            "fault_schedule_hash",
            "initial_source_hash",
            "governance_layer_digest",
            "process_root_digest",
            "state_root_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        if not isinstance(self.sibling_state_present, bool):
            raise ValueError("sibling_state_present must be a boolean")
        if self.sibling_state_present:
            raise ValueError("an arm must not have sibling-arm state")
        expected = sha256_payload(self._payload())
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("paired manifest hash mismatch")
        object.__setattr__(self, "manifest_hash", expected)

    def shared_input_payload(self) -> dict[str, Any]:
        """Fields that must be byte-for-byte equivalent between both arms."""
        return {
            "pair_id": self.pair_id,
            "pair_sequence": self.pair_sequence,
            "frozen_public_world_hash": self.frozen_public_world_hash,
            "frozen_evaluator_world_hash": self.frozen_evaluator_world_hash,
            "scenario_id": self.scenario_id,
            "variant_id": self.variant_id,
            "seed": self.seed,
            "candidate_implementation_digest": self.candidate_implementation_digest,
            "model_digest": self.model_digest,
            "provider_digest": self.provider_digest,
            "model_config_digest": self.model_config_digest,
            "tool_schema_digest": self.tool_schema_digest,
            "time_budget_ms": self.time_budget_ms,
            "token_budget": self.token_budget,
            "tool_call_budget": self.tool_call_budget,
            "restart_budget": self.restart_budget,
            "event_schedule_hash": self.event_schedule_hash,
            "fault_schedule_hash": self.fault_schedule_hash,
            "initial_source_hash": self.initial_source_hash,
            "repetition_index": self.repetition_index,
            "execution_tier": self.execution_tier.value,
        }

    @property
    def shared_input_hash(self) -> str:
        return sha256_payload(self.shared_input_payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self.shared_input_payload(),
            "arm_role": self.arm_role.value,
            "arm_ordinal": self.arm_ordinal,
            "governance_layer_digest": self.governance_layer_digest,
            "governance_mode": self.governance_mode,
            "process_root_digest": self.process_root_digest,
            "state_root_digest": self.state_root_digest,
            "sibling_state_present": self.sibling_state_present,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "shared_input_hash": self.shared_input_hash,
            "manifest_hash": self.manifest_hash,
        }


@dataclass(frozen=True)
class LifecycleComparisonMetricsV1:
    """Non-substitutable measurements used by a paired comparison."""

    hard_violation_count: int
    semantic_resolution_basis_points: int
    legitimate_effect_count: int
    false_refusal_count: int
    recovery_basis_points: int
    obligations_basis_points: int
    compensation_basis_points: int
    tool_call_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "hard_violation_count",
            "legitimate_effect_count",
            "false_refusal_count",
            "tool_call_count",
        ):
            _integer(getattr(self, field_name), field_name)
        for field_name in (
            "semantic_resolution_basis_points",
            "recovery_basis_points",
            "obligations_basis_points",
            "compensation_basis_points",
        ):
            _integer(getattr(self, field_name), field_name, maximum=10_000)

    def to_dict(self) -> dict[str, int]:
        return {
            "hard_violation_count": self.hard_violation_count,
            "semantic_resolution_basis_points": self.semantic_resolution_basis_points,
            "legitimate_effect_count": self.legitimate_effect_count,
            "false_refusal_count": self.false_refusal_count,
            "recovery_basis_points": self.recovery_basis_points,
            "obligations_basis_points": self.obligations_basis_points,
            "compensation_basis_points": self.compensation_basis_points,
            "tool_call_count": self.tool_call_count,
        }


@dataclass(frozen=True)
class PairedArmResultV1:
    """Artifact-bound result for one arm's actual lifecycle execution."""

    pair_id: str
    pair_sequence: int
    arm_role: ArmRole
    arm_ordinal: int
    manifest_hash: str
    lifecycle_run_result_hash: str
    trace_hash: str
    source_receipts_hash: str
    effect_receipts_hash: str
    oracle_hash: str
    score_hash: str
    metrics: LifecycleComparisonMetricsV1
    result_hash: str = ""
    schema_version: str = PAIRED_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PAIRED_RESULT_SCHEMA_VERSION:
            raise ValueError("paired result schema version mismatch")
        if not isinstance(self.arm_role, ArmRole):
            raise ValueError("arm_role must be ArmRole")
        if not isinstance(self.metrics, LifecycleComparisonMetricsV1):
            raise ValueError("metrics must be LifecycleComparisonMetricsV1")
        object.__setattr__(self, "pair_id", bounded_identifier(self.pair_id, "pair_id"))
        _integer(self.pair_sequence, "pair_sequence")
        _integer(self.arm_ordinal, "arm_ordinal")
        if self.arm_ordinal != _role_ordinal(self.arm_role):
            raise ValueError("arm_ordinal contradicts arm_role")
        for field_name in (
            "manifest_hash",
            "lifecycle_run_result_hash",
            "trace_hash",
            "source_receipts_hash",
            "effect_receipts_hash",
            "oracle_hash",
            "score_hash",
        ):
            _digest(getattr(self, field_name), field_name)
        expected = sha256_payload(self._payload())
        if self.result_hash and self.result_hash != expected:
            raise ValueError("paired result hash mismatch")
        object.__setattr__(self, "result_hash", expected)

    def semantic_result_payload(self) -> dict[str, Any]:
        """Root-independent outputs used for deterministic A/A calibration."""
        return {
            "lifecycle_run_result_hash": self.lifecycle_run_result_hash,
            "trace_hash": self.trace_hash,
            "source_receipts_hash": self.source_receipts_hash,
            "effect_receipts_hash": self.effect_receipts_hash,
            "oracle_hash": self.oracle_hash,
            "score_hash": self.score_hash,
            "metrics": self.metrics.to_dict(),
        }

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pair_id": self.pair_id,
            "pair_sequence": self.pair_sequence,
            "arm_role": self.arm_role.value,
            "arm_ordinal": self.arm_ordinal,
            "manifest_hash": self.manifest_hash,
            **self.semantic_result_payload(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "result_hash": self.result_hash}


@dataclass(frozen=True)
class PairedMetricDeltaV1:
    """Governed-minus-direct deltas, with reductions named explicitly."""

    hard_violation_reduction: int
    semantic_resolution_delta_basis_points: int
    legitimate_effect_delta: int
    false_refusal_reduction: int
    recovery_delta_basis_points: int
    obligations_delta_basis_points: int
    compensation_delta_basis_points: int
    tool_cost_delta: int

    @classmethod
    def from_metrics(
        cls,
        direct: LifecycleComparisonMetricsV1,
        governed: LifecycleComparisonMetricsV1,
    ) -> "PairedMetricDeltaV1":
        return cls(
            hard_violation_reduction=(
                direct.hard_violation_count - governed.hard_violation_count
            ),
            semantic_resolution_delta_basis_points=(
                governed.semantic_resolution_basis_points
                - direct.semantic_resolution_basis_points
            ),
            legitimate_effect_delta=(
                governed.legitimate_effect_count - direct.legitimate_effect_count
            ),
            false_refusal_reduction=(
                direct.false_refusal_count - governed.false_refusal_count
            ),
            recovery_delta_basis_points=(
                governed.recovery_basis_points - direct.recovery_basis_points
            ),
            obligations_delta_basis_points=(
                governed.obligations_basis_points - direct.obligations_basis_points
            ),
            compensation_delta_basis_points=(
                governed.compensation_basis_points
                - direct.compensation_basis_points
            ),
            tool_cost_delta=governed.tool_call_count - direct.tool_call_count,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "hard_violation_reduction": self.hard_violation_reduction,
            "semantic_resolution_delta_basis_points": (
                self.semantic_resolution_delta_basis_points
            ),
            "legitimate_effect_delta": self.legitimate_effect_delta,
            "false_refusal_reduction": self.false_refusal_reduction,
            "recovery_delta_basis_points": self.recovery_delta_basis_points,
            "obligations_delta_basis_points": self.obligations_delta_basis_points,
            "compensation_delta_basis_points": self.compensation_delta_basis_points,
            "tool_cost_delta": self.tool_cost_delta,
        }


@dataclass(frozen=True)
class PairedLifecyclePairV1:
    """Validated direct/governed pair over one immutable lifecycle world."""

    direct_manifest: PairedArmManifestV1
    governed_manifest: PairedArmManifestV1
    direct_result: PairedArmResultV1
    governed_result: PairedArmResultV1
    pair_hash: str = ""

    def __post_init__(self) -> None:
        for value, expected_type, field_name in (
            (self.direct_manifest, PairedArmManifestV1, "direct_manifest"),
            (self.governed_manifest, PairedArmManifestV1, "governed_manifest"),
            (self.direct_result, PairedArmResultV1, "direct_result"),
            (self.governed_result, PairedArmResultV1, "governed_result"),
        ):
            if not isinstance(value, expected_type):
                raise ValueError(field_name + " is missing or invalid")
        if self.direct_manifest.arm_role is not ArmRole.DIRECT:
            raise ValueError("direct manifest is swapped or mislabeled")
        if self.governed_manifest.arm_role is not ArmRole.GOVERNED:
            raise ValueError("governed manifest is swapped or mislabeled")
        pair_ids = {
            self.direct_manifest.pair_id,
            self.governed_manifest.pair_id,
            self.direct_result.pair_id,
            self.governed_result.pair_id,
        }
        if len(pair_ids) != 1:
            raise ValueError("paired artifacts have mismatched pair identifiers")
        sequences = {
            self.direct_manifest.pair_sequence,
            self.governed_manifest.pair_sequence,
            self.direct_result.pair_sequence,
            self.governed_result.pair_sequence,
        }
        if len(sequences) != 1:
            raise ValueError("paired artifacts are stale or out of order")
        if self.direct_manifest.shared_input_hash != self.governed_manifest.shared_input_hash:
            raise ValueError("paired arms do not bind identical experimental inputs")
        if self.direct_manifest.process_root_digest == self.governed_manifest.process_root_digest:
            raise ValueError("paired arms reused a process root")
        if self.direct_manifest.state_root_digest == self.governed_manifest.state_root_digest:
            raise ValueError("paired arms reused a state root")
        self._validate_result(self.direct_manifest, self.direct_result, ArmRole.DIRECT)
        self._validate_result(
            self.governed_manifest, self.governed_result, ArmRole.GOVERNED
        )
        expected = sha256_payload(self._payload())
        if self.pair_hash and self.pair_hash != expected:
            raise ValueError("paired lifecycle pair hash mismatch")
        object.__setattr__(self, "pair_hash", expected)

    @staticmethod
    def _validate_result(
        manifest: PairedArmManifestV1,
        result: PairedArmResultV1,
        role: ArmRole,
    ) -> None:
        if result.arm_role is not role or result.arm_ordinal != _role_ordinal(role):
            raise ValueError(role.value + " result is swapped or mislabeled")
        if result.manifest_hash != manifest.manifest_hash:
            raise ValueError(role.value + " result is stale for its manifest")

    @property
    def pair_id(self) -> str:
        return self.direct_manifest.pair_id

    @property
    def pair_sequence(self) -> int:
        return self.direct_manifest.pair_sequence

    @property
    def logical_run_key(self) -> tuple[str, str, int, int]:
        manifest = self.direct_manifest
        return (
            manifest.scenario_id,
            manifest.variant_id,
            manifest.seed,
            manifest.repetition_index,
        )

    @property
    def delta(self) -> PairedMetricDeltaV1:
        return PairedMetricDeltaV1.from_metrics(
            self.direct_result.metrics, self.governed_result.metrics
        )

    @property
    def is_aa_calibration(self) -> bool:
        return (
            self.direct_manifest.governance_layer_digest
            == self.governed_manifest.governance_layer_digest
            and self.direct_manifest.governance_mode
            == self.governed_manifest.governance_mode
        )

    @property
    def aa_equal(self) -> bool:
        return (
            self.is_aa_calibration
            and self.direct_result.semantic_result_payload()
            == self.governed_result.semantic_result_payload()
        )

    @property
    def aa_calibration_status(self) -> str:
        if not self.is_aa_calibration:
            return "NOT_AA"
        return "PASS" if self.aa_equal else "FAIL"

    def _payload(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "pair_sequence": self.pair_sequence,
            "shared_input_hash": self.direct_manifest.shared_input_hash,
            "direct_manifest_hash": self.direct_manifest.manifest_hash,
            "governed_manifest_hash": self.governed_manifest.manifest_hash,
            "direct_result_hash": self.direct_result.result_hash,
            "governed_result_hash": self.governed_result.result_hash,
            "delta": self.delta.to_dict(),
            "aa_calibration_status": self.aa_calibration_status,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "pair_hash": self.pair_hash}


@dataclass(frozen=True)
class PairedComparisonReportV1:
    """Deterministic multi-pair report with fail-closed qualification semantics."""

    pairs: tuple[PairedLifecyclePairV1, ...]
    qualification_claimed: bool = False
    report_hash: str = ""
    receipt_hash: str = ""
    schema_version: str = PAIRED_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PAIRED_REPORT_SCHEMA_VERSION:
            raise ValueError("paired report schema version mismatch")
        if not isinstance(self.pairs, tuple) or not self.pairs:
            raise ValueError("pairs must be a non-empty tuple")
        if not isinstance(self.qualification_claimed, bool):
            raise ValueError("qualification_claimed must be a boolean")
        if any(not isinstance(pair, PairedLifecyclePairV1) for pair in self.pairs):
            raise ValueError("pairs contains an invalid or missing pair")
        sequences = [pair.pair_sequence for pair in self.pairs]
        if sequences != list(range(len(self.pairs))):
            raise ValueError("pairs are missing, duplicated, or out of order")
        if len({pair.pair_id for pair in self.pairs}) != len(self.pairs):
            raise ValueError("duplicate pair identifier")
        if len({pair.logical_run_key for pair in self.pairs}) != len(self.pairs):
            raise ValueError("duplicate logical lifecycle run")
        if len({pair.pair_hash for pair in self.pairs}) != len(self.pairs):
            raise ValueError("duplicate paired result")
        process_roots = [
            manifest.process_root_digest
            for pair in self.pairs
            for manifest in (pair.direct_manifest, pair.governed_manifest)
        ]
        state_roots = [
            manifest.state_root_digest
            for pair in self.pairs
            for manifest in (pair.direct_manifest, pair.governed_manifest)
        ]
        if len(process_roots) != len(set(process_roots)):
            raise ValueError("paired report reused a process root across runs")
        if len(state_roots) != len(set(state_roots)):
            raise ValueError("paired report reused a state root across runs")
        artifact_owners: dict[str, str] = {}
        for pair in self.pairs:
            for result in (pair.direct_result, pair.governed_result):
                for field_name in (
                    "lifecycle_run_result_hash",
                    "trace_hash",
                    "source_receipts_hash",
                    "effect_receipts_hash",
                    "oracle_hash",
                    "score_hash",
                ):
                    digest = str(getattr(result, field_name))
                    owner = artifact_owners.setdefault(digest, pair.pair_id)
                    if owner != pair.pair_id:
                        raise ValueError(
                            "paired report reused an artifact across logical runs"
                        )
        if self.qualification_claimed and not self.qualification_eligible:
            raise ValueError(
                "qualification claim requires an external artifact-custody verifier"
            )
        expected_report = sha256_payload(self._report_payload())
        if self.report_hash and self.report_hash != expected_report:
            raise ValueError("paired comparison report hash mismatch")
        object.__setattr__(self, "report_hash", expected_report)
        expected_receipt = sha256_payload(self._receipt_payload(expected_report))
        if self.receipt_hash and self.receipt_hash != expected_receipt:
            raise ValueError("paired comparison receipt hash mismatch")
        object.__setattr__(self, "receipt_hash", expected_receipt)

    @property
    def aa_pair_count(self) -> int:
        return sum(pair.is_aa_calibration for pair in self.pairs)

    @property
    def aa_unequal_count(self) -> int:
        return sum(
            pair.is_aa_calibration and not pair.aa_equal for pair in self.pairs
        )

    @property
    def governed_hard_violation_count(self) -> int:
        return sum(pair.governed_result.metrics.hard_violation_count for pair in self.pairs)

    @property
    def qualification_eligible(self) -> bool:
        # This in-memory contract cannot reopen run artifacts or authenticate
        # evaluator custody. Qualification is issued only by an external
        # verifier, never from declared execution-tier and metric fields.
        return False

    @property
    def qualification_status(self) -> str:
        return "DEVELOPMENT_PREVIEW_NOT_QUALIFIED"

    @property
    def aggregate_delta(self) -> PairedMetricDeltaV1:
        names = tuple(PairedMetricDeltaV1.__dataclass_fields__)
        totals = {
            name: sum(getattr(pair.delta, name) for pair in self.pairs)
            for name in names
        }
        return PairedMetricDeltaV1(**totals)

    @property
    def hard_safety_regressed(self) -> bool:
        return self.aggregate_delta.hard_violation_reduction < 0

    def _summary(self) -> dict[str, Any]:
        return {
            "pair_count": len(self.pairs),
            "aa_pair_count": self.aa_pair_count,
            "aa_unequal_count": self.aa_unequal_count,
            "governed_hard_violation_count": self.governed_hard_violation_count,
            "hard_safety_regressed": self.hard_safety_regressed,
            "aggregate_delta": self.aggregate_delta.to_dict(),
            "qualification_claimed": self.qualification_claimed,
            "qualification_eligible": self.qualification_eligible,
            "qualification_status": self.qualification_status,
            "evidence_tier": "SELF_REPORTED_DEVELOPMENT_EVIDENCE",
        }

    def _report_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pairs": [pair.to_dict() for pair in self.pairs],
            "summary": self._summary(),
        }

    def _receipt_payload(self, report_hash: str) -> dict[str, Any]:
        return {
            "schema_version": PAIRED_RECEIPT_SCHEMA_VERSION,
            "report_schema_version": self.schema_version,
            "report_hash": report_hash,
            "pair_bindings": [
                {
                    "pair_id": pair.pair_id,
                    "pair_sequence": pair.pair_sequence,
                    "shared_input_hash": pair.direct_manifest.shared_input_hash,
                    "pair_hash": pair.pair_hash,
                    "direct_result_hash": pair.direct_result.result_hash,
                    "governed_result_hash": pair.governed_result.result_hash,
                }
                for pair in self.pairs
            ],
            "summary": self._summary(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._report_payload(),
            "report_hash": self.report_hash,
            "receipt_hash": self.receipt_hash,
        }


__all__ = [
    "ArmRole",
    "ExecutionTier",
    "LifecycleComparisonMetricsV1",
    "PAIRED_MANIFEST_SCHEMA_VERSION",
    "PAIRED_RECEIPT_SCHEMA_VERSION",
    "PAIRED_REPORT_SCHEMA_VERSION",
    "PAIRED_RESULT_SCHEMA_VERSION",
    "PairedArmManifestV1",
    "PairedArmResultV1",
    "PairedComparisonReportV1",
    "PairedLifecyclePairV1",
    "PairedMetricDeltaV1",
]
