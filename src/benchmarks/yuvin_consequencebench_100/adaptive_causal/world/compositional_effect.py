"""Evaluator-owned source world for five-domain compositional paired replay.

The public compositional episode exposes only records and named tools.  This
module is a separate evaluator-side adapter that converts a frozen public
world specification into a synthetic source system suitable for direct versus
current-Yuvin replay.  It is intentionally not part of the agent tool surface.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    FrozenActionProposalCandidateV1,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_episode import (
    CompositionalCausalEpisodeV1,
    CompositionalWorldSpecV1,
)


COMPOSITIONAL_EFFECT_WORLD_SCHEMA_VERSION = "ycb100.acc.compositional_effect_world.v1"

_TERMINAL_TO_DECISION = {
    "VERIFIED": "execute",
    "REJECTED": "deny",
    "DEFERRED": "defer",
    "ESCALATED": "escalate",
    "COMPENSATED": "compensate",
}


def _identifier(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 128:
        raise ValueError(field_name + " must be a bounded identifier")
    return normalized


@dataclass(frozen=True)
class CompositionalExecutionContextV1:
    """Evaluator-only facts needed to run one frozen candidate through an arm."""

    spec: CompositionalWorldSpecV1
    semantic_decision: str
    requested_operation: str
    subject_id: str
    evidence_handle: str
    request_nonce: str
    trusted_evidence_admissible: bool
    authority_active: bool
    policy_allows_execution: bool
    compensation_required: bool
    source_bundle_hash: str
    event_commitment_hash: str
    fault_commitment_hash: str
    schema_version: str = COMPOSITIONAL_EFFECT_WORLD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPOSITIONAL_EFFECT_WORLD_SCHEMA_VERSION:
            raise ValueError("compositional execution context schema version mismatch")
        if self.semantic_decision not in _TERMINAL_TO_DECISION.values():
            raise ValueError("semantic_decision is invalid")
        for field_name in ("requested_operation", "subject_id", "evidence_handle", "request_nonce"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        for field_name in ("source_bundle_hash", "event_commitment_hash", "fault_commitment_hash"):
            digest = str(getattr(self, field_name) or "").strip()
            if not digest.startswith("sha256:"):
                raise ValueError(field_name + " must be a digest")
            object.__setattr__(self, field_name, digest)
        expected = {
            "execute": (True, True, True, False),
            "deny": (True, False, False, False),
            "defer": (False, True, False, False),
            "escalate": (True, True, False, False),
            "compensate": (True, True, True, True),
        }[self.semantic_decision]
        observed = (
            self.trusted_evidence_admissible,
            self.authority_active,
            self.policy_allows_execution,
            self.compensation_required,
        )
        if observed != expected:
            raise ValueError("execution context does not match its semantic decision")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "spec": self.spec.to_dict(),
            "semantic_decision": self.semantic_decision,
            "requested_operation": self.requested_operation,
            "subject_id": self.subject_id,
            "evidence_handle": self.evidence_handle,
            "request_nonce": self.request_nonce,
            "trusted_evidence_admissible": self.trusted_evidence_admissible,
            "authority_active": self.authority_active,
            "policy_allows_execution": self.policy_allows_execution,
            "compensation_required": self.compensation_required,
            "source_bundle_hash": self.source_bundle_hash,
            "event_commitment_hash": self.event_commitment_hash,
            "fault_commitment_hash": self.fault_commitment_hash,
        }

    @property
    def context_hash(self) -> str:
        return sha256_payload(self.to_dict())


def build_compositional_execution_context(
    spec: CompositionalWorldSpecV1,
) -> CompositionalExecutionContextV1:
    """Derive evaluator-side execution facts without extending the agent view."""
    episode = CompositionalCausalEpisodeV1(spec)
    agent_view = episode.agent_view()
    fixture = episode.reference_execute()
    try:
        decision = _TERMINAL_TO_DECISION[fixture.terminal_disposition]
    except KeyError as error:
        raise AssertionError("reference fixture has no executable decision") from error
    # This mirrors the stable identity derivation used by the public episode
    # generator without reaching into its private record store.
    token = sha256_payload(
        {"domain_id": spec.domain_id, "family_index": spec.family_index, "seed": spec.seed}
    )[7:31]
    subject_id = "subject_" + token[:12]
    request_nonce = token[10:20]
    source_bundle = {
        "agent_view": agent_view,
        "fixture": fixture.to_dict(),
        "source_identity": {"subject_id": subject_id, "request_nonce": request_nonce},
    }
    return CompositionalExecutionContextV1(
        spec=spec,
        semantic_decision=decision,
        requested_operation=str(agent_view["objective"]["requested_operation"]),
        subject_id=subject_id,
        evidence_handle="evidence_" + spec.world_hash[7:31],
        request_nonce=request_nonce,
        trusted_evidence_admissible=decision != "defer",
        authority_active=decision != "deny",
        policy_allows_execution=decision in {"execute", "compensate"},
        compensation_required=decision == "compensate",
        source_bundle_hash=sha256_payload(source_bundle),
        event_commitment_hash=sha256_payload(
            {"world_hash": spec.world_hash, "variant_id": spec.variant_id, "fixture_trace": fixture.trace_hash}
        ),
        fault_commitment_hash=sha256_payload(
            {"world_hash": spec.world_hash, "compensation_required": decision == "compensate"}
        ),
    )


class CompositionalEffectWorldV1:
    """Forkable synthetic source state used by direct and governed arm replays."""

    def __init__(self, context: CompositionalExecutionContextV1) -> None:
        if not isinstance(context, CompositionalExecutionContextV1):
            raise TypeError("context must be a CompositionalExecutionContextV1")
        self.context = context
        self._source: dict[str, Any] = {
            "subject_id": context.subject_id,
            "requested_operation": context.requested_operation,
            "request_nonce": context.request_nonce,
            "effects": {},
            "compensations": {},
        }
        if context.compensation_required:
            effect_id = self.preexisting_effect_id
            self._source["effects"][effect_id] = {
                "effect_id": effect_id,
                "actor_id": "source_history",
                "candidate_hash": sha256_payload(
                    {"world_hash": context.spec.world_hash, "origin": "preexisting_source"}
                ),
                "subject_id": context.subject_id,
                "requested_operation": context.requested_operation,
                "effect_hash": sha256_payload(
                    {
                        "effect_id": effect_id,
                        "subject_id": context.subject_id,
                        "operation": context.requested_operation,
                        "origin": "preexisting_source",
                    }
                ),
                "preexisting": True,
                "source_state": "committed_response_lost",
            }

    @classmethod
    def from_spec(cls, spec: CompositionalWorldSpecV1) -> "CompositionalEffectWorldV1":
        return cls(build_compositional_execution_context(spec))

    def fork(self) -> "CompositionalEffectWorldV1":
        clone = CompositionalEffectWorldV1(self.context)
        clone._source = deepcopy(self._source)
        return clone

    @property
    def source_snapshot_hash(self) -> str:
        return sha256_payload(self._source)

    @property
    def context_hash(self) -> str:
        return self.context.context_hash

    @property
    def source_system(self) -> str:
        return "ycb100_" + self.context.spec.domain_id + "_source"

    @property
    def preexisting_effect_id(self) -> str:
        if not self.context.compensation_required:
            return ""
        return "preexisting_effect_" + self.context.spec.world_hash[7:31]

    def source_evidence_payload(self) -> dict[str, Any]:
        """Return an exact source projection without evaluator outcome labels."""
        return {
            "subject_id": self.context.subject_id,
            "requested_operation": self.context.requested_operation,
            "request_nonce": self.context.request_nonce,
            "source_snapshot_hash": self.source_snapshot_hash,
            "effect_count": len(self._source["effects"]),
            "preexisting_effect_id": self.preexisting_effect_id,
        }

    def reference_candidate(self) -> FrozenActionProposalCandidateV1:
        """Create a fixture candidate only for development-control replay."""
        context = self.context
        return FrozenActionProposalCandidateV1(
            candidate_id="candidate_" + context.spec.world_hash[7:27],
            tenant_id="tenant_" + context.spec.domain_id,
            connector_id="ycb100_" + context.spec.domain_id,
            action_type=context.requested_operation,
            decision=context.semantic_decision,
            target_claim={"subject_id": context.subject_id},
            parameters_claim={
                "operation": context.requested_operation,
                "request_nonce": context.request_nonce,
            },
            evidence_handles=(context.evidence_handle,),
            authority_references=("authority_" + context.spec.world_hash[7:25],),
            idempotency_key="key_" + context.spec.world_hash[7:28],
            semantic_checkpoint_hash=context.context_hash,
        )

    def execute_effect(
        self,
        *,
        effect_id: str,
        candidate: FrozenActionProposalCandidateV1,
        actor_id: str,
    ) -> Mapping[str, Any]:
        """Commit one direct or governed synthetic external effect.

        This source intentionally does not enforce policy.  The direct arm is
        allowed to make an unsafe request so the paired study can measure the
        consequence that the governed arm prevents.
        """
        effect_id = _identifier(effect_id, "effect_id")
        existing = self._source["effects"].get(effect_id)
        if existing is not None:
            return {"committed": True, "effect_id": effect_id, "idempotent_replay": True}
        effect = {
            "effect_id": effect_id,
            "actor_id": _identifier(actor_id, "actor_id"),
            "candidate_hash": candidate.payload_hash,
            "subject_id": self.context.subject_id,
            "requested_operation": self.context.requested_operation,
            "effect_hash": sha256_payload(
                {
                    "effect_id": effect_id,
                    "candidate_hash": candidate.payload_hash,
                    "subject_id": self.context.subject_id,
                    "operation": self.context.requested_operation,
                }
            ),
        }
        self._source["effects"][effect_id] = effect
        return {"committed": True, "effect_id": effect_id, "idempotent_replay": False}

    def independent_readback(
        self,
        *,
        effect_id: str,
        candidate: FrozenActionProposalCandidateV1,
    ) -> Mapping[str, Any] | None:
        effect = self._source["effects"].get(str(effect_id))
        if effect is None or candidate.target_claim.get("subject_id") != self.context.subject_id:
            return None
        return {
            "effect_id": effect_id,
            "source_effect_hash": effect["effect_hash"],
            "subject_id": self.context.subject_id,
            "requested_operation": self.context.requested_operation,
            "compensated": bool(self._source["compensations"].get(effect_id)),
            "source_snapshot_hash": self.source_snapshot_hash,
        }

    def reconcile_preexisting_effect(
        self,
        *,
        effect_id: str,
        candidate: FrozenActionProposalCandidateV1,
    ) -> Mapping[str, Any]:
        """Read the original source effect without issuing a second primary write."""
        readback = self.independent_readback(effect_id=effect_id, candidate=candidate)
        if readback is None or effect_id != self.preexisting_effect_id:
            return {"observed": False, "reason": "preexisting_effect_not_found"}
        return {"observed": True, **readback}

    def compensate_effect(self, *, effect_id: str, actor_id: str) -> Mapping[str, Any]:
        effect = self._source["effects"].get(str(effect_id))
        if effect is None:
            return {"compensated": False, "reason": "effect_not_found"}
        existing = self._source["compensations"].get(effect_id)
        if existing is not None:
            return {"compensated": True, "effect_id": effect_id, "idempotent_replay": True}
        compensation = {
            "effect_id": effect_id,
            "actor_id": _identifier(actor_id, "actor_id"),
            "compensation_hash": sha256_payload(
                {"effect_id": effect_id, "source_effect_hash": effect["effect_hash"], "actor_id": actor_id}
            ),
        }
        self._source["compensations"][effect_id] = compensation
        return {"compensated": True, "effect_id": effect_id, "idempotent_replay": False}

    def compensate_preexisting_effect(self, *, effect_id: str, actor_id: str) -> Mapping[str, Any]:
        if not self.preexisting_effect_id or effect_id != self.preexisting_effect_id:
            return {"compensated": False, "reason": "wrong_compensation_effect"}
        return self.compensate_effect(effect_id=effect_id, actor_id=actor_id)

    def independent_compensation_readback(
        self,
        *,
        effect_id: str,
        candidate: FrozenActionProposalCandidateV1,
    ) -> Mapping[str, Any] | None:
        if effect_id != self.preexisting_effect_id:
            return None
        readback = self.independent_readback(effect_id=effect_id, candidate=candidate)
        compensation = self._source["compensations"].get(effect_id)
        if readback is None or compensation is None:
            return None
        return {
            **readback,
            "compensation_hash": compensation["compensation_hash"],
            "compensated": True,
        }

    def snapshot_payload(self) -> dict[str, Any]:
        return deepcopy(self._source)


__all__ = [
    "COMPOSITIONAL_EFFECT_WORLD_SCHEMA_VERSION",
    "CompositionalEffectWorldV1",
    "CompositionalExecutionContextV1",
    "build_compositional_execution_context",
]
