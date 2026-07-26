"""Run Codex CLI through the contained ConsequenceBench JSONL agent protocol."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.agents.codex_cli_jsonl import (
    CODEX_CLI_PACKAGE,
    CODEX_CLI_SYSTEM_PROMPT,
    CodexCliConfigV1,
    execute_codex_cli_episode,
)


def _read_message() -> Mapping[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise EOFError("codex_agent_input_eof")
    payload = json.loads(line)
    if not isinstance(payload, Mapping):
        raise ValueError("codex_agent_input_not_object")
    return payload


def _emit(message: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(dict(message), sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Contained Codex CLI ConsequenceBench JSONL agent")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="xhigh")
    parser.add_argument("--codex-package", default=CODEX_CLI_PACKAGE)
    parser.add_argument("--codex-executable", default="npx.cmd")
    parser.add_argument("--model-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-investigations", type=int, default=5)
    parser.add_argument("--retry-count", type=int, default=0)
    parser.add_argument("--feedback-aware", action="store_true")
    args = parser.parse_args(argv)
    try:
        execute_codex_cli_episode(
            start_message=_read_message(),
            config=CodexCliConfigV1(
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                codex_package=args.codex_package,
                executable=args.codex_executable,
                timeout_seconds=args.model_timeout_seconds,
            ),
            maximum_investigations=args.max_investigations,
            retry_count=max(0, args.retry_count),
            emit=_emit,
            receive=_read_message,
            system_prompt=CODEX_CLI_SYSTEM_PROMPT,
        )
        return 0
    except Exception as exc:
        print("codex_cli_jsonl_agent_failed:" + type(exc).__name__, file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
