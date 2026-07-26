"""Evaluator-owned tool, source-mutation, and independent-reader boundaries."""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload


ToolHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
StateReader = Callable[[], Mapping[str, Any]]
SubjectStateReader = Callable[[str], Mapping[str, Any]]
MutationHandler = Callable[[], Mapping[str, Any]]
_SUBJECT_COLLECTION_KEYS = frozenset(("subjects", "records", "source_records", "effects"))


def _redact_private_response_fields(value: Any, private_fields: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, child in value.items():
            if str(key) in private_fields:
                continue
            redacted[copy.deepcopy(key)] = _redact_private_response_fields(child, private_fields)
        return redacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_private_response_fields(child, private_fields) for child in value]
    return copy.deepcopy(value)


def _contains_private_response_field(value: Any, private_fields: frozenset[str]) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in private_fields or _contains_private_response_field(child, private_fields):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_private_response_field(child, private_fields) for child in value)
    return False


def _select_subject_state(source_state: Mapping[str, Any], subject_id: str) -> dict[str, Any]:
    """Return exactly one subject-scoped source record from a source mapping."""
    candidates: list[tuple[str, Any]] = []
    if subject_id in source_state:
        candidates.append(("direct", source_state[subject_id]))
    for key in _SUBJECT_COLLECTION_KEYS:
        collection = source_state.get(key)
        if isinstance(collection, Mapping) and subject_id in collection:
            candidates.append((key, collection[subject_id]))
    if not candidates:
        raise RuntimeError("source_state_not_subject_scoped")
    if len(candidates) > 1:
        raise RuntimeError("source_state_ambiguous_subject_scope")
    location, record = candidates[0]
    scoped_record = copy.deepcopy(record)
    if not isinstance(scoped_record, Mapping):
        raise RuntimeError("source_subject_record_must_be_mapping")
    if location == "direct":
        return dict(scoped_record)
    return {location: {subject_id: dict(scoped_record)}}


@dataclass(frozen=True)
class ToolDefinitionV1:
    """One public tool exposed to an agent for one bounded episode."""

    name: str
    mode: str
    handler: ToolHandler
    private_response_fields: tuple[str, ...] = ()
    schema_version: str = "ycb100.acc.tool_definition.v1"

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ValueError("tool name is required")
        if self.mode not in {"read", "write"}:
            raise ValueError("tool mode must be read or write")
        if not callable(self.handler):
            raise TypeError("tool handler is required")
        fields = tuple(str(item or "").strip() for item in self.private_response_fields)
        if any(not item for item in fields) or len(fields) != len(set(fields)):
            raise ValueError("private response fields must be unique non-empty names")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "private_response_fields", fields)


@dataclass(frozen=True)
class ToolAuditEntryV1:
    ordinal: int
    tool_name: str
    mode: str
    request_hash: str
    response_hash: str
    schema_version: str = "ycb100.acc.tool_audit_entry.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ordinal": self.ordinal,
            "tool_name": self.tool_name,
            "mode": self.mode,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
        }


