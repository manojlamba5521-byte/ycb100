"""Restart-capable JSONL runner for interactive consequence lifecycles.

This is a containment-only local runner. It uses an empty temporary working
directory and a strict environment allowlist, but it does not claim an OS
sandbox, a microVM, sealed evaluator custody, or protection from hostile code.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.contracts import (
    canonical_json,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.environment import (
    ConsequenceLifecycleEnvironment,
    LifecycleToolOutcome,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.containment import (
    BASE_ENVIRONMENT_NAMES,
    filtered_environment,
)


LIFECYCLE_JSONL_RUN_SCHEMA_VERSION = "ycb100.lifecycle.jsonl_run.v1"
_EOF = object()


@dataclass(frozen=True)
class LifecycleJsonlInvocationV1:
    command: tuple[str, ...]
    timeout_seconds: int = 60
    max_messages: int = 256
    max_line_bytes: int = 65_536
    max_restarts: int = 4
    allowed_environment_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        command = tuple(
            str(item or "").strip()
            for item in self.command
            if str(item or "").strip()
        )
        if not command:
            raise ValueError("lifecycle candidate command is required")
        if not 1 <= int(self.timeout_seconds) <= 900:
            raise ValueError("timeout_seconds must be between 1 and 900")
        if not 1 <= int(self.max_messages) <= 4096:
            raise ValueError("max_messages must be between 1 and 4096")
        if not 256 <= int(self.max_line_bytes) <= 1_048_576:
            raise ValueError("max_line_bytes must be between 256 and 1048576")
        if not 0 <= int(self.max_restarts) <= 32:
            raise ValueError("max_restarts must be between 0 and 32")
        allowed = tuple(sorted({str(item).strip() for item in self.allowed_environment_names if str(item).strip()}))
        if any("=" in item or "\x00" in item for item in allowed):
            raise ValueError("allowed environment name is invalid")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "timeout_seconds", int(self.timeout_seconds))
        object.__setattr__(self, "max_messages", int(self.max_messages))
        object.__setattr__(self, "max_line_bytes", int(self.max_line_bytes))
        object.__setattr__(self, "max_restarts", int(self.max_restarts))
        object.__setattr__(self, "allowed_environment_names", allowed)


@dataclass(frozen=True)
class LifecycleJsonlRunResultV1:
    status: str
    final_result: Mapping[str, Any] | None
    runner_trace: tuple[Mapping[str, Any], ...]
    environment_trace_hash: str
    process_generations: tuple[Mapping[str, Any], ...]
    failure_reason: str = ""
    execution_tier: str = "CONTAINMENT_ONLY"
    isolation_claim: str = "NOT_OS_SANDBOXED"
    schema_version: str = LIFECYCLE_JSONL_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in {"COMPLETED", "FAILED"}:
            raise ValueError("lifecycle run status is invalid")
        if self.execution_tier != "CONTAINMENT_ONLY":
            raise ValueError("local lifecycle runner cannot claim stronger isolation")
        if self.isolation_claim != "NOT_OS_SANDBOXED":
            raise ValueError("local lifecycle runner must disclose its isolation limit")
        if self.status == "COMPLETED" and self.final_result is None:
            raise ValueError("completed lifecycle run requires a final result")

    @property
    def runner_trace_hash(self) -> str:
        return sha256_payload([dict(item) for item in self.runner_trace])

    @property
    def complete_trace_hash(self) -> str:
        return sha256_payload(
            {
                "runner_trace_hash": self.runner_trace_hash,
                "environment_trace_hash": self.environment_trace_hash,
                "final_result_hash": (
                    sha256_payload(dict(self.final_result))
                    if isinstance(self.final_result, Mapping)
                    else ""
                ),
                "process_generations": [dict(item) for item in self.process_generations],
                "failure_reason": self.failure_reason,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "final_result": (
                dict(self.final_result)
                if isinstance(self.final_result, Mapping)
                else None
            ),
            "runner_trace": [dict(item) for item in self.runner_trace],
            "runner_trace_hash": self.runner_trace_hash,
            "environment_trace_hash": self.environment_trace_hash,
            "complete_trace_hash": self.complete_trace_hash,
            "process_generations": [dict(item) for item in self.process_generations],
            "failure_reason": self.failure_reason,
            "execution_tier": self.execution_tier,
            "isolation_claim": self.isolation_claim,
        }


@dataclass
class _CandidateProcess:
    process: subprocess.Popen[str]
    output: queue.Queue[object]
    stdout_thread: threading.Thread
    stderr_thread: threading.Thread
    stderr_chunks: list[str]
    generation: int


class LifecycleJsonlRunner:
    """Run, kill, and restart one JSONL candidate against a durable environment."""

    def run_episode(
        self,
        *,
        invocation: LifecycleJsonlInvocationV1,
        environment: ConsequenceLifecycleEnvironment,
        supplied_environment: Mapping[str, str] | None = None,
    ) -> LifecycleJsonlRunResultV1:
        if not isinstance(environment, ConsequenceLifecycleEnvironment):
            raise ValueError("environment must be a ConsequenceLifecycleEnvironment")
        deadline = time.monotonic() + invocation.timeout_seconds
        trace: list[dict[str, Any]] = []
        process_runs: list[dict[str, Any]] = []
        message_count = 0
        restart_count = 0
        last_sequence = 0
        final_result: dict[str, Any] | None = None
        failure_reason = ""
        with tempfile.TemporaryDirectory(prefix="ycb100-lifecycle-runner-") as root:
            root_path = Path(root)
            candidate = self._start_candidate(
                invocation=invocation,
                environment=environment,
                supplied_environment=supplied_environment,
                root=root_path,
                generation=0,
                restarting=False,
                trace=trace,
            )
            while time.monotonic() < deadline:
                item = self._next_line(candidate, deadline)
                if item is _EOF:
                    failure_reason = "candidate_eof_before_episode_finish"
                    break
                if isinstance(item, _LineTooLong):
                    failure_reason = "candidate_line_budget_exhausted"
                    break
                if item is None:
                    failure_reason = (
                        "candidate_timeout"
                        if candidate.process.poll() is None
                        else "candidate_exited_before_episode_finish"
                    )
                    break
                raw = str(item)
                message_count += 1
                if message_count > invocation.max_messages:
                    failure_reason = "candidate_message_budget_exhausted"
                    break
                try:
                    message = self._parse_message(raw)
                except ValueError as exc:
                    failure_reason = "candidate_message_invalid:" + str(exc)
                    break
                sequence = int(message["sequence"])
                if sequence <= last_sequence:
                    failure_reason = "candidate_sequence_not_monotonic"
                    break
                last_sequence = sequence
                trace.append(
                    {
                        "actor": "candidate",
                        "type": "tool.call",
                        "generation": candidate.generation,
                        "sequence": sequence,
                        "line_hash": sha256_payload({"line": raw}),
                        "line_bytes": len(raw.encode("utf-8")),
                        "tool": message["name"],
                        "arguments_hash": sha256_payload(message["arguments"]),
                    }
                )
                try:
                    outcome = environment.handle_tool(
                        str(message["name"]),
                        dict(message["arguments"]),
                    )
                except Exception as exc:
                    error = {
                        "type": "tool.result",
                        "request_sequence": sequence,
                        "ok": False,
                        "error": type(exc).__name__,
                        "error_hash": sha256_payload(
                            {"type": type(exc).__name__, "message": str(exc)}
                        ),
                        "session_id": environment.session_id,
                    }
                    self._write(candidate.process, error)
                    trace.append(
                        {
                            "actor": "evaluator",
                            "type": "tool.error",
                            "generation": candidate.generation,
                            "request_sequence": sequence,
                            "error": type(exc).__name__,
                            "error_hash": error["error_hash"],
                        }
                    )
                    continue
                if outcome.terminate_candidate:
                    trace.append(
                        {
                            "actor": "evaluator",
                            "type": "candidate.process_killed",
                            "generation": candidate.generation,
                            "request_sequence": sequence,
                            "response_lost": outcome.response_lost,
                            "reason_hash": sha256_payload(
                                {"reason": outcome.termination_reason}
                            ),
                        }
                    )
                    process_runs.append(
                        self._stop_candidate(candidate, killed=True)
                    )
                    if restart_count >= min(
                        invocation.max_restarts,
                        environment.blueprint.budget.restart_limit,
                    ):
                        failure_reason = "candidate_restart_budget_exhausted"
                        candidate = None
                        break
                    restart_count += 1
                    last_sequence = 0
                    environment.record_process_restart(
                        reason=outcome.termination_reason
                    )
                    candidate = self._start_candidate(
                        invocation=invocation,
                        environment=environment,
                        supplied_environment=supplied_environment,
                        root=root_path,
                        generation=restart_count,
                        restarting=True,
                        trace=trace,
                    )
                    continue
                result = dict(outcome.result or {})
                response = {
                    "type": "tool.result",
                    "request_sequence": sequence,
                    "ok": True,
                    "result": result,
                    "result_hash": sha256_payload(result),
                    "session_id": environment.session_id,
                }
                self._write(candidate.process, response)
                trace.append(
                    {
                        "actor": "evaluator",
                        "type": "tool.result",
                        "generation": candidate.generation,
                        "request_sequence": sequence,
                        "result_hash": response["result_hash"],
                    }
                )
                if message["name"] == "episode.finish":
                    final_result = result
                    break
            if candidate is not None:
                process_runs.append(self._stop_candidate(candidate, killed=False))

        status = "COMPLETED" if final_result is not None and not failure_reason else "FAILED"
        return LifecycleJsonlRunResultV1(
            status=status,
            final_result=final_result,
            runner_trace=tuple(trace),
            environment_trace_hash=environment.trace_hash,
            process_generations=tuple(process_runs),
            failure_reason=failure_reason,
        )

    def _start_candidate(
        self,
        *,
        invocation: LifecycleJsonlInvocationV1,
        environment: ConsequenceLifecycleEnvironment,
        supplied_environment: Mapping[str, str] | None,
        root: Path,
        generation: int,
        restarting: bool,
        trace: list[dict[str, Any]],
    ) -> _CandidateProcess:
        workspace = root / ("candidate-" + str(generation))
        workspace.mkdir(parents=False, exist_ok=False)
        workspace_initialized_empty = not any(workspace.iterdir())
        process_environment = self._strict_environment(
            invocation.allowed_environment_names,
            supplied_environment,
        )
        process = subprocess.Popen(
            list(invocation.command),
            cwd=workspace,
            env=process_environment,
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
        output: queue.Queue[object] = queue.Queue()
        stderr_chunks: list[str] = []
        stdout_thread = threading.Thread(
            target=_read_bounded_lines,
            args=(process.stdout, output, invocation.max_line_bytes),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_collect_stderr,
            args=(process.stderr, stderr_chunks, invocation.max_line_bytes * 4),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        if restarting:
            start_payload = {
                "type": "session.restart",
                "schema_version": "ycb100.lifecycle.session_restart.v1",
                "session_id": environment.session_id,
                "restart_count": generation,
                "checkpoint_available": environment.checkpoint_path.exists(),
                "execution_tier": "CONTAINMENT_ONLY",
                "transcript_replayed": False,
            }
        else:
            start_payload = {
                "type": "episode.start",
                "schema_version": "ycb100.lifecycle.episode_start.v1",
                "episode": environment.initial_agent_view,
                "session_id": environment.session_id,
                "execution_tier": "CONTAINMENT_ONLY",
            }
        self._write(process, start_payload)
        trace.append(
            {
                "actor": "evaluator",
                "type": "candidate.process_started",
                "generation": generation,
                "restart": restarting,
                "start_payload_hash": sha256_payload(start_payload),
                "empty_workspace_at_launch": workspace_initialized_empty,
                "transcript_replayed": False if restarting else None,
            }
        )
        return _CandidateProcess(
            process=process,
            output=output,
            stdout_thread=stdout_thread,
            stderr_thread=stderr_thread,
            stderr_chunks=stderr_chunks,
            generation=generation,
        )

    @staticmethod
    def _strict_environment(
        allowed_names: tuple[str, ...],
        supplied: Mapping[str, str] | None,
    ) -> dict[str, str]:
        source: dict[str, str] = {
            name: str(os.environ[name])
            for name in BASE_ENVIRONMENT_NAMES
            if str(os.environ.get(name) or "")
        }
        provided = supplied or {}
        for name in allowed_names:
            if name in provided:
                source[name] = str(provided[name])
        return filtered_environment(
            allowed_names=allowed_names,
            supplied=source,
        )

    @staticmethod
    def _parse_message(raw: str) -> dict[str, Any]:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_json") from exc
        if not isinstance(message, dict):
            raise ValueError("message_not_object")
        if message.get("type") != "tool.call":
            raise ValueError("unsupported_message_type")
        if set(message) != {"type", "sequence", "name", "arguments"}:
            raise ValueError("message_schema_mismatch")
        sequence = message["sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ValueError("sequence_invalid")
        name = message["name"]
        arguments = message["arguments"]
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise ValueError("tool_call_invalid")
        return {
            "type": "tool.call",
            "sequence": sequence,
            "name": name,
            "arguments": arguments,
        }

    @staticmethod
    def _write(process: subprocess.Popen[str], payload: Mapping[str, Any]) -> None:
        if process.stdin is None or process.stdin.closed:
            raise RuntimeError("candidate stdin is closed")
        process.stdin.write(canonical_json(dict(payload)) + "\n")
        process.stdin.flush()

    @staticmethod
    def _next_line(candidate: _CandidateProcess, deadline: float) -> object | None:
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                return candidate.output.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if candidate.process.poll() is not None:
                    return None
        return None

    @staticmethod
    def _stop_candidate(
        candidate: _CandidateProcess,
        *,
        killed: bool,
    ) -> dict[str, Any]:
        process = candidate.process
        if killed and process.poll() is None:
            process.kill()
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
            killed = True
        candidate.stdout_thread.join(timeout=1)
        candidate.stderr_thread.join(timeout=1)
        stderr = "".join(candidate.stderr_chunks)
        return {
            "generation": candidate.generation,
            "killed_by_evaluator": bool(killed),
            "exit_code": process.returncode,
            "stderr_hash": sha256_payload({"stderr": stderr}),
            "stderr_bytes": len(stderr.encode("utf-8")),
        }


@dataclass(frozen=True)
class _LineTooLong:
    observed_bytes: int


def _read_bounded_lines(
    stream: Any,
    output: queue.Queue[object],
    maximum_bytes: int,
) -> None:
    try:
        while True:
            line = stream.readline(maximum_bytes + 2)
            if line == "":
                break
            encoded_size = len(line.encode("utf-8"))
            if encoded_size > maximum_bytes:
                output.put(_LineTooLong(encoded_size))
                break
            output.put(line.rstrip("\r\n"))
    finally:
        output.put(_EOF)


def _collect_stderr(stream: Any, chunks: list[str], maximum_bytes: int) -> None:
    consumed = 0
    try:
        while consumed < maximum_bytes:
            chunk = stream.read(min(4096, maximum_bytes - consumed))
            if not chunk:
                break
            chunks.append(chunk)
            consumed += len(chunk.encode("utf-8"))
    finally:
        stream.close()


def run_lifecycle_jsonl_episode(
    *,
    invocation: LifecycleJsonlInvocationV1,
    environment: ConsequenceLifecycleEnvironment,
    supplied_environment: Mapping[str, str] | None = None,
) -> LifecycleJsonlRunResultV1:
    return LifecycleJsonlRunner().run_episode(
        invocation=invocation,
        environment=environment,
        supplied_environment=supplied_environment,
    )


__all__ = [
    "LIFECYCLE_JSONL_RUN_SCHEMA_VERSION",
    "LifecycleJsonlInvocationV1",
    "LifecycleJsonlRunResultV1",
    "LifecycleJsonlRunner",
    "run_lifecycle_jsonl_episode",
]
