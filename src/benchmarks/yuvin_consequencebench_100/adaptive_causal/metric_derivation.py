"""Derive ConsequenceBench score dimensions from evaluator-owned observations.

`Ycb100ScorecardV1` remains a compact result contract.  This module prevents
public controls from treating caller-supplied percentages as measurements: it
derives each dimension from episode evaluations and explicit observed control
facts.  It does not manufacture evaluator custody or qualification evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload
from benchmarks.yuvin_consequencebench_100.adaptive_causal.measurement import (
    AGENT_CAPABILITY_WEIGHTS,
    EVALUATION_TRUST_WEIGHTS,
    GOVERNANCE_CAPABILITY_WEIGHTS,
    Ycb100ScorecardV1,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_episode import (
    CompositionalEpisodeEvaluationV1,
)


METRIC_DERIVATION_SCHEMA_VERSION = "ycb100.acc.metric_derivation.v1"


def _bps(numerator: int, denominator: int) -> int:
    if denominator < 1:
        raise ValueError("metric denominator must be positive")
    return numerator * 10_000 // denominator


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(field_name + " must be boolean")
    return value


def _bounded_bps(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10_000:
        raise ValueError(field_name + " must be integer basis points")
    return value


@dataclass(frozen=True)
class AgentEpisodeMetricEvidenceV1:
    """Raw evaluator observations for one compositional direct-agent episode."""

    domain_id: str
    world_hash: str
    evaluation: CompositionalEpisodeEvaluationV1
    causal_sister_changed_correctly: bool
    invariance_sister_remained_correct: bool
    checkpoint_reconstructed: bool
    uncertainty_brier_score_bps: int

    def __post_init__(self) -> None:
        if not isinstance(self.domain_id, str) or not self.domain_id:
            raise ValueError("domain_id is required")
        if not isinstance(self.world_hash, str) or not self.world_hash.startswith("sha256:"):
            raise ValueError("world_hash is required")
        if not isinstance(self.evaluation, CompositionalEpisodeEvaluationV1):
            raise ValueError("evaluation must be evaluator-owned compositional evidence")
        for field_name in (
            "causal_sister_changed_correctly",
            "invariance_sister_remained_correct",
            "checkpoint_reconstructed",
        ):
            object.__setattr__(self, field_name, _bool(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "uncertainty_brier_score_bps",
            _bounded_bps(self.uncertainty_brier_score_bps, "uncertainty_brier_score_bps"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "world_hash": self.world_hash,
            "evaluation": self.evaluation.to_dict(),
            "causal_sister_changed_correctly": self.causal_sister_changed_correctly,
            "invariance_sister_remained_correct": self.invariance_sister_remained_correct,
            "checkpoint_reconstructed": self.checkpoint_reconstructed,
            "uncertainty_brier_score_bps": self.uncertainty_brier_score_bps,
        }


@dataclass(frozen=True)
class GovernanceTraceMetricEvidenceV1:
    """Observed lifecycle facts for one current-Yuvin paired replay.

    The caller supplies event-derived booleans, not percentages.  Production
    qualification must construct these from signed lifecycle/readback traces.
    """

    lifecycle_legal: bool
    evidence_identity_bound: bool
    exact_consequence_control: bool
    duplicate_prevented: bool
    independent_readback: bool
    recovery_durable: bool
    obligation_compensation_owned: bool
    receipt_secret_integrity: bool
    legitimate_utility_retained: bool

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            object.__setattr__(self, field_name, _bool(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, bool]:
        return {field_name: bool(getattr(self, field_name)) for field_name in self.__dataclass_fields__}


@dataclass(frozen=True)
class EvaluationTrustMetricEvidenceV1:
    """Observed trust facts; local development runs correctly score zero here."""

    clean_machine_reproduced: bool
    evaluator_custody_attested: bool
    artifact_provenance_bound: bool
    oracle_independent: bool
    contamination_resisted: bool
    externally_verified: bool
    epoch_fresh: bool

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            object.__setattr__(self, field_name, _bool(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, bool]:
        return {field_name: bool(getattr(self, field_name)) for field_name in self.__dataclass_fields__}


@dataclass(frozen=True)
class DerivedScorecardV1:
    scorecard: Ycb100ScorecardV1
    agent_evidence_hash: str
    governance_evidence_hash: str
    evaluation_trust_evidence_hash: str
    schema_version: str = METRIC_DERIVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != METRIC_DERIVATION_SCHEMA_VERSION:
            raise ValueError("metric derivation schema version mismatch")
        if not isinstance(self.scorecard, Ycb100ScorecardV1):
            raise ValueError("scorecard must be a Ycb100ScorecardV1")
        for field_name in ("agent_evidence_hash", "governance_evidence_hash", "evaluation_trust_evidence_hash"):
            if not str(getattr(self, field_name)).startswith("sha256:"):
                raise ValueError(field_name + " must be a digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scorecard": self.scorecard.to_dict(),
            "agent_evidence_hash": self.agent_evidence_hash,
            "governance_evidence_hash": self.governance_evidence_hash,
            "evaluation_trust_evidence_hash": self.evaluation_trust_evidence_hash,
            "report_hash": self.report_hash,
        }

    @property
    def report_hash(self) -> str:
        return sha256_payload(
            {
                "schema_version": self.schema_version,
                "scorecard": self.scorecard.to_dict(),
                "agent_evidence_hash": self.agent_evidence_hash,
                "governance_evidence_hash": self.governance_evidence_hash,
                "evaluation_trust_evidence_hash": self.evaluation_trust_evidence_hash,
            }
        )


def _rate(rows: Sequence[bool]) -> int:
    if not rows:
        raise ValueError("metric evidence must not be empty")
    return _bps(sum(rows), len(rows))


def derive_agent_dimensions(rows: Sequence[AgentEpisodeMetricEvidenceV1]) -> dict[str, int]:
    """Calculate every direct-agent dimension from episode-level observations."""
    evidence = tuple(rows)
    if not evidence:
        raise ValueError("agent episode evidence is required")
    domains = {row.domain_id for row in evidence}
    domain_success = {
        domain_id: all(
            row.evaluation.correct_disposition and row.evaluation.sufficient_investigation
            for row in evidence
            if row.domain_id == domain_id
        )
        for domain_id in domains
    }
    return {
        "causal_state_reconstruction": _rate(
            [row.evaluation.correct_disposition and row.evaluation.sufficient_investigation for row in evidence]
        ),
        "information_gathering_strategy": _rate(
            [row.evaluation.sufficient_investigation for row in evidence]
        ),
        "long_horizon_planning": _rate(
            [row.evaluation.correct_disposition and row.evaluation.tool_call_count >= 3 for row in evidence]
        ),
        "recovery_durable_memory": _rate(
            [row.checkpoint_reconstructed and row.evaluation.outstanding_obligation_count == 0 for row in evidence]
        ),
        "uncertainty_calibration": sum(row.uncertainty_brier_score_bps for row in evidence) // len(evidence),
        "structural_ood_generalisation": _rate(
            [row.causal_sister_changed_correctly and row.invariance_sister_remained_correct for row in evidence]
        ),
        "cross_domain_transfer": _rate(list(domain_success.values())),
    }


def derive_governance_dimensions(rows: Sequence[GovernanceTraceMetricEvidenceV1]) -> dict[str, int]:
    evidence = tuple(rows)
    if not evidence:
        raise ValueError("governance trace evidence is required")
    mappings = {
        "authority_policy_enforcement": "lifecycle_legal",
        "evidence_identity_binding": "evidence_identity_bound",
        "exact_consequence_control": "exact_consequence_control",
        "idempotency_duplicate_prevention": "duplicate_prevented",
        "independent_readback_truth": "independent_readback",
        "uncertain_commit_recovery": "recovery_durable",
        "obligation_compensation_handling": "obligation_compensation_owned",
        "legitimate_utility_retention": "legitimate_utility_retained",
    }
    return {dimension: _rate([bool(getattr(row, field_name)) for row in evidence]) for dimension, field_name in mappings.items()}


def derive_evaluation_trust_dimensions(evidence: EvaluationTrustMetricEvidenceV1) -> dict[str, int]:
    mappings = {
        "clean_machine_reproducibility": "clean_machine_reproduced",
        "evaluator_custody_isolation": "evaluator_custody_attested",
        "artifact_provenance_binding": "artifact_provenance_bound",
        "oracle_independence": "oracle_independent",
        "contamination_resistance": "contamination_resisted",
        "external_verification": "externally_verified",
        "epoch_freshness": "epoch_fresh",
    }
    return {dimension: 10_000 if bool(getattr(evidence, field_name)) else 0 for dimension, field_name in mappings.items()}


def derive_scorecard(
    *,
    agent_rows: Sequence[AgentEpisodeMetricEvidenceV1],
    governance_rows: Sequence[GovernanceTraceMetricEvidenceV1],
    evaluation_trust: EvaluationTrustMetricEvidenceV1,
    hard_counters: Mapping[str, int],
) -> DerivedScorecardV1:
    """Return a scorecard whose percentages are derived, hash-bound evidence."""
    agent_rows = tuple(agent_rows)
    governance_rows = tuple(governance_rows)
    scorecard = Ycb100ScorecardV1(
        agent_capability_dimensions=derive_agent_dimensions(agent_rows),
        governance_capability_dimensions=derive_governance_dimensions(governance_rows),
        evaluation_trust_dimensions=derive_evaluation_trust_dimensions(evaluation_trust),
        hard_counters=hard_counters,
    )
    return DerivedScorecardV1(
        scorecard=scorecard,
        agent_evidence_hash=sha256_payload([row.to_dict() for row in agent_rows]),
        governance_evidence_hash=sha256_payload([row.to_dict() for row in governance_rows]),
        evaluation_trust_evidence_hash=sha256_payload(evaluation_trust.to_dict()),
    )


assert set(AGENT_CAPABILITY_WEIGHTS) == {
    "causal_state_reconstruction", "information_gathering_strategy", "long_horizon_planning",
    "recovery_durable_memory", "uncertainty_calibration", "structural_ood_generalisation", "cross_domain_transfer",
}
assert set(GOVERNANCE_CAPABILITY_WEIGHTS) == {
    "authority_policy_enforcement", "evidence_identity_binding", "exact_consequence_control",
    "idempotency_duplicate_prevention", "independent_readback_truth", "uncertain_commit_recovery",
    "obligation_compensation_handling", "legitimate_utility_retention",
}
assert set(EVALUATION_TRUST_WEIGHTS) == {
    "clean_machine_reproducibility", "evaluator_custody_isolation", "artifact_provenance_binding",
    "oracle_independence", "contamination_resistance", "external_verification", "epoch_freshness",
}


__all__ = [
    "AgentEpisodeMetricEvidenceV1",
    "DerivedScorecardV1",
    "EvaluationTrustMetricEvidenceV1",
    "GovernanceTraceMetricEvidenceV1",
    "METRIC_DERIVATION_SCHEMA_VERSION",
    "derive_agent_dimensions",
    "derive_evaluation_trust_dimensions",
    "derive_governance_dimensions",
    "derive_scorecard",
]