class ToolGatewayV1:
    """Bounded agent tool surface that never returns declared private fields."""

    def __init__(
        self,
        *,
        tools: Sequence[ToolDefinitionV1],
        read_budget: int,
        write_budget: int,
    ) -> None:
        definitions = {definition.name: definition for definition in tools}
        if not definitions or len(definitions) != len(tuple(tools)):
            raise ValueError("tool names must be unique and non-empty")
        if int(read_budget) < 0 or int(write_budget) < 0:
            raise ValueError("tool budgets must be non-negative")
        self._tools = definitions
        self._remaining = {"read": int(read_budget), "write": int(write_budget)}
        self._audit: list[ToolAuditEntryV1] = []

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    @property
    def audit(self) -> tuple[ToolAuditEntryV1, ...]:
        return tuple(self._audit)

    @property
    def audit_hash(self) -> str:
        return sha256_payload([entry.to_dict() for entry in self._audit])

    def invoke(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        tool_name = str(name or "").strip()
        definition = self._tools.get(tool_name)
        if definition is None:
            raise ValueError("undeclared_tool:" + tool_name)
        if not isinstance(arguments, Mapping):
            raise ValueError("tool arguments must be a mapping")
        if self._remaining[definition.mode] <= 0:
            raise RuntimeError("tool_budget_exhausted:" + definition.mode)
        raw = definition.handler(copy.deepcopy(dict(arguments)))
        if not isinstance(raw, Mapping):
            raise TypeError("tool response must be a mapping")
        private_fields = frozenset(definition.private_response_fields)
        response = _redact_private_response_fields(dict(raw), private_fields)
        if _contains_private_response_field(response, private_fields):
            raise RuntimeError("private_response_field_redaction_failed")
        self._remaining[definition.mode] -= 1
        self._audit.append(
            ToolAuditEntryV1(
                ordinal=len(self._audit),
                tool_name=definition.name,
                mode=definition.mode,
                request_hash=sha256_payload(dict(arguments)),
                response_hash=sha256_payload(response),
            )
        )
        return response


class SourceMutationLedgerV1:
    """Evaluator source ledger enforcing idempotency before source mutation."""

    def __init__(self, *, state_reader: StateReader) -> None:
        if not callable(state_reader):
            raise TypeError("state_reader is required")
        self._state_reader = state_reader
        self._entries: dict[str, tuple[str, Mapping[str, Any]]] = {}

    def mutate(
        self,
        *,
        idempotency_key: str,
        request: Mapping[str, Any],
        handler: MutationHandler,
    ) -> dict[str, Any]:
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key is required")
        if not isinstance(request, Mapping):
            raise ValueError("mutation request must be a mapping")
        if not callable(handler):
            raise TypeError("mutation handler is required")
        request_hash = sha256_payload(dict(request))
        existing = self._entries.get(key)
        if existing is not None:
            previous_hash, previous_response = existing
            if previous_hash != request_hash:
                raise ValueError("idempotency_key_reused_with_different_request")
            replay = copy.deepcopy(dict(previous_response))
            replay["idempotent_replay"] = True
            return replay
        before_hash = sha256_payload(self._state_reader())
        response = handler()
        if not isinstance(response, Mapping):
            raise TypeError("mutation handler response must be a mapping")
        result = copy.deepcopy(dict(response))
        after_hash = sha256_payload(self._state_reader())
        if result.get("committed") is True and before_hash == after_hash:
            raise RuntimeError("committed_mutation_without_source_state_change")
        result["idempotent_replay"] = False
        self._entries[key] = (request_hash, copy.deepcopy(result))
        return result


class IndependentSourceReaderV1:
    """Read-only evaluator interface intentionally separate from mutation tools."""

    def __init__(
        self,
        *,
        state_reader: StateReader,
        reader_id: str,
        subject_state_reader: SubjectStateReader | None = None,
    ) -> None:
        if not callable(state_reader):
            raise TypeError("state_reader is required")
        if subject_state_reader is not None and not callable(subject_state_reader):
            raise TypeError("subject_state_reader must be callable")
        self._state_reader = state_reader
        self._subject_state_reader = subject_state_reader
        self.reader_id = str(reader_id or "").strip()
        if not self.reader_id:
            raise ValueError("reader_id is required")
        self._read_count = 0

    @property
    def read_count(self) -> int:
        return self._read_count

    def read(self, *, subject_id: str) -> dict[str, Any]:
        subject = str(subject_id or "").strip()
        if not subject:
            raise ValueError("subject_id is required")
        self._read_count += 1
        if self._subject_state_reader is None:
            raw_state = self._state_reader()
            if not isinstance(raw_state, Mapping):
                raise TypeError("source state must be a mapping")
            state = _select_subject_state(dict(raw_state), subject)
        else:
            projection = self._subject_state_reader(subject)
            if not isinstance(projection, Mapping):
                raise TypeError("subject source projection must be a mapping")
            if set(projection) != {"subject_id", "source_state"}:
                raise RuntimeError("source_subject_projection_shape_invalid")
            if projection.get("subject_id") != subject:
                raise RuntimeError("source_subject_projection_mismatch")
            projected_state = projection.get("source_state")
            if not isinstance(projected_state, Mapping):
                raise RuntimeError("source_subject_projection_state_invalid")
            state = copy.deepcopy(dict(projected_state))
        return {
            "reader_id": self.reader_id,
            "subject_id": subject,
            "source_state": state,
            "source_state_hash": sha256_payload(state),
        }


__all__ = [
    "IndependentSourceReaderV1",
    "SourceMutationLedgerV1",
    "ToolAuditEntryV1",
    "ToolDefinitionV1",
    "ToolGatewayV1",
]
