"""Raw, public-development observations for ConsequenceBench causal-family construction.

These contracts deliberately model observations rather than conclusions.  The
agent presentation contains source records, timestamps, replica positions, and
tool characteristics, but never an outcome, a policy conclusion, or an
expected next step.  Family mechanics and causal edges belong to the evaluator
contract in :mod:`family_corpus`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload


RAW_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.raw_evidence.v1"
RAW_AGENT_VIEW_SCHEMA_VERSION = "ycb100.acc.raw_observation_agent_view.v1"

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,95}$")
_REFERENCE = re.compile(r"^[a-z][a-z0-9_:/.-]{2,160}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


def _identifier(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(field_name + " must be a lowercase identifier")
    return normalized


def _reference(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _REFERENCE.fullmatch(normalized):
        raise ValueError(field_name + " must be a bounded reference")
    return normalized


def _tick(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(field_name + " must be a non-negative integer")
    return value


def _hash(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _HASH.fullmatch(normalized):
        raise ValueError(field_name + " must be a sha256 digest")
    return normalized


@dataclass(frozen=True)
class AuthorityObservationV1:
    """An issuer-signed authority record, without any derived validity result."""

    record_id: str
    issuer_id: str
    subject_ref: str
    capability_ref: str
    issued_at: int
    valid_from: int
    valid_until: int
    delegation_ref: str
    signature_ref: str

    def __post_init__(self) -> None:
        for field_name in ("record_id", "issuer_id"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        for field_name in ("subject_ref", "capability_ref", "delegation_ref", "signature_ref"):
            object.__setattr__(self, field_name, _reference(getattr(self, field_name), field_name))
        for field_name in ("issued_at", "valid_from", "valid_until"):
            object.__setattr__(self, field_name, _tick(getattr(self, field_name), field_name))
        if self.valid_from > self.valid_until:
            raise ValueError("authority observation validity interval is inverted")

    def to_agent_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "issuer_id": self.issuer_id,
            "subject_ref": self.subject_ref,
            "capability_ref": self.capability_ref,
            "issued_at": self.issued_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "delegation_ref": self.delegation_ref,
            "signature_ref": self.signature_ref,
        }


@dataclass(frozen=True)
class EventFragmentV1:
    """A source-local event fragment.  Sequence and observed time are raw facts."""

    record_id: str
    source_id: str
    event_type: str
    subject_ref: str
    observed_at: int
    source_sequence: int
    payload_hash: str

    def __post_init__(self) -> None:
        for field_name in ("record_id", "source_id", "event_type"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        object.__setattr__(self, "subject_ref", _reference(self.subject_ref, "subject_ref"))
        object.__setattr__(self, "observed_at", _tick(self.observed_at, "observed_at"))
        object.__setattr__(self, "source_sequence", _tick(self.source_sequence, "source_sequence"))
        object.__setattr__(self, "payload_hash", _hash(self.payload_hash, "payload_hash"))

    def to_agent_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "event_type": self.event_type,
            "subject_ref": self.subject_ref,
            "observed_at": self.observed_at,
            "source_sequence": self.source_sequence,
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class SourceObservationV1:
    """A content-addressed source observation, not a source interpretation."""

    record_id: str
    source_id: str
    subject_ref: str
    observed_at: int
    artifact_hash: str
    retrieval_ref: str

    def __post_init__(self) -> None:
        for field_name in ("record_id", "source_id"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        object.__setattr__(self, "subject_ref", _reference(self.subject_ref, "subject_ref"))
        object.__setattr__(self, "observed_at", _tick(self.observed_at, "observed_at"))
        object.__setattr__(self, "artifact_hash", _hash(self.artifact_hash, "artifact_hash"))
        object.__setattr__(self, "retrieval_ref", _reference(self.retrieval_ref, "retrieval_ref"))

    def to_agent_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "subject_ref": self.subject_ref,
            "observed_at": self.observed_at,
            "artifact_hash": self.artifact_hash,
            "retrieval_ref": self.retrieval_ref,
        }


@dataclass(frozen=True)
class ReplicaObservationV1:
    """Replica placement and timing facts without a derived freshness judgement."""

    replica_id: str
    subject_ref: str
    observed_at: int
    source_sequence: int
    lag_ticks: int
    transport_hint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "replica_id", _identifier(self.replica_id, "replica_id"))
        object.__setattr__(self, "subject_ref", _reference(self.subject_ref, "subject_ref"))
        for field_name in ("observed_at", "source_sequence", "lag_ticks"):
            object.__setattr__(self, field_name, _tick(getattr(self, field_name), field_name))
        object.__setattr__(self, "transport_hint", _identifier(self.transport_hint, "transport_hint"))

    def to_agent_dict(self) -> dict[str, Any]:
        return {
            "replica_id": self.replica_id,
            "subject_ref": self.subject_ref,
            "observed_at": self.observed_at,
            "source_sequence": self.source_sequence,
            "lag_ticks": self.lag_ticks,
            "transport_hint": self.transport_hint,
        }


@dataclass(frozen=True)
class ToolMetadataV1:
    """Static tool constraints exposed to the participant before use."""

    tool_id: str
    read_scope: str
    latency_ticks: int
    cost_units: int
    staleness_bound_ticks: int
    side_effect_class: str
    audit_channel: str

    def __post_init__(self) -> None:
        for field_name in ("tool_id", "read_scope", "side_effect_class", "audit_channel"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        for field_name in ("latency_ticks", "cost_units", "staleness_bound_ticks"):
            object.__setattr__(self, field_name, _tick(getattr(self, field_name), field_name))

    def to_agent_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "read_scope": self.read_scope,
            "latency_ticks": self.latency_ticks,
            "cost_units": self.cost_units,
            "staleness_bound_ticks": self.staleness_bound_ticks,
            "side_effect_class": self.side_effect_class,
            "audit_channel": self.audit_channel,
        }


@dataclass(frozen=True)
class RawCausalObservationBundleV1:
    """Complete agent-visible raw evidence for one public causal family."""

    bundle_id: str
    domain_id: str
    authority_records: tuple[AuthorityObservationV1, ...]
    event_fragments: tuple[EventFragmentV1, ...]
    source_records: tuple[SourceObservationV1, ...]
    replica_metadata: tuple[ReplicaObservationV1, ...]
    tool_metadata: tuple[ToolMetadataV1, ...]
    schema_version: str = RAW_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RAW_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("raw evidence schema version mismatch")
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, "bundle_id"))
        object.__setattr__(self, "domain_id", _identifier(self.domain_id, "domain_id"))
        fields = (
            ("authority_records", AuthorityObservationV1),
            ("event_fragments", EventFragmentV1),
            ("source_records", SourceObservationV1),
            ("replica_metadata", ReplicaObservationV1),
            ("tool_metadata", ToolMetadataV1),
        )
        for field_name, record_type in fields:
            values = tuple(getattr(self, field_name))
            if not values or not all(isinstance(item, record_type) for item in values):
                raise ValueError(field_name + " must contain canonical raw records")
            identifiers = [item.to_agent_dict()["record_id"] if field_name != "replica_metadata" and field_name != "tool_metadata" else (item.replica_id if field_name == "replica_metadata" else item.tool_id) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(field_name + " contains duplicate identifiers")
            object.__setattr__(self, field_name, values)

    @property
    def agent_view_hash(self) -> str:
        return sha256_payload(self.to_agent_view())

    def to_agent_view(self) -> dict[str, Any]:
        return {
            "schema_version": RAW_AGENT_VIEW_SCHEMA_VERSION,
            "bundle_id": self.bundle_id,
            "domain_id": self.domain_id,
            "authority_records": [item.to_agent_dict() for item in self.authority_records],
            "event_fragments": [item.to_agent_dict() for item in self.event_fragments],
            "source_records": [item.to_agent_dict() for item in self.source_records],
            "replica_metadata": [item.to_agent_dict() for item in self.replica_metadata],
            "tool_metadata": [item.to_agent_dict() for item in self.tool_metadata],
        }


__all__ = [
    "AuthorityObservationV1",
    "EventFragmentV1",
    "RAW_AGENT_VIEW_SCHEMA_VERSION",
    "RAW_EVIDENCE_SCHEMA_VERSION",
    "RawCausalObservationBundleV1",
    "ReplicaObservationV1",
    "SourceObservationV1",
    "ToolMetadataV1",
]
