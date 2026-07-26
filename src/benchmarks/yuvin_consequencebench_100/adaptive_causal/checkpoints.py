"""Immutable, agent-authored semantic checkpoints for Adaptive Causal candidates.

Checkpoints are deliberation artifacts, not evidence or authorization.  They may
only cite opaque handles that were visible to the agent; the evaluator resolves
those handles separately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import canonical_json, sha256_payload


SEMANTIC_CHECKPOINT_SCHEMA_VERSION = "ycb100.acc.semantic_checkpoint.v1"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@=-]{0,255}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_CLAIM_KEYS = frozenset(
    {
        "oracle",
        "oracle_state",
        "state",
        "world_state",
        "canonical_action_state",
        "action_state",
        "authorization",
        "authorization_status",
        "authority",
        "authority_reference",
        "approval",
        "evidence",
        "evidence_row",
        "evidence_record",
        "evidence_records",
        "canonical_evidence",
        "trusted_evidence",
        "verification_status",
        "receipt",
        "receipt_id",
    }
)
_BROAD_VALUES = frozenset(
    {
        "",
        "unknown",
        "uncertain",
        "risk",
        "wait",
        "monitor",
        "investigate",
        "tbd",
        "n/a",
        "none",
        "unspecified",
    }
)


def _identifier(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field_name} must be a bounded identifier")
    return text


def _sha256(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{field_name} must be a sha256 digest")
    return text


def _semantic_text(value: Any, field_name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    text = " ".join(value.split())
    normalized = text.casefold().rstrip(".!:;")
    if len(text) < 16 or len(text) > maximum or normalized in _BROAD_VALUES:
        raise ValueError(f"{field_name} must be specific, non-empty bounded text")
    if len(re.findall(r"[A-Za-z0-9]+", text)) < 3:
        raise ValueError(f"{field_name} must contain a specific semantic statement")
    return text


def _reject_forbidden_claims(value: Mapping[str, Any], path: str) -> None:
    for key, item in value.items():
        normalized = str(key).strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized in _FORBIDDEN_CLAIM_KEYS:
            raise ValueError(f"{path}.{normalized} is not permitted in a semantic checkpoint")
        if isinstance(item, Mapping):
            _reject_forbidden_claims(item, f"{path}.{normalized}")
        elif isinstance(item, (list, tuple)):
            for index, member in enumerate(item):
                if isinstance(member, Mapping):
                    _reject_forbidden_claims(member, f"{path}.{normalized}[{index}]")


@dataclass(frozen=True)
class ControllingClaimSourceJoinV1:
    """A narrow agent claim joined to one opaque, agent-visible source handle."""

    claim: str
    source_handle: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim", _semantic_text(self.claim, "claim", maximum=512))
        object.__setattr__(self, "source_handle", _identifier(self.source_handle, "source_handle"))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ControllingClaimSourceJoinV1":
        if not isinstance(payload, Mapping):
            raise ValueError("controlling claim/source join must be a mapping")
        _reject_forbidden_claims(payload, "controlling_claim_source_join")
        allowed = {"claim", "source_handle"}
        unexpected = sorted(str(key) for key in payload if str(key) not in allowed)
        if unexpected:
            raise ValueError("controlling claim/source join contains unsupported fields: " + ",".join(unexpected))
        return cls(claim=payload.get("claim"), source_handle=payload.get("source_handle"))

    def to_dict(self) -> dict[str, str]:
        return {"claim": self.claim, "source_handle": self.source_handle}


@dataclass(frozen=True)
class SemanticCheckpointV1:
    """A hash-bound semantic checkpoint that contains no evaluator-owned facts."""

    effect_fingerprint: str
    controlling_claim_source_joins: tuple[ControllingClaimSourceJoinV1, ...]
    rejected_plausible_alternative: str
    material_uncertainty: str
    irreversible_risk_statement: str
    revision_trigger: str
    payload_hash: str = ""
    schema_version: str = SEMANTIC_CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("semantic checkpoint schema version mismatch")
        object.__setattr__(self, "effect_fingerprint", _sha256(self.effect_fingerprint, "effect_fingerprint"))

        joins = tuple(self.controlling_claim_source_joins)
        if not joins:
            raise ValueError("semantic checkpoint requires at least one controlling claim/source join")
        if not all(isinstance(join, ControllingClaimSourceJoinV1) for join in joins):
            raise ValueError("controlling_claim_source_joins must contain canonical joins")
        source_handles = tuple(join.source_handle for join in joins)
        if len(source_handles) != len(set(source_handles)):
            raise ValueError("controlling_claim_source_joins must use unique source handles")
        object.__setattr__(self, "controlling_claim_source_joins", joins)

        object.__setattr__(
            self,
            "rejected_plausible_alternative",
            _semantic_text(self.rejected_plausible_alternative, "rejected_plausible_alternative"),
        )
        object.__setattr__(self, "material_uncertainty", _semantic_text(self.material_uncertainty, "material_uncertainty"))
        object.__setattr__(
            self,
            "irreversible_risk_statement",
            _semantic_text(self.irreversible_risk_statement, "irreversible_risk_statement"),
        )
        object.__setattr__(self, "revision_trigger", _semantic_text(self.revision_trigger, "revision_trigger"))

        declared_hash = str(self.payload_hash or "").strip()
        expected_hash = self.recomputed_payload_hash
        if declared_hash and declared_hash != expected_hash:
            raise ValueError("semantic checkpoint payload_hash mismatch")
        object.__setattr__(self, "payload_hash", expected_hash)

    @property
    def source_handles(self) -> tuple[str, ...]:
        return tuple(join.source_handle for join in self.controlling_claim_source_joins)

    @property
    def recomputed_payload_hash(self) -> str:
        return sha256_payload(
            {
                "schema_version": self.schema_version,
                "effect_fingerprint": self.effect_fingerprint,
                "controlling_claim_source_joins": [join.to_dict() for join in self.controlling_claim_source_joins],
                "rejected_plausible_alternative": self.rejected_plausible_alternative,
                "material_uncertainty": self.material_uncertainty,
                "irreversible_risk_statement": self.irreversible_risk_statement,
                "revision_trigger": self.revision_trigger,
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SemanticCheckpointV1":
        if not isinstance(payload, Mapping):
            raise ValueError("semantic checkpoint must be a mapping")
        _reject_forbidden_claims(payload, "semantic_checkpoint")
        allowed = {
            "schema_version",
            "effect_fingerprint",
            "controlling_claim_source_joins",
            "rejected_plausible_alternative",
            "material_uncertainty",
            "irreversible_risk_statement",
            "revision_trigger",
            "payload_hash",
        }
        unexpected = sorted(str(key) for key in payload if str(key) not in allowed)
        if unexpected:
            raise ValueError("semantic checkpoint contains unsupported fields: " + ",".join(unexpected))
        raw_joins = payload.get("controlling_claim_source_joins")
        if not isinstance(raw_joins, (list, tuple)):
            raise ValueError("controlling_claim_source_joins must be a non-empty sequence")
        return cls(
            effect_fingerprint=payload.get("effect_fingerprint"),
            controlling_claim_source_joins=tuple(ControllingClaimSourceJoinV1.from_mapping(join) for join in raw_joins),
            rejected_plausible_alternative=payload.get("rejected_plausible_alternative"),
            material_uncertainty=payload.get("material_uncertainty"),
            irreversible_risk_statement=payload.get("irreversible_risk_statement"),
            revision_trigger=payload.get("revision_trigger"),
            payload_hash=str(payload.get("payload_hash") or ""),
            schema_version=str(payload.get("schema_version") or SEMANTIC_CHECKPOINT_SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "effect_fingerprint": self.effect_fingerprint,
            "controlling_claim_source_joins": [join.to_dict() for join in self.controlling_claim_source_joins],
            "rejected_plausible_alternative": self.rejected_plausible_alternative,
            "material_uncertainty": self.material_uncertainty,
            "irreversible_risk_statement": self.irreversible_risk_statement,
            "revision_trigger": self.revision_trigger,
            "payload_hash": self.payload_hash,
        }

    def validate_against(self, *, agent_visible_handles: set[str] | tuple[str, ...] | list[str], effect_fingerprint: str) -> None:
        validate_semantic_checkpoint(
            self,
            agent_visible_handles=agent_visible_handles,
            effect_fingerprint=effect_fingerprint,
        )


def validate_semantic_checkpoint(
    checkpoint: SemanticCheckpointV1,
    *,
    agent_visible_handles: set[str] | tuple[str, ...] | list[str],
    effect_fingerprint: str,
) -> None:
    """Fail closed unless the checkpoint is bound to this effect and visible sources."""
    if not isinstance(checkpoint, SemanticCheckpointV1):
        raise ValueError("checkpoint must be a SemanticCheckpointV1")
    expected_effect_fingerprint = _sha256(effect_fingerprint, "effect_fingerprint")
    if checkpoint.effect_fingerprint != expected_effect_fingerprint:
        raise ValueError("semantic checkpoint effect_fingerprint does not match the supplied effect")
    try:
        visible = {_identifier(handle, "agent_visible_handle") for handle in agent_visible_handles}
    except TypeError as exc:
        raise ValueError("agent_visible_handles must be a finite collection") from exc
    if not visible:
        raise ValueError("agent_visible_handles must not be empty")
    unbound = sorted(set(checkpoint.source_handles) - visible)
    if unbound:
        raise ValueError("semantic checkpoint cites handles not visible to the agent: " + ",".join(unbound))
    if checkpoint.payload_hash != checkpoint.recomputed_payload_hash:
        raise ValueError("semantic checkpoint payload_hash mismatch")
    # Force canonical JSON encoding now so unsupported contract data cannot survive a caller mutation.
    canonical_json(checkpoint.to_dict())


__all__ = [
    "ControllingClaimSourceJoinV1",
    "SEMANTIC_CHECKPOINT_SCHEMA_VERSION",
    "SemanticCheckpointV1",
    "validate_semantic_checkpoint",
]
