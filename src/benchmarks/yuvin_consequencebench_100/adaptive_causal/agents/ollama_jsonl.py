"""Local Ollama structured-chat client for the contained YCB-100 agent protocol."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


OllamaTransport = Callable[[str, Mapping[str, Any], float], Mapping[str, Any]]
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _default_transport(
    url: str,
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    request = Request(
        url,
        data=json.dumps(dict(payload), sort_keys=True).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise ValueError("ollama_response_not_object")
    return decoded


class OllamaStructuredChatClient:
    """Expose Ollama through the same structured client used by the JSONL agent."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 300.0,
        context_tokens: int = 131_072,
        transport: OllamaTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in _LOCAL_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ollama_base_url_must_be_loopback_http")
        if timeout_seconds <= 0:
            raise ValueError("ollama_timeout_must_be_positive")
        if (
            not isinstance(context_tokens, int)
            or isinstance(context_tokens, bool)
            or context_tokens < 65_536
        ):
            raise ValueError("ollama_context_tokens_too_small")
        self._url = base_url.rstrip("/") + "/api/chat"
        self._timeout_seconds = float(timeout_seconds)
        self._context_tokens = context_tokens
        self._transport = transport or _default_transport

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        format: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not model.strip() or not messages:
            raise ValueError("ollama_request_identity_missing")
        merged_options = dict(options or {})
        merged_options["num_ctx"] = self._context_tokens
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": merged_options,
        }
        if format is not None:
            payload["format"] = dict(format)
        response = self._transport(self._url, payload, self._timeout_seconds)
        message = response.get("message")
        content: object = None
        if isinstance(message, Mapping):
            content = message.get("content")
        if content is None:
            content = response.get("response")
        if isinstance(content, Mapping):
            decoded = content
        elif isinstance(content, str):
            decoded = json.loads(content)
        else:
            raise ValueError("ollama_response_content_missing")
        if not isinstance(decoded, Mapping):
            raise ValueError("ollama_structured_response_not_object")
        return decoded


__all__ = ["OllamaStructuredChatClient", "OllamaTransport"]
