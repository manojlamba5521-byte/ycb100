"""Deterministic event-sourced world primitives for YCB-100 public episodes."""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    WorldSnapshotBindingV1,
    canonical_json,
    sha256_payload,
)


def _identifier(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 256:
        raise ValueError(field_name + " is required")
    return text


def _plain_mapping(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(field_name + " must be a mapping")
    return copy.deepcopy(dict(value))


@dataclass(frozen=True)
class WorldEventV1:
    event_id: str
    event_type: str
    virtual_tick: int
    actor_id: str
    payload: Mapping[str, Any]
    causal_parent_ids: tuple[str, ...] = ()
    schema_version: str = "ycb100.acc.world_event.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "event_type", _identifier(self.event_type, "event_type"))
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        if not isinstance(self.virtual_tick, int) or self.virtual_tick < 0:
            raise ValueError("virtual_tick must be a non-negative integer")
        object.__setattr__(self, "payload", _plain_mapping(self.payload, "event payload"))
        parents = tuple(_identifier(item, "causal_parent_id") for item in self.causal_parent_ids)
        if len(parents) != len(set(parents)):
            raise ValueError("causal_parent_ids must not contain duplicates")
        object.__setattr__(self, "causal_parent_ids", parents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "virtual_tick": self.virtual_tick,
            "actor_id": self.actor_id,
            "payload": copy.deepcopy(dict(self.payload)),
            "causal_parent_ids": list(self.causal_parent_ids),
        }

    @property
    def body_hash(self) -> str:
        return sha256_payload(
            {
                "event_type": self.event_type,
                "virtual_tick": self.virtual_tick,
                "actor_id": self.actor_id,
                "payload": dict(self.payload),
                "causal_parent_ids": list(self.causal_parent_ids),
            }
        )


@dataclass(frozen=True)
class ScheduledWorldEventV1:
    schedule_id: str
    event_type: str
    due_tick: int
    payload: Mapping[str, Any]
    actor_id: str = "world_scheduler"
    schema_version: str = "ycb100.acc.scheduled_world_event.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "schedule_id", _identifier(self.schedule_id, "schedule_id"))
        object.__setattr__(self, "event_type", _identifier(self.event_type, "event_type"))
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        if not isinstance(self.due_tick, int) or self.due_tick < 0:
            raise ValueError("due_tick must be a non-negative integer")
        object.__setattr__(self, "payload", _plain_mapping(self.payload, "scheduled event payload"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "schedule_id": self.schedule_id,
            "event_type": self.event_type,
            "due_tick": self.due_tick,
            "payload": copy.deepcopy(dict(self.payload)),
            "actor_id": self.actor_id,
        }


EventHandler = Callable[[dict[str, Any], ScheduledWorldEventV1], None]


class EventSourcedWorld:
    """Append-only state with deterministic scheduled events and exact forks."""

    def __init__(
        self,
        *,
        world_id: str,
        initial_state: Mapping[str, Any],
        scheduled_events: tuple[ScheduledWorldEventV1, ...] = (),
        event_handlers: Mapping[str, EventHandler] | None = None,
    ) -> None:
        self.world_id = _identifier(world_id, "world_id")
        self._state = _plain_mapping(initial_state, "initial_state")
        self._initial_state = _plain_mapping(initial_state, "initial_state")
        self._scheduled_events = tuple(sorted(scheduled_events, key=lambda item: (item.due_tick, item.schedule_id)))
        if len({item.schedule_id for item in self._scheduled_events}) != len(self._scheduled_events):
            raise ValueError("scheduled event IDs must be unique")
        self._event_handlers = dict(event_handlers or {})
        self._events: list[WorldEventV1] = []
        self._virtual_tick = 0
        self._applied_schedule_ids: set[str] = set()

    @property
    def virtual_tick(self) -> int:
        return self._virtual_tick

    @property
    def state(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    @property
    def initial_state_hash(self) -> str:
        return sha256_payload(self._initial_state)

    @property
    def event_commitment_hash(self) -> str:
        return sha256_payload([item.to_dict() for item in self._scheduled_events])

    @property
    def event_log_hash(self) -> str:
        return sha256_payload([event.to_dict() for event in self._events])

    @property
    def events(self) -> tuple[WorldEventV1, ...]:
        return tuple(self._events)

    def record(
        self,
        *,
        event_type: str,
        actor_id: str,
        payload: Mapping[str, Any],
        causal_parent_ids: tuple[str, ...] = (),
    ) -> WorldEventV1:
        event = WorldEventV1(
            event_id=self._event_id(
                ordinal=len(self._events),
                event_type=event_type,
                virtual_tick=self._virtual_tick,
                actor_id=actor_id,
                payload=payload,
                causal_parent_ids=causal_parent_ids,
            ),
            event_type=event_type,
            virtual_tick=self._virtual_tick,
            actor_id=actor_id,
            payload=payload,
            causal_parent_ids=causal_parent_ids,
        )
        self._events.append(event)
        return event

    def validate_event_log(self) -> None:
        """Reject any event whose identity is not bound to its exact body."""
        previous_tick = 0
        known_ids: set[str] = set()
        for ordinal, event in enumerate(self._events):
            if event.virtual_tick < previous_tick:
                raise ValueError("event log virtual time moved backwards")
            if any(parent not in known_ids for parent in event.causal_parent_ids):
                raise ValueError("event log contains an unknown causal parent")
            expected_id = self._event_id(
                ordinal=ordinal,
                event_type=event.event_type,
                virtual_tick=event.virtual_tick,
                actor_id=event.actor_id,
                payload=event.payload,
                causal_parent_ids=event.causal_parent_ids,
            )
            if event.event_id != expected_id:
                raise ValueError("event log body hash or ordinal does not match event_id")
            known_ids.add(event.event_id)
            previous_tick = event.virtual_tick

    def _event_id(
        self,
        *,
        ordinal: int,
        event_type: str,
        virtual_tick: int,
        actor_id: str,
        payload: Mapping[str, Any],
        causal_parent_ids: tuple[str, ...],
    ) -> str:
        return "event:" + sha256_payload(
            {
                "world_id": self.world_id,
                "ordinal": ordinal,
                "event_type": event_type,
                "virtual_tick": virtual_tick,
                "actor_id": actor_id,
                "payload": dict(payload),
                "parents": list(causal_parent_ids),
            }
        ).split(":", 1)[1][:24]

    def advance_to(self, tick: int) -> tuple[WorldEventV1, ...]:
        if not isinstance(tick, int) or tick < self._virtual_tick:
            raise ValueError("virtual time must advance monotonically")
        emitted: list[WorldEventV1] = []
        for scheduled in self._scheduled_events:
            if scheduled.schedule_id in self._applied_schedule_ids or scheduled.due_tick > tick:
                continue
            self._virtual_tick = scheduled.due_tick
            handler = self._event_handlers.get(scheduled.event_type)
            if handler is None:
                raise ValueError("scheduled event handler is missing: " + scheduled.event_type)
            handler(self._state, scheduled)
            emitted.append(
                self.record(
                    event_type=scheduled.event_type,
                    actor_id=scheduled.actor_id,
                    payload={
                        "schedule_id": scheduled.schedule_id,
                        "payload_hash": sha256_payload(scheduled.payload),
                    },
                )
            )
            self._applied_schedule_ids.add(scheduled.schedule_id)
        self._virtual_tick = tick
        return tuple(emitted)

    def snapshot_payload(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "initial_state": copy.deepcopy(self._initial_state),
            "state": copy.deepcopy(self._state),
            "virtual_tick": self._virtual_tick,
            "scheduled_events": [item.to_dict() for item in self._scheduled_events],
            "applied_schedule_ids": sorted(self._applied_schedule_ids),
            "events": [event.to_dict() for event in self._events],
        }

    @property
    def snapshot_hash(self) -> str:
        return sha256_payload(self.snapshot_payload())

    def fork(self) -> "EventSourcedWorld":
        clone = EventSourcedWorld(
            world_id=self.world_id,
            initial_state=self._initial_state,
            scheduled_events=self._scheduled_events,
            event_handlers=self._event_handlers,
        )
        clone._state = copy.deepcopy(self._state)
        clone._virtual_tick = self._virtual_tick
        clone._events = list(self._events)
        clone._applied_schedule_ids = set(self._applied_schedule_ids)
        return clone

    @classmethod
    def restore(
        cls,
        snapshot: Mapping[str, Any],
        *,
        event_handlers: Mapping[str, EventHandler] | None = None,
    ) -> "EventSourcedWorld":
        """Restore an exact snapshot by replaying the committed schedule.

        The serialized state is only an integrity claim. Restore rebuilds the
        world from initial state, scheduled events, handlers, and virtual time,
        then rejects any mismatch in state, applied schedules, or emitted log.
        """
        if not isinstance(snapshot, Mapping):
            raise ValueError("world snapshot must be a mapping")
        schedules: list[ScheduledWorldEventV1] = []
        for raw in snapshot.get("scheduled_events") or ():
            if not isinstance(raw, Mapping):
                raise ValueError("scheduled event snapshot item must be a mapping")
            schedules.append(
                ScheduledWorldEventV1(
                    schedule_id=str(raw.get("schedule_id") or ""),
                    event_type=str(raw.get("event_type") or ""),
                    due_tick=raw.get("due_tick"),
                    payload=raw.get("payload") or {},
                    actor_id=str(raw.get("actor_id") or "world_scheduler"),
                )
            )
        state = snapshot.get("state")
        if not isinstance(state, Mapping):
            raise ValueError("world snapshot state must be a mapping")
        tick = snapshot.get("virtual_tick")
        if not isinstance(tick, int) or tick < 0:
            raise ValueError("world snapshot virtual_tick is invalid")
        applied = snapshot.get("applied_schedule_ids")
        if not isinstance(applied, list) or not all(isinstance(item, str) for item in applied):
            raise ValueError("world snapshot applied_schedule_ids is invalid")
        if len(applied) != len(set(applied)):
            raise ValueError("world snapshot applied_schedule_ids contains duplicates")
        allowed_schedule_ids = {item.schedule_id for item in schedules}
        if not set(applied).issubset(allowed_schedule_ids):
            raise ValueError("world snapshot references an unknown scheduled event")
        events: list[WorldEventV1] = []
        for raw in snapshot.get("events") or ():
            if not isinstance(raw, Mapping):
                raise ValueError("world snapshot event must be a mapping")
            events.append(
                WorldEventV1(
                    event_id=str(raw.get("event_id") or ""),
                    event_type=str(raw.get("event_type") or ""),
                    virtual_tick=raw.get("virtual_tick"),
                    actor_id=str(raw.get("actor_id") or ""),
                    payload=raw.get("payload") or {},
                    causal_parent_ids=tuple(raw.get("causal_parent_ids") or ()),
                )
            )
        claimed_log_world = cls(
            world_id=str(snapshot.get("world_id") or ""),
            initial_state=snapshot.get("initial_state") or {},
            scheduled_events=tuple(schedules),
            event_handlers=event_handlers,
        )
        claimed_log_world._events = events
        claimed_log_world.validate_event_log()

        world = cls(
            world_id=str(snapshot.get("world_id") or ""),
            initial_state=snapshot.get("initial_state") or {},
            scheduled_events=tuple(schedules),
            event_handlers=event_handlers,
        )
        world.advance_to(tick)

        replayed_applied = sorted(world._applied_schedule_ids)
        if replayed_applied != applied:
            raise ValueError("world snapshot applied_schedule_ids do not match replay")
        if [event.to_dict() for event in world._events] != [event.to_dict() for event in events]:
            raise ValueError("world snapshot event log does not match replay")
        if world._state != copy.deepcopy(dict(state)):
            raise ValueError("world snapshot state does not match replay")
        return world

    def binding(
        self,
        *,
        world_build_hash: str,
        source_bundle_hash: str,
        agent_view: Mapping[str, Any],
        fault_commitment_hash: str,
    ) -> WorldSnapshotBindingV1:
        return WorldSnapshotBindingV1(
            world_id=self.world_id,
            world_build_hash=world_build_hash,
            source_bundle_hash=source_bundle_hash,
            agent_view_hash=sha256_payload(agent_view),
            initial_state_hash=self.initial_state_hash,
            event_commitment_hash=self.event_commitment_hash,
            fault_commitment_hash=fault_commitment_hash,
        )

    def canonical_snapshot_json(self) -> str:
        return canonical_json(self.snapshot_payload())
