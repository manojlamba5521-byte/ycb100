"""Versioned contracts for a durable consequence-execution lifecycle."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


LIFECYCLE_CONTRACT_SCHEMA_VERSION = "ycb100.consequence_lifecycle.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@=-]{0,255}$")


class LifecycleState(StrEnum):
    PROPOSED = "PROPOSED"
    PREPARED = "PREPARED"
    RESERVED = "RESERVED"
    DISPATCHING = "DISPATCHING"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    COMMITTED = "COMMITTED"
    READBACK_PENDING = "READBACK_PENDING"
    EFFECT_VERIFIED = "EFFECT_VERIFIED"
    OBLIGATION_OPEN = "OBLIGATION_OPEN"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    COMPENSATING = "COMPENSATING"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"


TERMINAL_STATES = frozenset(
    {
        LifecycleState.VERIFIED,
        LifecycleState.DENIED,
        LifecycleState.REVOKED,
        LifecycleState.EXECUTION_FAILED,
        LifecycleState.COMPENSATED,
        LifecycleState.COMPENSATION_FAILED,
    }
)

ALLOWED_TRANSITIONS: Mapping[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.PROPOSED: frozenset({LifecycleState.PREPARED, LifecycleState.DENIED}),
    LifecycleState.PREPARED: frozenset({LifecycleState.RESERVED, LifecycleState.DENIED}),
    LifecycleState.RESERVED: frozenset({LifecycleState.DISPATCHING, LifecycleState.REVOKED}),
    LifecycleState.DISPATCHING: frozenset(
        {
            LifecycleState.EXECUTION_UNKNOWN,
            LifecycleState.COMMITTED,
            LifecycleState.EXECUTION_FAILED,
        }
    ),
    LifecycleState.EXECUTION_UNKNOWN: frozenset({LifecycleState.READBACK_PENDING}),
    LifecycleState.COMMITTED: frozenset({LifecycleState.READBACK_PENDING}),
    LifecycleState.READBACK_PENDING: frozenset(
        {
            LifecycleState.EFFECT_VERIFIED,
            LifecycleState.COMPENSATION_REQUIRED,
            LifecycleState.EXECUTION_FAILED,
        }
    ),
    LifecycleState.EFFECT_VERIFIED: frozenset(
        {
            LifecycleState.VERIFIED,
            LifecycleState.OBLIGATION_OPEN,
            LifecycleState.COMPENSATION_REQUIRED,
        }
    ),
    LifecycleState.OBLIGATION_OPEN: frozenset(
        {LifecycleState.VERIFIED, LifecycleState.COMPENSATION_REQUIRED}
    ),
    LifecycleState.COMPENSATION_REQUIRED: frozenset({LifecycleState.COMPENSATING}),
    LifecycleState.COMPENSATING: frozenset(
        {LifecycleState.COMPENSATED, LifecycleState.COMPENSATION_FAILED}
    ),
    **{state: frozenset() for state in TERMINAL_STATES},
}


def bounded_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(field_name + " must be a string identifier")
    normalized = value.strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(field_name + " must be a bounded identifier")
    return normalized


def canonical_json(value: Any) -> str:
    normalized = _plain_json(value, "$")
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_payload(value: Any) -> str:
    return sha256_text(canonical_json(value))


def _plain_json(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(path + " contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key or len(key) > 256:
                raise ValueError(path + " contains an invalid mapping key")
            result[key] = _plain_json(child, path + "." + key)
        return result
    if isinstance(value, (list, tuple)):
        return [_plain_json(child, path + "[]") for child in value]
    raise ValueError(path + " contains a non-JSON value")


@dataclass(frozen=True)
class ActionIdentityV1:
    """Immutable, canonical action and exact external-effect identity."""

    action_id: str
    tenant_id: str
    connector_id: str
    source_system: str
    action_type: str
    target_json: str
    parameters_json: str
    schema_version: str = LIFECYCLE_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LIFECYCLE_CONTRACT_SCHEMA_VERSION:
            raise ValueError("action identity schema version mismatch")
        for field_name in (
            "action_id",
            "tenant_id",
            "connector_id",
            "source_system",
            "action_type",
        ):
            object.__setattr__(
                self,
                field_name,
                bounded_identifier(getattr(self, field_name), field_name),
            )
        for field_name in ("target_json", "parameters_json"):
            raw = str(getattr(self, field_name) or "")
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(field_name + " must be canonical JSON") from exc
            if not isinstance(parsed, Mapping):
                raise ValueError(field_name + " must encode a JSON object")
            canonical = canonical_json(parsed)
            if raw != canonical:
                raise ValueError(field_name + " must use canonical JSON encoding")

    @classmethod
    def from_claims(
        cls,
        *,
        action_id: str,
        tenant_id: str,
        connector_id: str,
        source_system: str,
        action_type: str,
        target: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> "ActionIdentityV1":
        if not isinstance(target, Mapping) or not isinstance(parameters, Mapping):
            raise ValueError("target and parameters must be mappings")
        return cls(
            action_id=action_id,
            tenant_id=tenant_id,
            connector_id=connector_id,
            source_system=source_system,
            action_type=action_type,
            target_json=canonical_json(target),
            parameters_json=canonical_json(parameters),
        )

    @property
    def target(self) -> dict[str, Any]:
        return dict(json.loads(self.target_json))

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(json.loads(self.parameters_json))

    @property
    def effect_fingerprint(self) -> str:
        return sha256_payload(
            {
                "tenant_id": self.tenant_id,
                "connector_id": self.connector_id,
                "source_system": self.source_system,
                "action_type": self.action_type,
                "target": self.target,
                "parameters": self.parameters,
            }
        )

    @property
    def identity_hash(self) -> str:
        return sha256_payload(
            {
                "schema_version": self.schema_version,
                "action_id": self.action_id,
                "effect_fingerprint": self.effect_fingerprint,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "action_id": self.action_id,
            "tenant_id": self.tenant_id,
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "action_type": self.action_type,
            "target": self.target,
            "parameters": self.parameters,
            "effect_fingerprint": self.effect_fingerprint,
            "identity_hash": self.identity_hash,
        }


@dataclass(frozen=True)
class ActionSnapshotV1:
    identity: ActionIdentityV1
    state: LifecycleState
    state_version: int
    schema_version: str = LIFECYCLE_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ActionIdentityV1):
            raise ValueError("snapshot identity must be ActionIdentityV1")
        if not isinstance(self.state, LifecycleState):
            raise ValueError("snapshot state must be LifecycleState")
        if (
            not isinstance(self.state_version, int)
            or isinstance(self.state_version, bool)
            or self.state_version < 0
        ):
            raise ValueError("snapshot state_version must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "state": self.state.value,
            "state_version": self.state_version,
        }


def validate_expected_state_version(value: object, *, allow_creation: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected_state_version must be an integer")
    minimum = -1 if allow_creation else 0
    if value < minimum:
        raise ValueError("expected_state_version is outside the valid range")
    return value


def validate_transition(current: LifecycleState, target: LifecycleState) -> None:
    if not isinstance(current, LifecycleState) or not isinstance(target, LifecycleState):
        raise ValueError("lifecycle transition states are invalid")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError("illegal lifecycle transition: " + current.value + " -> " + target.value)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ActionIdentityV1",
    "ActionSnapshotV1",
    "LIFECYCLE_CONTRACT_SCHEMA_VERSION",
    "LifecycleState",
    "TERMINAL_STATES",
    "bounded_identifier",
    "canonical_json",
    "sha256_payload",
    "validate_expected_state_version",
    "validate_transition",
]
