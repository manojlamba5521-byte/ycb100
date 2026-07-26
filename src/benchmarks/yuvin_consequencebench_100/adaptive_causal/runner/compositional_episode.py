"""Universal multi-tool JSONL runner for compositional YCB-100 development worlds."""
from __future__ import annotations

import queue
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    AgentManifestV1,
    CandidateGenerationManifestV1,
    canonical_json,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.protocol import validate_agent_message
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.containment import (
    filtered_environment,
    local_agent_workspace,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.jsonl_adapter import (
    AdapterInvocationV1,
    _EOF,
    _close_process,
    _collect_stderr,
    _read_lines,
    _write_jsonl,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.compositional_episode import (
    CompositionalCausalEpisodeV1,
    CompositionalEpisodeEvaluationV1,
    TOOL_NAMES,
)


COMPOSITIONAL_ADAPTER_RUN_SCHEMA_VERSION = "ycb100.acc.compositional_adapter_run.v1"


@dataclass(frozen=True)
class CompositionalAdapterRunV1:
    """A transcript, independent episode result, and agent-owned decision claim."""

    status: str
    run_manifest_hash: str
    agent_manifest_hash: str
    episode_start_hash: str
    decision: Mapping[str, Any] | None
    trace: tuple[Mapping[str, Any], ...]
    evaluation: CompositionalEpisodeEvaluationV1
    failure_reason: str = ""
    stderr_hash: str = ""
    exit_code: int | None = None
    execution_tier: str = "CONTAINMENT_ONLY"
    schema_version: str = COMPOSITIONAL_ADAPTER_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPOSITIONAL_ADAPTER_RUN_SCHEMA_VERSION:
            raise ValueError("compositional adapter run schema version mismatch")
        if self.status not in {"COMPLETED", "FAILED"}:
            raise ValueError("compositional adapter status is invalid")
        if self.execution_tier != "CONTAINMENT_ONLY":
            raise ValueError("local compositional runner cannot claim sealed isolation")
        if not isinstance(self.evaluation, CompositionalEpisodeEvaluationV1):
            raise ValueError("evaluation must be evaluator-owned")
        for field_name in ("run_manifest_hash", "agent_manifest_hash", "episode_start_hash", "stderr_hash"):
            if not str(getattr(self, field_name)).startswith("sha256:"):
                raise ValueError(field_name + " must be a digest")
        if self.status == "COMPLETED" and not isinstance(self.decision, Mapping):
            raise ValueError("completed compositional run requires a decision claim")

    @property
    def trace_hash(self) -> str:
        return sha256_payload(list(self.trace))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "run_manifest_hash": self.run_manifest_hash,
            "agent_manifest_hash": self.agent_manifest_hash,
            "episode_start_hash": self.episode_start_hash,
            "decision": dict(self.decision) if isinstance(self.decision, Mapping) else None,
            "trace": [dict(row) for row in self.trace],
            "trace_hash": self.trace_hash,
            "evaluation": self.evaluation.to_dict(),
            "failure_reason": self.failure_reason,
            "stderr_hash": self.stderr_hash,
            "exit_code": self.exit_code,
            "execution_tier": self.execution_tier,
        }


def run_jsonl_compositional_episode(
    *,
    episode: CompositionalCausalEpisodeV1,
    invocation: AdapterInvocationV1,
    agent_manifest: AgentManifestV1,
    run_manifest: CandidateGenerationManifestV1,
    environment: Mapping[str, str] | None = None,
    agent_start: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
) -> CompositionalAdapterRunV1:
    """Run an untrusted adapter against named, bounded compositional tools.

    Unlike proposal-generation runs, this capability runner binds a submitted
    decision claim and independently scores the actual tool effects.  It is
    still `CONTAINMENT_ONLY`, never a sealed evaluator or product claim.
    """
    if not isinstance(episode, CompositionalCausalEpisodeV1):
        raise ValueError("episode must be a CompositionalCausalEpisodeV1")
    if not isinstance(run_manifest, CandidateGenerationManifestV1):
        raise ValueError("compositional episodes require a pre-candidate run manifest")
    if agent_manifest.execution_tier != "CONTAINMENT_ONLY" or run_manifest.execution_tier != "CONTAINMENT_ONLY":
        raise ValueError("local compositional runner only accepts CONTAINMENT_ONLY manifests")
    if run_manifest.agent_manifest_hash != agent_manifest.manifest_hash:
        raise ValueError("run manifest is not bound to the supplied agent manifest")
    start = dict(agent_start) if agent_start is not None else episode.agent_view()
    permitted_tools = tuple(allowed_tools or TOOL_NAMES)
    if not permitted_tools or any(name not in TOOL_NAMES for name in permitted_tools):
        raise ValueError("compositional allowed_tools are invalid")
    start_hash = sha256_payload(start)
    if run_manifest.world_snapshot_hash != start_hash:
        raise ValueError("run manifest is not bound to the compositional episode view")
    trace: list[dict[str, Any]] = []
    decision: dict[str, Any] | None = None
    result: dict[str, Any]
    with local_agent_workspace() as workspace:
        process = subprocess.Popen(
            list(invocation.command),
            cwd=workspace,
            env=filtered_environment(allowed_names=agent_manifest.allowed_environment_names, supplied=environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_queue: queue.Queue[object] = queue.Queue()
        stderr_chunks: list[str] = []
        stdout_thread = threading.Thread(target=_read_lines, args=(process.stdout, stdout_queue), daemon=True)
        stderr_thread = threading.Thread(target=_collect_stderr, args=(process.stderr, stderr_chunks), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        _write_jsonl(
            process.stdin,
            {
                "type": "episode.start",
                "episode": start,
                "run_manifest_hash": run_manifest.manifest_hash,
                "execution_tier": "CONTAINMENT_ONLY",
            },
        )
        result, decision = _consume(
            process=process,
            stdout_queue=stdout_queue,
            invocation=invocation,
            run_manifest=run_manifest,
            episode=episode,
            trace=trace,
            allowed_tools=frozenset(permitted_tools),
        )
        _close_process(process)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        stderr_hash = sha256_payload({"stderr": "".join(stderr_chunks)})
        return CompositionalAdapterRunV1(
            status=result["status"],
            run_manifest_hash=run_manifest.manifest_hash,
            agent_manifest_hash=agent_manifest.manifest_hash,
            episode_start_hash=start_hash,
            decision=decision,
            trace=tuple(trace),
            evaluation=episode.evaluate(),
            failure_reason=str(result.get("failure_reason") or ""),
            stderr_hash=stderr_hash,
            exit_code=process.returncode,
        )


def _consume(
    *,
    process: subprocess.Popen[str],
    stdout_queue: queue.Queue[object],
    invocation: AdapterInvocationV1,
    run_manifest: CandidateGenerationManifestV1,
    episode: CompositionalCausalEpisodeV1,
    trace: list[dict[str, Any]],
    allowed_tools: frozenset[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    deadline = time.monotonic() + invocation.timeout_seconds
    last_sequence = -1
    message_count = 0
    decision: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            item = stdout_queue.get(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            if process.poll() is not None:
                return {"status": "FAILED", "failure_reason": "agent_exited_before_finish"}, decision
            continue
        if item is _EOF:
            return {"status": "FAILED", "failure_reason": "agent_eof_before_finish"}, decision
        message_count += 1
        if message_count > invocation.max_messages:
            return {"status": "FAILED", "failure_reason": "agent_message_budget_exhausted"}, decision
        try:
            normalized = validate_agent_message(json.loads(str(item)))
        except Exception as exc:
            return {"status": "FAILED", "failure_reason": "agent_message_invalid:" + type(exc).__name__}, decision
        sequence = int(normalized["sequence"])
        if sequence <= last_sequence:
            return {"status": "FAILED", "failure_reason": "agent_sequence_not_monotonic"}, decision
        last_sequence = sequence
        message_type = str(normalized["type"])
        trace.append({"actor": "agent", "type": message_type, "sequence": sequence, "payload_hash": sha256_payload(normalized)})
        if message_type == "tool.call":
            payload = dict(normalized["payload"])
            name = str(payload.get("name") or "").strip()
            arguments = payload.get("arguments")
            if name not in allowed_tools:
                return {"status": "FAILED", "failure_reason": "undeclared_tool:" + name}, decision
            if not isinstance(arguments, Mapping) or "tool" in arguments:
                return {"status": "FAILED", "failure_reason": "tool_arguments_invalid"}, decision
            try:
                response = episode.perform({"tool": name, **dict(arguments)})
            except Exception as exc:
                return {"status": "FAILED", "failure_reason": "tool_handler_failed:" + type(exc).__name__}, decision
            _write_jsonl(
                process.stdin,
                {
                    "type": "tool.result",
                    "request_sequence": sequence,
                    "result": response,
                    "result_hash": sha256_payload(response),
                    "run_manifest_hash": run_manifest.manifest_hash,
                },
            )
            trace.append({"actor": "evaluator", "type": "tool.result", "request_sequence": sequence, "result_hash": sha256_payload(response)})
        elif message_type == "decision.submit":
            if decision is not None:
                return {"status": "FAILED", "failure_reason": "duplicate_decision_submission"}, decision
            decision = dict(normalized["payload"])
        elif message_type == "candidate.submit":
            return {"status": "FAILED", "failure_reason": "candidate_submission_not_allowed"}, decision
        elif message_type == "episode.finish":
            if decision is None:
                return {"status": "FAILED", "failure_reason": "finish_without_decision"}, decision
            return {"status": "COMPLETED"}, decision
    return {"status": "FAILED", "failure_reason": "agent_timeout"}, decision


__all__ = [
    "COMPOSITIONAL_ADAPTER_RUN_SCHEMA_VERSION",
    "CompositionalAdapterRunV1",
    "run_jsonl_compositional_episode",
]
