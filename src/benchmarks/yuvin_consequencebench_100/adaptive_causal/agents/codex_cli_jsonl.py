"""Codex CLI bridge for the contained public ConsequenceBench JSONL agent protocol.

The bridge treats Codex as an external candidate process.  It receives only
the evaluator-provided public episode view, asks Codex for schema-constrained
read-tool selections and a final decision, and forwards every read through the
existing JSONL membrane.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.agents.vertex_gemini_jsonl import (
    READ_ONLY_TOOLS,
    VERTEX_GEMINI_FEEDBACK_SYSTEM_PROMPT,
    execute_vertex_gemini_episode,
    vertex_decision_schema,
    vertex_investigation_schema,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload


CODEX_CLI_PACKAGE = "@openai/codex@0.145.0"
CODEX_CLI_SYSTEM_PROMPT = (
    VERTEX_GEMINI_FEEDBACK_SYSTEM_PROMPT
    + "\n\nYou are being evaluated as a contained candidate. Use only the JSON "
    "episode and the read-only tool results returned by the evaluator. Do not "
    "inspect local files, repository contents, environment variables, prior "
    "receipts, network resources, or benchmark implementation code. Return "
    "only the JSON object required by the supplied schema."
)


@dataclass(frozen=True)
class CodexCliConfigV1:
    model: str = "gpt-5.5"
    reasoning_effort: str = "xhigh"
    codex_package: str = CODEX_CLI_PACKAGE
    executable: str = "npx.cmd"
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not self.model or not self.reasoning_effort or not self.codex_package or not self.executable:
            raise ValueError("codex CLI config is incomplete")
        if self.reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("codex reasoning effort is unsupported")
        if self.timeout_seconds < 10 or self.timeout_seconds > 600:
            raise ValueError("codex timeout must be between 10 and 600 seconds")


CodexJsonRunner = Callable[[str, Mapping[str, Any], str], Mapping[str, Any]]


class CodexCliStructuredChatClient:
    """StructuredChatClient-compatible wrapper around `codex exec`."""

    def __init__(
        self,
        *,
        config: CodexCliConfigV1,
        retry_count: int = 0,
        codex_json_runner: CodexJsonRunner | None = None,
    ) -> None:
        self.config = config
        self.retry_count = max(0, retry_count)
        self._runner = codex_json_runner

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        format: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if model != self.config.model:
            raise ValueError("codex model binding mismatch")
        if not isinstance(format, Mapping):
            raise ValueError("codex output schema missing")
        prompt = _messages_to_prompt(messages=messages, options=dict(options or {}))
        if self._runner is not None:
            return dict(self._runner(prompt, dict(format), "structured_chat"))
        return _run_codex_cli_json(
            prompt=prompt,
            schema=dict(format),
            phase="structured_chat",
            config=self.config,
            retry_count=self.retry_count,
        )


def execute_codex_cli_episode(
    *,
    start_message: Mapping[str, Any],
    config: CodexCliConfigV1,
    maximum_investigations: int,
    retry_count: int,
    emit: Callable[[Mapping[str, Any]], None],
    receive: Callable[[], Mapping[str, Any]],
    system_prompt: str = CODEX_CLI_SYSTEM_PROMPT,
    codex_json_runner: CodexJsonRunner | None = None,
) -> None:
    """Drive one JSONL episode through isolated Codex CLI invocations."""
    execute_vertex_gemini_episode(
        start_message=start_message,
        client=CodexCliStructuredChatClient(
            config=config,
            retry_count=retry_count,
            codex_json_runner=codex_json_runner,
        ),
        model=config.model,
        maximum_investigations=maximum_investigations,
        retry_count=0,
        emit=emit,
        receive=receive,
        system_prompt=system_prompt,
    )


def _messages_to_prompt(*, messages: list[dict[str, str]], options: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "protocol": "ycb100.codex_cli.structured_chat.v1",
            "instructions": "Return only one JSON object matching the supplied output schema.",
            "messages": messages,
            "options": options,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _run_codex_cli_json(
    *,
    prompt: str,
    schema: Mapping[str, Any],
    phase: str,
    config: CodexCliConfigV1,
    retry_count: int,
) -> Mapping[str, Any]:
    last_error: Exception | None = None
    for _ in range(max(1, retry_count + 1)):
        try:
            return _run_codex_cli_json_once(
                prompt=prompt,
                schema=schema,
                phase=phase,
                config=config,
            )
        except Exception as exc:
            last_error = exc
    raise RuntimeError("codex_cli_unavailable:" + type(last_error).__name__) from last_error


def _run_codex_cli_json_once(
    *,
    prompt: str,
    schema: Mapping[str, Any],
    phase: str,
    config: CodexCliConfigV1,
) -> Mapping[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ycb100-codex-cli-") as directory:
        workdir = Path(directory)
        schema_path = workdir / "output_schema.json"
        output_path = workdir / "last_message.json"
        schema_path.write_text(json.dumps(dict(schema), sort_keys=True), encoding="utf-8")
        command = [
            config.executable,
            "--yes",
            config.codex_package,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ignore-rules",
            "--ignore-user-config",
            "--json",
            "-m",
            config.model,
            "-c",
            'model_reasoning_effort="' + config.reasoning_effort + '"',
            "--cd",
            str(workdir),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        completed = subprocess.run(
            command,
            input=prompt,
            cwd=workdir,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=config.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0 or not output_path.exists():
            diagnostic_hash = sha256_payload(
                {
                    "phase": phase,
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
            raise RuntimeError("codex_cli_failed:" + diagnostic_hash)
        _validate_codex_json_events(completed.stdout)
        payload = _parse_json_object(output_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("codex_cli_output_not_object")
        return dict(payload)


def _parse_json_object(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, Mapping):
        raise ValueError("codex_cli_json_not_object")
    return payload


def _validate_codex_json_events(stdout: str) -> None:
    """Reject Codex executions that used any non-message tool/event item."""
    allowed_top_level = {"thread.started", "turn.started", "turn.completed", "item.completed"}
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            raise ValueError("codex_json_event_not_object")
        event_type = str(event.get("type") or "")
        if event_type not in allowed_top_level:
            raise ValueError("codex_json_event_unsupported:" + event_type)
        if event_type.startswith("item."):
            item = event.get("item")
            if not isinstance(item, Mapping):
                raise ValueError("codex_json_item_missing")
            item_type = str(item.get("type") or "")
            if item_type != "agent_message":
                raise ValueError("codex_tool_invocation_detected:" + item_type)


__all__ = [
    "CODEX_CLI_PACKAGE",
    "CODEX_CLI_SYSTEM_PROMPT",
    "CodexCliConfigV1",
    "CodexCliStructuredChatClient",
    "execute_codex_cli_episode",
]
