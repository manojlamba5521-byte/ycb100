"""Interactive JSONL adapter runner for public ConsequenceBench development episodes."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    AgentManifestV1,
    CandidateGenerationManifestV1,
    FrozenActionProposalCandidateV1,
    RunManifestV1,
    canonical_json,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.protocol import validate_agent_message
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.containment import (
    filtered_environment,
    local_agent_workspace,
)


ToolHandler = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
_EOF = object()


@dataclass(frozen=True)
class AdapterInvocationV1:
    command: tuple[str, ...]
    timeout_seconds: int = 30
    max_messages: int = 64

    def __post_init__(self) -> None:
        command = tuple(str(item or "").strip() for item in self.command if str(item or "").strip())
        if not command:
            raise ValueError("adapter command is required")
        if int(self.timeout_seconds) < 1 or int(self.timeout_seconds) > 600:
            raise ValueError("adapter timeout_seconds must be between 1 and 600")
        if int(self.max_messages) < 1 or int(self.max_messages) > 2048:
            raise ValueError("adapter max_messages must be between 1 and 2048")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "timeout_seconds", int(self.timeout_seconds))
        object.__setattr__(self, "max_messages", int(self.max_messages))


@dataclass(frozen=True)
class AdapterRunResultV1:
    status: str
    run_manifest_hash: str
    agent_manifest_hash: str
    candidate: Mapping[str, Any] | None
    trace: tuple[Mapping[str, Any], ...]
    failure_reason: str = ""
    stderr_hash: str = ""
    exit_code: int | None = None
    execution_tier: str = "CONTAINMENT_ONLY"
    generation_manifest_hash: str = ""
    schema_version: str = "ycb100.acc.adapter_run_result.v1"

    def __post_init__(self) -> None:
        if self.status not in {"COMPLETED", "FAILED"}:
            raise ValueError("adapter run status is invalid")
        if self.execution_tier != "CONTAINMENT_ONLY":
            raise ValueError("local adapter runner cannot claim OCI or sealed isolation")
        if not self.run_manifest_hash.startswith("sha256:"):
            raise ValueError("run_manifest_hash is required")
        if not self.agent_manifest_hash.startswith("sha256:"):
            raise ValueError("agent_manifest_hash is required")
        if self.generation_manifest_hash and not self.generation_manifest_hash.startswith("sha256:"):
            raise ValueError("generation_manifest_hash is invalid")
        if self.status == "COMPLETED" and self.candidate is None:
            raise ValueError("completed adapter run requires a candidate")

    @property
    def trace_hash(self) -> str:
        return sha256_payload(list(self.trace))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "run_manifest_hash": self.run_manifest_hash,
            "agent_manifest_hash": self.agent_manifest_hash,
            "candidate": dict(self.candidate) if isinstance(self.candidate, Mapping) else None,
            "candidate_hash": (
                str(self.candidate.get("payload_hash") or "")
                if isinstance(self.candidate, Mapping)
                else ""
            ),
            "trace": [dict(item) for item in self.trace],
            "trace_hash": self.trace_hash,
            "failure_reason": self.failure_reason,
            "stderr_hash": self.stderr_hash,
            "exit_code": self.exit_code,
            "execution_tier": self.execution_tier,
            "generation_manifest_hash": self.generation_manifest_hash,
        }


class JsonlContainmentRunner:
    """Run one adapter with typed tool replies and evaluator-owned transcript."""

    def run_episode(
        self,
        *,
        invocation: AdapterInvocationV1,
        agent_manifest: AgentManifestV1,
        run_manifest: RunManifestV1 | CandidateGenerationManifestV1,
        episode_start: Mapping[str, Any],
        tool_handler: ToolHandler,
        allowed_tools: Sequence[str],
        environment: Mapping[str, str] | None = None,
    ) -> AdapterRunResultV1:
        if agent_manifest.execution_tier != "CONTAINMENT_ONLY":
            raise ValueError("local runner only accepts a CONTAINMENT_ONLY agent manifest")
        if run_manifest.execution_tier != "CONTAINMENT_ONLY":
            raise ValueError("local runner only accepts a CONTAINMENT_ONLY run manifest")
        if run_manifest.agent_manifest_hash != agent_manifest.manifest_hash:
            raise ValueError("run manifest is not bound to the supplied agent manifest")
        if not callable(tool_handler):
            raise ValueError("tool_handler is required")
        tool_names = {str(name or "").strip() for name in allowed_tools if str(name or "").strip()}
        if not tool_names:
            raise ValueError("at least one tool must be declared")

        start_payload = {
            "type": "episode.start",
            "episode": dict(episode_start),
            "run_manifest_hash": run_manifest.manifest_hash,
            "candidate_generation": isinstance(run_manifest, CandidateGenerationManifestV1),
            "execution_tier": "CONTAINMENT_ONLY",
        }
        trace: list[dict[str, Any]] = []
        with local_agent_workspace() as workspace:
            process = subprocess.Popen(
                list(invocation.command),
                cwd=workspace,
                env=filtered_environment(
                    allowed_names=agent_manifest.allowed_environment_names,
                    supplied=environment,
                ),
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
            stdout_thread = threading.Thread(
                target=_read_lines,
                args=(process.stdout, stdout_queue),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_collect_stderr,
                args=(process.stderr, stderr_chunks),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            _write_jsonl(process.stdin, start_payload)
            result = self._consume(
                process=process,
                stdout_queue=stdout_queue,
                trace=trace,
                invocation=invocation,
                run_manifest=run_manifest,
                agent_manifest=agent_manifest,
                allowed_tools=tool_names,
                tool_handler=tool_handler,
            )
            _close_process(process)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            stderr_hash = sha256_payload({"stderr": "".join(stderr_chunks)})
            return AdapterRunResultV1(
                status=result["status"],
                run_manifest_hash=str(result.get("run_manifest_hash") or run_manifest.manifest_hash),
                agent_manifest_hash=agent_manifest.manifest_hash,
                candidate=result.get("candidate"),
                trace=tuple(trace),
                failure_reason=str(result.get("failure_reason") or ""),
                stderr_hash=stderr_hash,
                exit_code=process.returncode,
                generation_manifest_hash=(
                    run_manifest.manifest_hash
                    if isinstance(run_manifest, CandidateGenerationManifestV1)
                    else ""
                ),
            )

    def _consume(
        self,
        *,
        process: subprocess.Popen[str],
        stdout_queue: queue.Queue[object],
        trace: list[dict[str, Any]],
        invocation: AdapterInvocationV1,
        run_manifest: RunManifestV1 | CandidateGenerationManifestV1,
        agent_manifest: AgentManifestV1,
        allowed_tools: set[str],
        tool_handler: ToolHandler,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + invocation.timeout_seconds
        last_sequence = -1
        candidate: dict[str, Any] | None = None
        message_count = 0
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                item = stdout_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if process.poll() is not None:
                    return {"status": "FAILED", "failure_reason": "agent_exited_before_finish"}
                continue
            if item is _EOF:
                return {
                    "status": "FAILED",
                    "failure_reason": "agent_eof_before_finish",
                }
            raw = str(item)
            message_count += 1
            if message_count > invocation.max_messages:
                return {"status": "FAILED", "failure_reason": "agent_message_budget_exhausted"}
            try:
                message = json.loads(raw)
                normalized = validate_agent_message(message)
            except Exception as exc:
                return {
                    "status": "FAILED",
                    "failure_reason": "agent_message_invalid:" + type(exc).__name__,
                }
            sequence = int(normalized["sequence"])
            if sequence <= last_sequence:
                return {"status": "FAILED", "failure_reason": "agent_sequence_not_monotonic"}
            last_sequence = sequence
            message_type = str(normalized["type"])
            trace.append(
                {
                    "actor": "agent",
                    "type": message_type,
                    "sequence": sequence,
                    "payload_hash": sha256_payload(normalized),
                }
            )
            if message_type == "tool.call":
                payload = dict(normalized["payload"])
                tool_name = str(payload.get("name") or "").strip()
                arguments = payload.get("arguments")
                if tool_name not in allowed_tools:
                    return {"status": "FAILED", "failure_reason": "undeclared_tool:" + tool_name}
                if not isinstance(arguments, Mapping):
                    return {"status": "FAILED", "failure_reason": "tool_arguments_invalid"}
                try:
                    response = dict(tool_handler(tool_name, dict(arguments)))
                except Exception as exc:
                    return {"status": "FAILED", "failure_reason": "tool_handler_failed:" + type(exc).__name__}
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
                trace.append(
                    {
                        "actor": "evaluator",
                        "type": "tool.result",
                        "request_sequence": sequence,
                        "result_hash": sha256_payload(response),
                    }
                )
            elif message_type == "candidate.submit":
                if candidate is not None:
                    return {"status": "FAILED", "failure_reason": "duplicate_candidate_submission"}
                parsed = FrozenActionProposalCandidateV1.from_mapping(normalized["candidate"])
                if isinstance(run_manifest, RunManifestV1):
                    if parsed.payload_hash != run_manifest.candidate_hash:
                        return {"status": "FAILED", "failure_reason": "candidate_hash_not_bound_to_run"}
                    bound_manifest_hash = run_manifest.manifest_hash
                else:
                    bound_manifest_hash = run_manifest.bind_candidate(parsed.payload_hash).manifest_hash
                candidate = parsed.to_dict()
            elif message_type == "episode.finish":
                if candidate is None:
                    return {"status": "FAILED", "failure_reason": "finish_without_candidate"}
                return {
                    "status": "COMPLETED",
                    "candidate": candidate,
                    "run_manifest_hash": bound_manifest_hash,
                }
        return {"status": "FAILED", "failure_reason": "agent_timeout"}


def _read_lines(stream: Any, output: queue.Queue[object]) -> None:
    try:
        for line in iter(stream.readline, ""):
            output.put(line.rstrip("\r\n"))
    finally:
        output.put(_EOF)


def _collect_stderr(stream: Any, chunks: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            chunks.append(line)
    finally:
        stream.close()


def _write_jsonl(stream: Any, payload: Mapping[str, Any]) -> None:
    stream.write(canonical_json(dict(payload)) + "\n")
    stream.flush()


def _close_process(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None and not process.stdin.closed:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
