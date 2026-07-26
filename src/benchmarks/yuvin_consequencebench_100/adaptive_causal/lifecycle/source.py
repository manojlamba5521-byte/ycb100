"""Evaluator-owned external source state and a reference JSONL candidate.

The external source is deliberately separate from both connector acknowledgements
and the canonical lifecycle SQLite database. The same module is also executable:
the small reference candidate exercises the public lifecycle protocol without
reading evaluator files or importing benchmark internals.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


EXTERNAL_SOURCE_SCHEMA_VERSION = "ycb100.lifecycle.external_source.v1"
REFERENCE_CANDIDATE_SCHEMA_VERSION = "ycb100.lifecycle.reference_candidate.v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_payload(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    encoded = _canonical_json(dict(payload)) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class PersistedExternalSource:
    """Atomic evaluator-owned source-of-truth state for one lifecycle world."""

    def __init__(
        self,
        path: str | Path,
        *,
        world_hash: str,
        initial_state: Mapping[str, str | int | bool],
        records: Sequence[Mapping[str, Any]],
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.world_hash = str(world_hash)
        self._lock = threading.RLock()
        if self.path.exists():
            payload = self._load()
            if payload.get("world_hash") != self.world_hash:
                raise ValueError("external source belongs to a different lifecycle world")
        else:
            record_map = {
                str(record["record_id"]): json.loads(_canonical_json(dict(record)))
                for record in records
            }
            self._write(
                {
                    "schema_version": EXTERNAL_SOURCE_SCHEMA_VERSION,
                    "world_hash": self.world_hash,
                    "state": dict(initial_state),
                    "records": record_map,
                    "effects": [],
                    "compensations": [],
                    "duties": [],
                    "reservations": {},
                    "applied_events": [],
                    "event_history": [],
                }
            )

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("external source state is unreadable") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != EXTERNAL_SOURCE_SCHEMA_VERSION
        ):
            raise ValueError("external source schema mismatch")
        return payload

    def _write(self, payload: Mapping[str, Any]) -> None:
        _atomic_json_write(self.path, payload)

    @property
    def state_hash(self) -> str:
        with self._lock:
            return _sha256_payload(self._load())

    def public_record(self, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._load()["records"].get(str(record_id))
            return json.loads(_canonical_json(record)) if isinstance(record, dict) else None

    def records_for_service(self, service_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            records = self._load()["records"].values()
            return tuple(
                json.loads(_canonical_json(record))
                for record in records
                if record.get("service_id") == service_id
            )

    def apply_event(
        self,
        *,
        event_id: str,
        logical_step: int,
        event_type: str,
        record_refs: Sequence[str],
        state_patch: Mapping[str, str | int | bool],
    ) -> bool:
        with self._lock:
            payload = self._load()
            if event_id in payload["applied_events"]:
                return False
            payload["state"].update(dict(state_patch))
            for record_id in record_refs:
                record = payload["records"].get(record_id)
                if not isinstance(record, dict):
                    continue
                fields = record.get("fields")
                if not isinstance(fields, list):
                    continue
                for field in fields:
                    if isinstance(field, dict) and field.get("name") in state_patch:
                        field["value"] = state_patch[str(field["name"])]
            payload["applied_events"].append(event_id)
            payload["event_history"].append(
                {
                    "event_id": event_id,
                    "logical_step": logical_step,
                    "event_type": event_type,
                    "record_refs": list(record_refs),
                    "state_patch_hash": _sha256_payload(dict(state_patch)),
                }
            )
            self._write(payload)
            return True

    def claim_reservation(
        self,
        *,
        semantic_key: str,
        owner_id: str,
        lease_generation: int,
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            existing = payload["reservations"].get(semantic_key)
            if existing is not None:
                return {
                    "claimed": existing.get("owner_id") == owner_id,
                    "owner_id": existing.get("owner_id"),
                    "lease_generation": existing.get("lease_generation"),
                }
            receipt = {
                "owner_id": owner_id,
                "lease_generation": int(lease_generation),
                "semantic_key_hash": _sha256_payload({"semantic_key": semantic_key}),
            }
            payload["reservations"][semantic_key] = receipt
            self._write(payload)
            return {"claimed": True, **receipt}

    def commit_effect(
        self,
        *,
        action_id: str,
        action_identity: Mapping[str, Any],
        lifecycle_effect_fingerprint: str,
        invocation_id: str,
        source_system: str,
        state_diff: Sequence[Mapping[str, Any]],
        partial: bool,
        duties: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Commit exactly once by invocation identity, regardless of oracle safety."""
        with self._lock:
            payload = self._load()
            for existing in payload["effects"]:
                if existing["invocation_id"] == invocation_id:
                    return json.loads(_canonical_json(existing))
            ordinal = len(payload["effects"]) + 1
            source_effect_id = "source_effect_" + _sha256_payload(
                {
                    "world_hash": self.world_hash,
                    "invocation_id": invocation_id,
                    "ordinal": ordinal,
                }
            )[7:31]
            mutations = [dict(item) for item in state_diff]
            pre_effect_state = json.loads(_canonical_json(payload["state"]))
            applied_count = max(1, len(mutations) // 2) if partial and mutations else len(mutations)
            for mutation in mutations[:applied_count]:
                path = str(mutation.get("path") or "")
                if path:
                    payload["state"][path] = mutation.get("after")
            source_payload = {
                "action_id": action_id,
                "action_identity": dict(action_identity),
                "effect_fingerprint": lifecycle_effect_fingerprint,
                "invocation_id": invocation_id,
                "committed": True,
                "partial": bool(partial),
                "applied_mutation_count": applied_count,
                "requested_mutation_count": len(mutations),
            }
            effect = {
                "source_effect_id": source_effect_id,
                "source_system": source_system,
                "action_id": action_id,
                "effect_fingerprint": lifecycle_effect_fingerprint,
                "invocation_id": invocation_id,
                "status": "partial" if partial else "committed",
                "source_payload": source_payload,
                "source_payload_hash": _sha256_payload(source_payload),
                "pre_effect_state": pre_effect_state,
                "pre_effect_state_hash": _sha256_payload(pre_effect_state),
                "sequence": ordinal,
            }
            payload["effects"].append(effect)
            existing_duties = {item["obligation_id"] for item in payload["duties"]}
            for raw in duties:
                duty = dict(raw)
                if duty["obligation_id"] in existing_duties:
                    continue
                duty["original_source_effect_id"] = source_effect_id
                duty["effect_fingerprint"] = lifecycle_effect_fingerprint
                duty["status"] = "OPEN"
                payload["duties"].append(duty)
                existing_duties.add(duty["obligation_id"])
            self._write(payload)
            return json.loads(_canonical_json(effect))

    def effect_for_action(
        self,
        *,
        action_id: str,
        lifecycle_effect_fingerprint: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            for effect in reversed(self._load()["effects"]):
                if (
                    effect["action_id"] == action_id
                    and effect["effect_fingerprint"] == lifecycle_effect_fingerprint
                ):
                    return json.loads(_canonical_json(effect))
            return None

    def effects(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(
                json.loads(_canonical_json(item)) for item in self._load()["effects"]
            )

    def duties_for_effect(self, source_effect_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(
                json.loads(_canonical_json(item))
                for item in self._load()["duties"]
                if item["original_source_effect_id"] == source_effect_id
            )

    def discharge_duty(self, obligation_id: str, *, logical_step: int) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            for duty in payload["duties"]:
                if duty["obligation_id"] != obligation_id:
                    continue
                if duty["status"] == "DISCHARGED":
                    return json.loads(_canonical_json(duty))
                if logical_step < int(duty.get("trigger_step") or 0):
                    raise ValueError("source obligation condition is not yet observable")
                duty["status"] = "DISCHARGED"
                duty["discharged_at_step"] = logical_step
                duty["discharge_evidence_hash"] = _sha256_payload(
                    {
                        "obligation_id": obligation_id,
                        "logical_step": logical_step,
                        "world_hash": self.world_hash,
                    }
                )
                self._write(payload)
                return json.loads(_canonical_json(duty))
            raise ValueError("source obligation does not exist")

    def commit_compensation(
        self,
        *,
        compensation_id: str,
        original_source_effect_id: str,
        operation: str,
        source_system: str,
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            for existing in payload["compensations"]:
                if existing["compensation_id"] == compensation_id:
                    return json.loads(_canonical_json(existing))
            if not any(
                effect["source_effect_id"] == original_source_effect_id
                for effect in payload["effects"]
            ):
                raise ValueError("compensation cannot replace a missing original effect")
            effect_id = "compensation_effect_" + _sha256_payload(
                {
                    "world_hash": self.world_hash,
                    "compensation_id": compensation_id,
                    "original_source_effect_id": original_source_effect_id,
                }
            )[7:31]
            receipt = {
                "compensation_id": compensation_id,
                "compensation_effect_id": effect_id,
                "original_source_effect_id": original_source_effect_id,
                "operation": operation,
                "source_system": source_system,
                "verified": True,
                "sequence": len(payload["compensations"]) + 1,
            }
            payload["compensations"].append(receipt)
            self._write(payload)
            return json.loads(_canonical_json(receipt))

    def compensations(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(
                json.loads(_canonical_json(item))
                for item in self._load()["compensations"]
            )


class ReferenceLifecycleExecutor:
    """Protocol-only candidate used for runner qualification and examples."""

    def __init__(self) -> None:
        self.sequence = 0

    def _call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        sys.stdout.write(
            _canonical_json(
                {
                    "type": "tool.call",
                    "sequence": self.sequence,
                    "name": name,
                    "arguments": dict(arguments),
                }
            )
            + "\n"
        )
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("evaluator closed the lifecycle protocol")
        response = json.loads(line)
        if response.get("type") != "tool.result":
            raise RuntimeError("unexpected lifecycle protocol response")
        if response.get("ok") is not True:
            raise RuntimeError(str(response.get("error") or "tool call failed"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("tool result must be an object")
        return result

    def _investigate(self) -> tuple[dict[str, Any], ...]:
        inspected: set[str] = set()
        records: list[dict[str, Any]] = []
        for _ in range(64):
            discovery = self._call("service.discover", {})
            services = discovery.get("services") or ()
            for raw_service in services:
                service_id = str(raw_service["service_id"])
                if service_id in inspected:
                    continue
                self._call("schema.describe", {"service_id": service_id})
                result = self._call("record.read", {"service_id": service_id})
                records.extend(
                    dict(record)
                    for record in result.get("records") or ()
                    if isinstance(record, Mapping)
                )
                inspected.add(service_id)
            if discovery.get("discovery_complete"):
                break
            self._call("event.poll", {})
        else:
            raise RuntimeError("service discovery did not converge")
        cursor = 0
        for _ in range(64):
            history = self._call("history.read", {"cursor": cursor, "limit": 64})
            next_cursor = history.get("next_cursor")
            if next_cursor is None:
                break
            cursor = int(next_cursor)
        return tuple(records)

    @staticmethod
    def _reconstruct_identity(
        claim: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        expected = {
            "action_id",
            "tenant_id",
            "actor_id",
            "operation",
            "target_id",
            "requested_value",
            "unit",
            "environment",
            "generation",
        }
        witnessed: dict[str, Any] = {}
        for record in records:
            for raw_field in record.get("fields") or ():
                if not isinstance(raw_field, Mapping):
                    continue
                name = str(raw_field.get("name") or "")
                if not name.startswith("proposal_binding."):
                    continue
                key = name.removeprefix("proposal_binding.")
                if key not in expected:
                    continue
                value = raw_field.get("value")
                if key in witnessed and witnessed[key] != value:
                    raise RuntimeError("conflicting trusted proposal identity witnesses")
                witnessed[key] = value
        missing = expected.difference(witnessed)
        if missing:
            raise RuntimeError(
                "trusted proposal identity is incomplete: " + ",".join(sorted(missing))
            )
        for key, claimed_value in claim.items():
            if key in witnessed and witnessed[key] != claimed_value:
                raise RuntimeError("untrusted proposal claim conflicts with source: " + key)
        material = {
            key: witnessed[key]
            for key in (
                "tenant_id",
                "actor_id",
                "operation",
                "target_id",
                "requested_value",
                "unit",
                "environment",
                "generation",
            )
        }
        return {
            "action_id": witnessed["action_id"],
            **material,
            "fingerprint": _sha256_payload(material),
        }

    def run(self, first_message: Mapping[str, Any]) -> None:
        message_type = str(first_message.get("type") or "")
        if message_type == "episode.start":
            episode = first_message.get("episode")
            if not isinstance(episode, Mapping):
                raise RuntimeError("episode.start is missing the episode")
            proposal_claim = episode.get("proposal_claim")
            if not isinstance(proposal_claim, Mapping):
                raise RuntimeError("episode.start is missing the proposal claim")
            claimed_identity = proposal_claim.get("claimed_identity")
            if not isinstance(claimed_identity, Mapping):
                raise RuntimeError("proposal claim is missing its untrusted identity")
            self._call(
                "checkpoint.save",
                {
                    "checkpoint": {
                        "phase": "investigating",
                        "proposal_claim": dict(claimed_identity),
                    }
                },
            )
            records = self._investigate()
            action = self._reconstruct_identity(claimed_identity, records)
            self._call(
                "checkpoint.save",
                {"checkpoint": {"phase": "identity_reconstructed", "action": action}},
            )
            recovered = self._call("session.recover", {})
            if recovered.get("source_effects"):
                decision = "recover"
            else:
                prepared = self._call("action.prepare", {"identity": action})
                self._call(
                    "effect.reserve",
                    {
                        "action_id": action["action_id"],
                        "effect_fingerprint": prepared["effect_fingerprint"],
                        "proposal_fingerprint": action["fingerprint"],
                    },
                )
                self._call(
                    "checkpoint.save",
                    {"checkpoint": {"phase": "reserved", "action": action}},
                )
                self._call("effect.dispatch", {"action_id": action["action_id"]})
                decision = "execute"
        elif message_type == "session.restart":
            recovered = self._call("session.recover", {})
            checkpoint = recovered.get("checkpoint")
            if not isinstance(checkpoint, Mapping):
                raise RuntimeError("durable checkpoint is unavailable after restart")
            action = dict(checkpoint["action"])
            matching_actions = [
                item
                for item in recovered.get("actions") or ()
                if isinstance(item, Mapping)
                and isinstance(item.get("identity"), Mapping)
                and item["identity"].get("action_id") == action.get("action_id")
            ]
            state = str(matching_actions[-1].get("state") or "") if matching_actions else ""
            if state == "PROPOSED":
                self._call("action.prepare", {"identity": action})
                state = "PREPARED"
            if state == "PREPARED":
                prepared = self._call("action.prepare", {"identity": action})
                self._call(
                    "effect.reserve",
                    {
                        "action_id": action["action_id"],
                        "effect_fingerprint": prepared["effect_fingerprint"],
                        "proposal_fingerprint": action["fingerprint"],
                    },
                )
                state = "RESERVED"
            if state == "RESERVED":
                self._call("effect.dispatch", {"action_id": action["action_id"]})
            decision = "recover"
        else:
            raise RuntimeError("reference candidate expected episode.start or session.restart")

        readback = self._call("source.readback", {"action_id": action["action_id"]})
        for duty in readback.get("open_obligations") or []:
            obligation_id = str(duty["obligation_id"])
            self._call(
                "obligation.open",
                {"action_id": action["action_id"], "obligation_id": obligation_id},
            )
            self._call(
                "obligation.discharge",
                {"action_id": action["action_id"], "obligation_id": obligation_id},
            )
        if readback.get("compensation_required"):
            prepared_compensation = self._call(
                "compensation.prepare",
                {"action_id": action["action_id"]},
            )
            self._call(
                "compensation.dispatch",
                {
                    "action_id": action["action_id"],
                    "compensation_id": prepared_compensation["compensation_id"],
                },
            )
            decision = "compensate"
        self._call(
            "episode.finish",
            {"decision": decision, "action_id": action["action_id"]},
        )


def main() -> int:
    first_line = sys.stdin.readline()
    if not first_line:
        return 2
    try:
        first = json.loads(first_line)
        if not isinstance(first, dict):
            return 2
        ReferenceLifecycleExecutor().run(first)
    except Exception as exc:
        sys.stderr.write(type(exc).__name__ + ":" + str(exc) + "\n")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXTERNAL_SOURCE_SCHEMA_VERSION",
    "PersistedExternalSource",
    "REFERENCE_CANDIDATE_SCHEMA_VERSION",
    "ReferenceLifecycleExecutor",
    "main",
]
