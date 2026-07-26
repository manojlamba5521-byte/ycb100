"""Run Gemini through the contained ConsequenceBench JSONL agent protocol.

This program is executed from a temporary evaluator-owned working directory.
It reads Vertex credentials only from its filtered process environment and
never writes credential values or raw model responses to stdout or stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.agents.vertex_gemini_jsonl import (
    VERTEX_GEMINI_AGENT_SYSTEM_PROMPT,
    VERTEX_GEMINI_FEEDBACK_SYSTEM_PROMPT,
    execute_vertex_gemini_episode,
)


class VertexGeminiStructuredClient:
    """Small adapter over the optional official Google Gen AI SDK."""

    def __init__(self, *, project: str, location: str) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "Vertex support requires: python -m pip install 'ycb100[vertex]'"
            ) from exc
        self._types = types
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=types.HttpOptions(api_version="v1"),
        )

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        format: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        system_parts = [
            item["content"] for item in messages if item.get("role") == "system"
        ]
        conversation = "\n\n".join(
            f"{item.get('role', 'user').upper()}:\n{item.get('content', '')}"
            for item in messages
            if item.get("role") != "system"
        )
        temperature = float((options or {}).get("temperature", 0.0))
        config = self._types.GenerateContentConfig(
            system_instruction="\n\n".join(system_parts),
            temperature=temperature,
            response_mime_type="application/json",
            response_json_schema=dict(format or {}),
        )
        response = self._client.models.generate_content(
            model=model,
            contents=conversation,
            config=config,
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, Mapping):
            return dict(parsed)
        text = str(getattr(response, "text", "") or "")
        payload = json.loads(text)
        if not isinstance(payload, Mapping):
            raise ValueError("vertex_structured_response_not_object")
        return dict(payload)


def _read_message() -> Mapping[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise EOFError("vertex_agent_input_eof")
    payload = json.loads(line)
    if not isinstance(payload, Mapping):
        raise ValueError("vertex_agent_input_not_object")
    return payload


def _emit(message: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(dict(message), sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Contained Vertex Gemini ConsequenceBench JSONL agent")
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-investigations", type=int, default=5)
    parser.add_argument("--retry-count", type=int, default=1)
    parser.add_argument("--feedback-aware", action="store_true")
    parser.add_argument(
        "--project",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        help="Vertex project; defaults to GOOGLE_CLOUD_PROJECT.",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        help="Vertex location; defaults to GOOGLE_CLOUD_LOCATION or global.",
    )
    args = parser.parse_args(argv)
    try:
        if not args.project:
            raise ValueError("vertex_project_required")
        execute_vertex_gemini_episode(
            start_message=_read_message(),
            client=VertexGeminiStructuredClient(
                project=args.project,
                location=args.location,
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
        # The evaluator hashes stderr.  Do not disclose private model or auth details.
        print("vertex_gemini_jsonl_agent_failed:" + type(exc).__name__, file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
