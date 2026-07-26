"""Run a local Ollama model through the contained YCB-100 JSONL protocol."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.agents.ollama_jsonl import (
    OllamaStructuredChatClient,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.agents.vertex_gemini_jsonl import (
    VERTEX_GEMINI_AGENT_SYSTEM_PROMPT,
    VERTEX_GEMINI_FEEDBACK_SYSTEM_PROMPT,
    execute_vertex_gemini_episode,
)


def _read_message() -> Mapping[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise EOFError("ollama_agent_input_eof")
    payload = json.loads(line)
    if not isinstance(payload, Mapping):
        raise ValueError("ollama_agent_input_not_object")
    return payload


def _emit(message: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(dict(message), sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Contained Ollama YCB-100 JSONL agent")
    parser.add_argument("--model", default="qwen3.6:35b")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--max-investigations", type=int, default=16)
    parser.add_argument("--retry-count", type=int, default=1)
    parser.add_argument("--context-tokens", type=int, default=131_072)
    parser.add_argument("--feedback-aware", action="store_true")
    args = parser.parse_args(argv)
    try:
        execute_vertex_gemini_episode(
            start_message=_read_message(),
            client=OllamaStructuredChatClient(
                timeout_seconds=args.timeout_seconds,
                context_tokens=args.context_tokens,
            ),
            model=args.model,
            maximum_investigations=args.max_investigations,
            retry_count=max(0, args.retry_count),
            emit=_emit,
            receive=_read_message,
            system_prompt=(
                VERTEX_GEMINI_FEEDBACK_SYSTEM_PROMPT
                if args.feedback_aware
                else VERTEX_GEMINI_AGENT_SYSTEM_PROMPT
            ),
        )
        return 0
    except Exception as exc:
        print("ollama_jsonl_agent_failed:" + type(exc).__name__, file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
