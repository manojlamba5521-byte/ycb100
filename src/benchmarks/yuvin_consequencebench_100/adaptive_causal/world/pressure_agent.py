"""Contained arbitrary-agent adapter for Pressure Worlds pressure worlds."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    AgentManifestV1,
    CandidateGenerationManifestV1,
    FrozenActionProposalCandidateV1,
    RunManifestV1,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.compositional_episode import (
    run_jsonl_compositional_episode,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.jsonl_adapter import AdapterInvocationV1
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_agent import (
    READ_ONLY_COMPOSITIONAL_TOOLS,
    CompositionalAgentCandidateResultV1,
    CompositionalProposalEnvelopeV1,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_effect import (
    CompositionalEffectWorldV1,
    CompositionalExecutionContextV1,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_episode import (
    CompositionalWorldSpecV1,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.pressure_episode import (
    PRESSURE_DISPATCH_TICK,
    PRESSURE_DYNAMIC_TICK,
    PRESSURE_TOOL_BUDGET,
    PressureCausalEpisodeV1,
    PressureWorldSpecV1,
)


PRESSURE_AGENT_BUILD_ID = "ycb100.acc.pressure_agent.v1"


def build_pressure_effect_world(episode: PressureCausalEpisodeV1) -> CompositionalEffectWorldV1:
    """Compress evaluator truth into the current Yuvin arm's execution contract."""
    oracle = episode.oracle
    surrogate_spec = CompositionalWorldSpecV1(
        domain_id=episode.spec.domain_id,
        family_index=episode.spec.family_index,
        seed=episode.spec.seed,
        variant_id=episode.spec.variant_id,
    )
    start_hash = sha256_payload(episode.agent_view())
    context = CompositionalExecutionContextV1(
        spec=surrogate_spec,
        semantic_decision=oracle.decision,
        requested_operation=episode.operation,
        subject_id=episode.subject_id,
        evidence_handle="evidence_pressure_" + episode.spec.world_hash[7:31],
        request_nonce=episode.request_nonce,
        trusted_evidence_admissible=oracle.decision != "defer",
        authority_active=oracle.decision != "deny",
        policy_allows_execution=oracle.decision in {"execute", "compensate"},
        compensation_required=oracle.decision == "compensate",
        source_bundle_hash=sha256_payload(
            {
                "pressure_world_hash": episode.spec.world_hash,
                "agent_start_hash": start_hash,
                "oracle_input_hash": oracle.oracle_input_hash,
            }
        ),
        event_commitment_hash=sha256_payload(
            {
                "pressure_world_hash": episode.spec.world_hash,
                "dynamic_update_tick": PRESSURE_DYNAMIC_TICK,
                "dispatch_tick": PRESSURE_DISPATCH_TICK,
            }
        ),
        fault_commitment_hash=sha256_payload(
            {
                "pressure_world_hash": episode.spec.world_hash,
                "response_loss": oracle.decision == "compensate",
                "fault_schedule_version": "pressure.v1",
            }
        ),
    )
    return CompositionalEffectWorldV1(context)


class PressureAgentEpisodeV1:
    """One long-context proposal-generation attempt with no effect capability."""

    def __init__(self, spec: PressureWorldSpecV1, *, tool_budget: int = PRESSURE_TOOL_BUDGET) -> None:
        self.spec = spec
        self.episode = PressureCausalEpisodeV1(spec, tool_budget=tool_budget)
        self.effect_world = build_pressure_effect_world(self.episode)
        self.proposal_envelope = CompositionalProposalEnvelopeV1(
            episode_id=self.episode.episode_id,
            tenant_id=self.episode.tenant_id,
            connector_id="ycb100_" + spec.domain_id,
            action_type=self.episode.operation,
            target_claim={"subject_id": self.episode.subject_id},
            parameters_claim={
                "operation": self.episode.operation,
                "request_nonce": self.episode.request_nonce,
            },
            evidence_handles=(self.effect_world.context.evidence_handle,),
            authority_references=("authority_pressure_" + spec.world_hash[7:25],),
            idempotency_namespace="idem_pressure_" + spec.world_hash[7:21],
        )

    def agent_start(
        self,
        *,
        proposal_round: int | None = None,
        proposal_round_limit: int | None = None,
        boundary_feedback: Mapping[str, Any] | None = None,
        prior_proposals: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, object]:
        start = self.episode.agent_view()
        start["tool_manifest"] = [
            item
            for item in start["tool_manifest"]
            if item.get("name") in READ_ONLY_COMPOSITIONAL_TOOLS
        ]
        start["proposal_envelope"] = self.proposal_envelope.to_agent_view()
        if proposal_round is not None:
            if not isinstance(proposal_round, int) or isinstance(proposal_round, bool) or proposal_round < 1:
                raise ValueError("proposal_round must be a positive integer")
            if (
                not isinstance(proposal_round_limit, int)
                or isinstance(proposal_round_limit, bool)
                or proposal_round_limit < proposal_round
            ):
                raise ValueError("proposal_round_limit must include proposal_round")
            start["proposal_round"] = proposal_round
            start["proposal_round_limit"] = proposal_round_limit
        if boundary_feedback is not None:
            start["boundary_feedback"] = dict(boundary_feedback)
        if prior_proposals:
            start["prior_proposals"] = [dict(item) for item in prior_proposals]
        return start

    def run(
        self,
        *,
        invocation: AdapterInvocationV1,
        agent_manifest: AgentManifestV1,
        environment: Mapping[str, str] | None = None,
        proposal_round: int | None = None,
        proposal_round_limit: int | None = None,
        boundary_feedback: Mapping[str, Any] | None = None,
        prior_proposals: Sequence[Mapping[str, Any]] = (),
    ) -> CompositionalAgentCandidateResultV1:
        start = self.agent_start(
            proposal_round=proposal_round,
            proposal_round_limit=proposal_round_limit,
            boundary_feedback=boundary_feedback,
            prior_proposals=prior_proposals,
        )
        generation = CandidateGenerationManifestV1(
            benchmark_build_hash=sha256_payload(
                {
                    "module": PRESSURE_AGENT_BUILD_ID,
                    "read_only_tools": READ_ONLY_COMPOSITIONAL_TOOLS,
                    "pressure_world_schema": self.spec.schema_version,
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
            if not isinstance(rationale, list) or not rationale or not set(rationale).issubset(known_record_ids):
                adapter_run = replace(
                    adapter_run,
                    status="FAILED",
                    decision=None,
                    failure_reason="agent_rationale_outside_supplied_pressure_world",
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


__all__ = [
    "PRESSURE_AGENT_BUILD_ID",
    "PressureAgentEpisodeV1",
    "build_pressure_effect_world",
]
