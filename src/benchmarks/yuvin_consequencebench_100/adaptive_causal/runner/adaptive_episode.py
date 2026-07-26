"""Bind an arbitrary JSONL adapter to a YCB-100 adaptive public-development world."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    AgentManifestV1,
    CandidateGenerationManifestV1,
    RunManifestV1,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.jsonl_adapter import (
    AdapterInvocationV1,
    AdapterRunResultV1,
    JsonlContainmentRunner,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.adaptive_episode import (
    AdaptiveCausalEpisodeV1,
    AdaptiveEpisodeEvaluationV1,
)


ADAPTIVE_RUN_SCHEMA_VERSION = "ycb100.acc.adaptive_adapter_run.v1"


@dataclass(frozen=True)
class AdaptiveAdapterRunV1:
    """One agent transcript and its evaluator-owned adaptive-world measurement."""

    adapter_result: AdapterRunResultV1
    evaluation: AdaptiveEpisodeEvaluationV1
    episode_start_hash: str
    schema_version: str = ADAPTIVE_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ADAPTIVE_RUN_SCHEMA_VERSION:
            raise ValueError("adaptive adapter run schema version mismatch")
        if not isinstance(self.adapter_result, AdapterRunResultV1):
            raise ValueError("adapter_result must use AdapterRunResultV1")
        if not isinstance(self.evaluation, AdaptiveEpisodeEvaluationV1):
            raise ValueError("evaluation must use AdaptiveEpisodeEvaluationV1")
        if not str(self.episode_start_hash).startswith("sha256:"):
            raise ValueError("episode_start_hash must be a sha256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "adapter_result": self.adapter_result.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "episode_start_hash": self.episode_start_hash,
            "report_hash": self.report_hash,
        }

    @property
    def report_hash(self) -> str:
        return sha256_payload(
            {
                "schema_version": self.schema_version,
                "adapter_result": self.adapter_result.to_dict(),
                "evaluation": self.evaluation.to_dict(),
                "episode_start_hash": self.episode_start_hash,
            }
        )


def run_jsonl_adaptive_episode(
    *,
    episode: AdaptiveCausalEpisodeV1,
    invocation: AdapterInvocationV1,
    agent_manifest: AgentManifestV1,
    run_manifest: RunManifestV1 | CandidateGenerationManifestV1,
    environment: Mapping[str, str] | None = None,
) -> AdaptiveAdapterRunV1:
    """Run an untrusted adapter through exactly one declared adaptive tool.

    This is a local `CONTAINMENT_ONLY` development integration. It does not
    imply microVM isolation, private-corpus custody, Yuvin conformance, or an
    empirical agent result.
    """
    if not isinstance(episode, AdaptiveCausalEpisodeV1):
        raise ValueError("episode must use AdaptiveCausalEpisodeV1")
    start = episode.agent_view()
    result = JsonlContainmentRunner().run_episode(
        invocation=invocation,
        agent_manifest=agent_manifest,
        run_manifest=run_manifest,
        episode_start=start,
        tool_handler=lambda name, arguments: _adaptive_tool_handler(episode, name, arguments),
        allowed_tools=("adaptive.perform",),
        environment=environment,
    )
    return AdaptiveAdapterRunV1(
        adapter_result=result,
        evaluation=episode.evaluate(),
        episode_start_hash=sha256_payload(start),
    )


def _adaptive_tool_handler(
    episode: AdaptiveCausalEpisodeV1,
    name: str,
    arguments: Mapping[str, Any],
) -> Mapping[str, Any]:
    if name != "adaptive.perform":
        raise ValueError("undeclared adaptive tool")
    return episode.perform(arguments)


__all__ = ["ADAPTIVE_RUN_SCHEMA_VERSION", "AdaptiveAdapterRunV1", "run_jsonl_adaptive_episode"]
