"""Bridge a contained JSONL agent episode to the ConsequenceBench banking control plane."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    AgentManifestV1,
    CandidateGenerationManifestV1,
    FrozenActionProposalCandidateV1,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner import (
    AdapterInvocationV1,
    AdapterRunResultV1,
    JsonlContainmentRunner,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.banking import BankingRefundWorld
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.gateway import ToolDefinitionV1, ToolGatewayV1


@dataclass(frozen=True)
class BankingAgentEpisodeResultV1:
    candidate: FrozenActionProposalCandidateV1
    adapter_result: AdapterRunResultV1
    tool_audit_hash: str
    schema_version: str = "ycb100.acc.banking_agent_episode_result.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate": self.candidate.to_dict(),
            "adapter_result": self.adapter_result.to_dict(),
            "tool_audit_hash": self.tool_audit_hash,
        }


class BankingAgentEpisodeV1:
    """Evaluator-owned live banking observation surface for one agent process."""

    def __init__(self, world: BankingRefundWorld) -> None:
        self.world = world
        definitions = tuple(
            ToolDefinitionV1(
                name=name,
                mode="read",
                handler=lambda arguments, tool_name=name: self.world.tool_call(tool_name, arguments),
            )
            for name in tuple(world.agent_view()["tool_manifest"])
        )
        self.gateway = ToolGatewayV1(tools=definitions, read_budget=12, write_budget=0)

    def run(
        self,
        *,
        invocation: AdapterInvocationV1,
        agent_manifest: AgentManifestV1,
    ) -> BankingAgentEpisodeResultV1:
        generation = CandidateGenerationManifestV1(
            benchmark_build_hash=sha256_payload({"module": "ycb100.adaptive_causal.banking_episode.v1"}),
            agent_manifest_hash=agent_manifest.manifest_hash,
            world_snapshot_hash=self.world.snapshot_hash,
            execution_tier="CONTAINMENT_ONLY",
        )
        result = JsonlContainmentRunner().run_episode(
            invocation=invocation,
            agent_manifest=agent_manifest,
            run_manifest=generation,
            episode_start=self.world.agent_view(),
            tool_handler=self.gateway.invoke,
            allowed_tools=self.gateway.allowed_tools,
        )
        if result.status != "COMPLETED" or result.candidate is None:
            raise RuntimeError("banking agent episode failed: " + result.failure_reason)
        candidate = FrozenActionProposalCandidateV1.from_mapping(result.candidate)
        return BankingAgentEpisodeResultV1(
            candidate=candidate,
            adapter_result=result,
            tool_audit_hash=self.gateway.audit_hash,
        )


__all__ = ["BankingAgentEpisodeResultV1", "BankingAgentEpisodeV1"]
