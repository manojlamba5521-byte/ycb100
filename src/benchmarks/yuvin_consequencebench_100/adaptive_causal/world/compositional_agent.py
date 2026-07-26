"""Proposal-generation adapter for arbitrary agents in compositional ConsequenceBench worlds.

Agents receive raw records, read-only tools, and a public proposal envelope.
They submit a decision claim, never a caller-authored trusted-evidence or
canonical-action record. The evaluator normalizes that claim into the one
immutable candidate replayed by the study arms.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    AgentManifestV1,
    CandidateGenerationManifestV1,
    FrozenActionProposalCandidateV1,
    RunManifestV1,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.compositional_episode import (
    CompositionalAdapterRunV1,
    run_jsonl_compositional_episode,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.jsonl_adapter import AdapterInvocationV1
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_effect import (
    CompositionalEffectWorldV1,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_episode import (
    CompositionalCausalEpisodeV1,
    CompositionalWorldSpecV1,
)


COMPOSITIONAL_PROPOSAL_ENVELOPE_SCHEMA_VERSION = "ycb100.acc.compositional_proposal_envelope.v1"
COMPOSITIONAL_AGENT_CANDIDATE_RESULT_SCHEMA_VERSION = "ycb100.acc.compositional_agent_candidate_result.v1"
READ_ONLY_COMPOSITIONAL_TOOLS = (
    "record.inspect",
    "source.read",
    "risk.probe",
    "approval.request",
)


def _identifier(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 128:
        raise ValueError(field_name + " must be a bounded identifier")
    return normalized


def _digest(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("sha256:") or len(normalized) != 71:
        raise ValueError(field_name + " must be a sha256 digest")
    return normalized


@dataclass(frozen=True)
class CompositionalProposalEnvelopeV1:
    """Public, non-authoritative fields used to construct one candidate."""

    episode_id: str
    tenant_id: str
    connector_id: str
    action_type: str
    target_claim: Mapping[str, Any]
    parameters_claim: Mapping[str, Any]
    evidence_handles: tuple[str, ...]
    authority_references: tuple[str, ...]
    idempotency_namespace: str
    schema_version: str = COMPOSITIONAL_PROPOSAL_ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPOSITIONAL_PROPOSAL_ENVELOPE_SCHEMA_VERSION:
            raise ValueError("compositional proposal envelope schema version mismatch")
        for field_name in (
            "episode_id",
            "tenant_id",
            "connector_id",
            "action_type",
            "idempotency_namespace",
        ):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        target = dict(self.target_claim)
        parameters = dict(self.parameters_claim)
        if set(target) != {"subject_id"}:
            raise ValueError("proposal envelope target_claim is invalid")
        if set(parameters) != {"operation", "request_nonce"}:
            raise ValueError("proposal envelope parameters_claim is invalid")
        object.__setattr__(self, "target_claim", target)
        object.__setattr__(self, "parameters_claim", parameters)
        handles = tuple(_identifier(value, "evidence_handle") for value in self.evidence_handles)
        authorities = tuple(_identifier(value, "authority_reference") for value in self.authority_references)
        if len(handles) != 1 or len(authorities) != 1:
            raise ValueError("proposal envelope requires exactly one opaque evidence and authority reference")
        object.__setattr__(self, "evidence_handles", handles)
        object.__setattr__(self, "authority_references", authorities)

    def to_agent_view(self) -> dict[str, Any]:
        """Expose non-authoritative proposal slots without outcome information."""
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "tenant_id": self.tenant_id,
            "connector_id": self.connector_id,
            "action_type": self.action_type,
            "target_claim": dict(self.target_claim),
            "parameters_claim": dict(self.parameters_claim),
            "evidence_handles": list(self.evidence_handles),
            "authority_references": list(self.authority_references),
            "allowed_decisions": ["execute", "deny", "defer", "escalate", "compensate"],
            "submission": "decision_submit_only",
        }

    @property
    def envelope_hash(self) -> str:
        return sha256_payload(self.to_agent_view())

    def candidate_from_decision(
        self,
        *,
        decision: Mapping[str, Any],
        agent_manifest_hash: str,
        generation_manifest_hash: str,
        transcript_hash: str,
    ) -> FrozenActionProposalCandidateV1:
        normalized_decision = str(decision.get("decision") or "").strip()
        rationale = decision.get("rationale_record_ids")
        confidence = decision.get("confidence_basis_points")
        if normalized_decision not in {"execute", "deny", "defer", "escalate", "compensate"}:
            raise ValueError("agent decision is invalid")
        if not isinstance(rationale, (list, tuple)) or not rationale:
            raise ValueError("agent decision requires rationale record identifiers")
        rationale_ids = tuple(_identifier(value, "rationale_record_id") for value in rationale)
        if not isinstance(confidence, int) or isinstance(confidence, bool) or not 0 <= confidence <= 10_000:
            raise ValueError("agent decision confidence is invalid")
        manifest_hash = _digest(agent_manifest_hash, "agent_manifest_hash")
        generation_hash = _digest(generation_manifest_hash, "generation_manifest_hash")
        trace_hash = _digest(transcript_hash, "transcript_hash")
        semantic_checkpoint_hash = sha256_payload(
            {
                "proposal_envelope_hash": self.envelope_hash,
                "agent_manifest_hash": manifest_hash,
                "generation_manifest_hash": generation_hash,
                "transcript_hash": trace_hash,
                "decision": normalized_decision,
                "rationale_record_ids": rationale_ids,
                "confidence_basis_points": confidence,
            }
        )
        candidate_id = "candidate_" + sha256_payload(
            {"proposal_envelope_hash": self.envelope_hash, "semantic_checkpoint_hash": semantic_checkpoint_hash}
        )[7:31]
        idempotency_key = self.idempotency_namespace + "_" + semantic_checkpoint_hash[7:23]
        return FrozenActionProposalCandidateV1(
            candidate_id=candidate_id,
            tenant_id=self.tenant_id,
            connector_id=self.connector_id,
            action_type=self.action_type,
            decision=normalized_decision,
            target_claim=self.target_claim,
            parameters_claim=self.parameters_claim,
            evidence_handles=self.evidence_handles,
            authority_references=self.authority_references,
            idempotency_key=idempotency_key,
            semantic_checkpoint_hash=semantic_checkpoint_hash,
        )


@dataclass(frozen=True)
class CompositionalAgentCandidateResultV1:
    """One arbitrary-agent proposal attempt and its bound frozen candidate."""

    proposal_envelope: CompositionalProposalEnvelopeV1
    agent_start_hash: str
    generation_manifest: CandidateGenerationManifestV1
    adapter_run: CompositionalAdapterRunV1
    candidate: FrozenActionProposalCandidateV1 | None
    final_run_manifest: RunManifestV1 | None
    schema_version: str = COMPOSITIONAL_AGENT_CANDIDATE_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPOSITIONAL_AGENT_CANDIDATE_RESULT_SCHEMA_VERSION:
            raise ValueError("compositional agent candidate result schema version mismatch")
        _digest(self.agent_start_hash, "agent_start_hash")
        if self.generation_manifest.world_snapshot_hash != self.agent_start_hash:
            raise ValueError("generation manifest is not bound to the agent start view")
        if self.adapter_run.run_manifest_hash != self.generation_manifest.manifest_hash:
            raise ValueError("adapter run is not bound to its generation manifest")
        if self.adapter_run.agent_manifest_hash != self.generation_manifest.agent_manifest_hash:
            raise ValueError("adapter run is not bound to its agent manifest")
        completed = self.adapter_run.status == "COMPLETED"
        if completed != (self.candidate is not None):
            raise ValueError("completed proposal attempts require exactly one candidate")
        if completed != (self.final_run_manifest is not None):
            raise ValueError("completed proposal attempts require a final run manifest")
        if self.candidate is not None and self.final_run_manifest is not None:
            expected = self.generation_manifest.bind_candidate(self.candidate.payload_hash)
            if self.final_run_manifest.manifest_hash != expected.manifest_hash:
                raise ValueError("final run manifest is not bound to the normalized candidate")

    @property
    def status(self) -> str:
        return self.adapter_run.status

    @property
    def report_hash(self) -> str:
        return sha256_payload(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "proposal_envelope_hash": self.proposal_envelope.envelope_hash,
            "agent_start_hash": self.agent_start_hash,
            "generation_manifest": self.generation_manifest.to_dict(),
            "adapter_run": self.adapter_run.to_dict(),
            "candidate": self.candidate.to_dict() if self.candidate is not None else None,
            "final_run_manifest": self.final_run_manifest.to_dict() if self.final_run_manifest is not None else None,
        }
        if include_hash:
            payload["report_hash"] = sha256_payload(payload)
        return payload


class CompositionalAgentEpisodeV1:
    """Evaluator-owned read-only proposal episode for one arbitrary process."""

    def __init__(self, spec: CompositionalWorldSpecV1, *, tool_budget: int = 18) -> None:
        self.spec = spec
        self.episode = CompositionalCausalEpisodeV1(spec, tool_budget=tool_budget)
        self.effect_world = CompositionalEffectWorldV1.from_spec(spec)
        self.proposal_envelope = build_compositional_proposal_envelope(self.effect_world)

    def agent_start(self) -> dict[str, Any]:
        start = self.episode.agent_view()
        start["tool_manifest"] = [
            item for item in start["tool_manifest"] if item.get("name") in READ_ONLY_COMPOSITIONAL_TOOLS
        ]
        start["proposal_envelope"] = self.proposal_envelope.to_agent_view()
        return start

    def run(
        self,
        *,
        invocation: AdapterInvocationV1,
        agent_manifest: AgentManifestV1,
        environment: Mapping[str, str] | None = None,
    ) -> CompositionalAgentCandidateResultV1:
        start = self.agent_start()
        generation = CandidateGenerationManifestV1(
            benchmark_build_hash=sha256_payload(
                {
                    "module": "ycb100.adaptive_causal.compositional_agent.v1",
                    "read_only_tools": READ_ONLY_COMPOSITIONAL_TOOLS,
                }
            ),
            agent_manifest_hash=agent_manifest.manifest_hash,
            world_snapshot_hash=sha256_payload(start),
            execution_tier="CONTAINMENT_ONLY",
        )
        adapter_run = run_jsonl_compositional_episode(
            episode=self.episode,
            invocation=invocation,
            agent_manifest=agent_manifest,
            run_manifest=generation,
            environment=environment,
            agent_start=start,
            allowed_tools=READ_ONLY_COMPOSITIONAL_TOOLS,
        )
        candidate: FrozenActionProposalCandidateV1 | None = None
        final_run_manifest: RunManifestV1 | None = None
        if adapter_run.status == "COMPLETED" and adapter_run.decision is not None:
            known_record_ids = {str(record["record_id"]) for record in start["records"]}
            rationale = adapter_run.decision.get("rationale_record_ids")
            if not isinstance(rationale, list) or not set(rationale).issubset(known_record_ids):
                adapter_run = replace(
                    adapter_run,
                    status="FAILED",
                    decision=None,
                    failure_reason="agent_rationale_outside_supplied_world",
                )
            else:
                candidate = self.proposal_envelope.candidate_from_decision(
                    decision=adapter_run.decision,
                    agent_manifest_hash=agent_manifest.manifest_hash,
                    generation_manifest_hash=generation.manifest_hash,
                    transcript_hash=adapter_run.trace_hash,
                )
                final_run_manifest = generation.bind_candidate(candidate.payload_hash)
        return CompositionalAgentCandidateResultV1(
            proposal_envelope=self.proposal_envelope,
            agent_start_hash=sha256_payload(start),
            generation_manifest=generation,
            adapter_run=adapter_run,
            candidate=candidate,
            final_run_manifest=final_run_manifest,
        )


def build_compositional_proposal_envelope(
    world: CompositionalEffectWorldV1,
) -> CompositionalProposalEnvelopeV1:
    """Create public candidate slots without exposing evaluator truth fields."""
    context = world.context
    return CompositionalProposalEnvelopeV1(
        episode_id="episode_" + context.spec.world_id,
        tenant_id="tenant_" + context.spec.domain_id,
        connector_id="ycb100_" + context.spec.domain_id,
        action_type=context.requested_operation,
        target_claim={"subject_id": context.subject_id},
        parameters_claim={"operation": context.requested_operation, "request_nonce": context.request_nonce},
        evidence_handles=(context.evidence_handle,),
        authority_references=("authority_" + context.spec.world_hash[7:25],),
        idempotency_namespace="idem_" + context.spec.world_hash[7:21],
    )


__all__ = [
    "COMPOSITIONAL_AGENT_CANDIDATE_RESULT_SCHEMA_VERSION",
    "COMPOSITIONAL_PROPOSAL_ENVELOPE_SCHEMA_VERSION",
    "READ_ONLY_COMPOSITIONAL_TOOLS",
    "CompositionalAgentCandidateResultV1",
    "CompositionalAgentEpisodeV1",
    "CompositionalProposalEnvelopeV1",
    "build_compositional_proposal_envelope",
]
