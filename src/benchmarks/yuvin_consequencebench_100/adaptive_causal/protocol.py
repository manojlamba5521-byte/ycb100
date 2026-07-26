"""Strict JSONL message validation for universal YCB-100 agent adapters."""
from __future__ import annotations

from typing import Any, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import FrozenActionProposalCandidateV1


AGENT_MESSAGE_TYPES = frozenset(
    {
        "tool.call",
        "checkpoint.put",
        "candidate.submit",
        "decision.submit",
        "episode.finish",
    }
)


def validate_agent_message(message: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one adapter message without trusting agent-owned conclusions."""
    if not isinstance(message, Mapping):
        raise ValueError("agent message must be an object")
    message_type = str(message.get("type") or "").strip()
    if message_type not in AGENT_MESSAGE_TYPES:
        raise ValueError("agent message type is unsupported")
    sequence = message.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ValueError("agent message sequence must be a non-negative integer")
    if message_type == "candidate.submit":
        candidate = FrozenActionProposalCandidateV1.from_mapping(message.get("candidate") or {})
        return {"type": message_type, "sequence": sequence, "candidate": candidate.to_dict()}
    payload = message.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("agent message payload must be an object")
    if message_type == "checkpoint.put":
        if set(payload) != {"checkpoint_hash"}:
            raise ValueError("checkpoint.put accepts only checkpoint_hash")
        checkpoint_hash = str(payload.get("checkpoint_hash") or "")
        if len(checkpoint_hash) != 71 or not checkpoint_hash.startswith("sha256:") or any(
            character not in "0123456789abcdef" for character in checkpoint_hash[7:]
        ):
            raise ValueError("checkpoint.put requires an exact sha256 content hash")
    if message_type == "decision.submit":
        if set(payload) != {"decision", "rationale_record_ids", "confidence_basis_points"}:
            raise ValueError("decision.submit has an invalid payload shape")
        decision = str(payload.get("decision") or "").strip()
        if decision not in {"execute", "deny", "defer", "escalate", "compensate"}:
            raise ValueError("decision.submit decision is unsupported")
        references = payload.get("rationale_record_ids")
        if not isinstance(references, list) or not references or not all(isinstance(item, str) and item for item in references):
            raise ValueError("decision.submit requires bounded rationale record identifiers")
        confidence = payload.get("confidence_basis_points")
        if not isinstance(confidence, int) or isinstance(confidence, bool) or not 0 <= confidence <= 10_000:
            raise ValueError("decision.submit confidence_basis_points is invalid")
    return {"type": message_type, "sequence": sequence, "payload": dict(payload)}


__all__ = ["AGENT_MESSAGE_TYPES", "validate_agent_message"]
