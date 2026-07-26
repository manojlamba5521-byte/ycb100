"""Portable SQLite store for canonical consequence lifecycle execution."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.contracts import (
    ActionIdentityV1,
    ActionSnapshotV1,
    LifecycleState,
    bounded_identifier,
    canonical_json,
    sha256_payload,
    validate_expected_state_version,
    validate_transition,
)


class LifecycleStoreError(RuntimeError):
    """Base class for fail-closed lifecycle store failures."""


class LifecycleConflict(LifecycleStoreError):
    pass


class ActionIdentityConflict(LifecycleStoreError):
    pass


class ReservationConflict(LifecycleStoreError):
    pass


class CommandConflict(LifecycleStoreError):
    pass


class VerificationBlocked(LifecycleStoreError):
    pass


_CommandBody = Callable[[sqlite3.Connection], dict[str, Any]]
_RECEIPT_TABLES = (
    "transitions",
    "prepared_attempts",
    "reservations",
    "connector_invocations",
    "source_effects",
    "readbacks",
    "obligation_receipts",
    "compensation_receipts",
    "commands",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _bounded_text(value: object, field_name: str, *, maximum: int = 2048) -> str:
    if not isinstance(value, str):
        raise ValueError(field_name + " must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(field_name + " must be bounded non-empty text")
    return normalized


def _receipt(
    *,
    receipt_kind: str,
    action_id: str,
    command_id: str,
    body: Mapping[str, Any],
) -> tuple[str, str]:
    payload = {
        "receipt_kind": receipt_kind,
        "action_id": action_id,
        "command_id": command_id,
        "body": dict(body),
    }
    receipt_hash = sha256_payload(payload)
    return receipt_kind.lower() + ":" + receipt_hash[7:39], receipt_hash


class ConsequenceLifecycleStore:
    """Explicit-close SQLite lifecycle store with atomic, replayable commands."""

    def __init__(self, database_path: str | Path, *, busy_timeout_ms: int = 10_000) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        if not isinstance(busy_timeout_ms, int) or isinstance(busy_timeout_ms, bool) or busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be a positive integer")
        self.busy_timeout_ms = busy_timeout_ms
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA busy_timeout = " + str(self.busy_timeout_ms))
        return connection

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._new_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        connection = self._new_connection()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target_json TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    effect_fingerprint TEXT NOT NULL,
                    identity_hash TEXT NOT NULL,
                    current_state TEXT NOT NULL,
                    state_version INTEGER NOT NULL CHECK (state_version >= 0),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transitions (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    from_version INTEGER,
                    to_version INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(action_id, to_version)
                );

                CREATE TABLE IF NOT EXISTS prepared_attempts (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    attempt_id TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL UNIQUE REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    action_identity_hash TEXT NOT NULL,
                    effect_fingerprint TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    prepared_state_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reservations (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    reservation_id TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL UNIQUE REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    semantic_key TEXT NOT NULL UNIQUE,
                    effect_fingerprint TEXT NOT NULL UNIQUE,
                    prepared_attempt_id TEXT NOT NULL REFERENCES prepared_attempts(attempt_id),
                    reserved_state_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS connector_invocations (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    invocation_id TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL REFERENCES prepared_attempts(attempt_id),
                    reservation_id TEXT NOT NULL REFERENCES reservations(reservation_id),
                    effect_fingerprint TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    dispatch_state_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(action_id, attempt_id)
                );

                CREATE TABLE IF NOT EXISTS source_effects (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    effect_fingerprint TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    source_effect_id TEXT NOT NULL,
                    source_payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_system, source_effect_id)
                );

                CREATE TABLE IF NOT EXISTS readbacks (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    readback_id TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    claimed_effect_fingerprint TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    source_effect_id TEXT NOT NULL,
                    source_payload_hash TEXT NOT NULL,
                    observed INTEGER NOT NULL CHECK (observed IN (0, 1)),
                    exact_binding INTEGER NOT NULL CHECK (exact_binding IN (0, 1)),
                    admitted_state_version INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS obligation_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    obligation_id TEXT NOT NULL,
                    action_id TEXT NOT NULL REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (event_type IN ('OPENED', 'DISCHARGED', 'FAILED')),
                    owner_id TEXT NOT NULL,
                    deadline TEXT NOT NULL,
                    effect_fingerprint TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    supersedes_receipt_hash TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS obligation_action_idx
                    ON obligation_receipts(action_id, obligation_id, created_at);

                CREATE TABLE IF NOT EXISTS compensation_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    compensation_id TEXT NOT NULL,
                    action_id TEXT NOT NULL REFERENCES actions(action_id),
                    command_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (
                        event_type IN ('REQUIRED', 'STARTED', 'VERIFIED', 'FAILED')
                    ),
                    original_source_effect_id TEXT NOT NULL,
                    compensation_effect_id TEXT,
                    source_system TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    supersedes_receipt_hash TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS compensation_action_idx
                    ON compensation_receipts(action_id, compensation_id, created_at);

                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS actions_identity_immutable
                BEFORE UPDATE OF
                    action_id, tenant_id, connector_id, source_system, action_type,
                    target_json, parameters_json, effect_fingerprint, identity_hash, created_at
                ON actions
                BEGIN
                    SELECT RAISE(ABORT, 'action_identity_is_immutable');
                END;
                """
            )
            for table in _RECEIPT_TABLES:
                connection.executescript(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS {table}_append_only_update
                    BEFORE UPDATE ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, '{table}_is_append_only');
                    END;
                    CREATE TRIGGER IF NOT EXISTS {table}_append_only_delete
                    BEFORE DELETE ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, '{table}_is_append_only');
                    END;
                    """
                )
        finally:
            connection.close()

    def create_action(
        self,
        identity: ActionIdentityV1,
        *,
        expected_state_version: int,
        command_id: str,
    ) -> dict[str, Any]:
        if not isinstance(identity, ActionIdentityV1):
            raise ValueError("identity must be ActionIdentityV1")
        expected = validate_expected_state_version(expected_state_version, allow_creation=True)
        if expected != -1:
            raise ValueError("action creation requires expected_state_version=-1")
        command = bounded_identifier(command_id, "command_id")
        request = {
            "identity": identity.to_dict(),
            "expected_state_version": expected,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            existing = connection.execute(
                "SELECT identity_hash FROM actions WHERE action_id = ?",
                (identity.action_id,),
            ).fetchone()
            if existing is not None:
                if existing["identity_hash"] != identity.identity_hash:
                    raise ActionIdentityConflict("action_id is bound to a different immutable identity")
                raise LifecycleConflict("action already exists under a different command")
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO actions (
                    action_id, tenant_id, connector_id, source_system, action_type,
                    target_json, parameters_json, effect_fingerprint, identity_hash,
                    current_state, state_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    identity.action_id,
                    identity.tenant_id,
                    identity.connector_id,
                    identity.source_system,
                    identity.action_type,
                    identity.target_json,
                    identity.parameters_json,
                    identity.effect_fingerprint,
                    identity.identity_hash,
                    LifecycleState.PROPOSED.value,
                    now,
                ),
            )
            transition = self._insert_transition_receipt(
                connection,
                action_id=identity.action_id,
                command_id=command,
                from_state=None,
                to_state=LifecycleState.PROPOSED,
                from_version=None,
                to_version=0,
                reason="canonical_action_created",
                created_at=now,
            )
            return {
                "action": self._load_snapshot(connection, identity.action_id).to_dict(),
                "transition": transition,
            }

        return self._execute_command(
            action_id=identity.action_id,
            command_id=command,
            command_type="create_action",
            request=request,
            body=body,
        )

    def prepare_action(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        attempt_id: str,
        prepared_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        attempt = bounded_identifier(attempt_id, "attempt_id")
        expected = validate_expected_state_version(expected_state_version)
        payload_hash = sha256_payload(prepared_payload)
        request = {
            "expected_state_version": expected,
            "attempt_id": attempt,
            "payload_hash": payload_hash,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.PROPOSED,
            )
            now = _utc_now()
            receipt_body = {
                "attempt_id": attempt,
                "action_identity_hash": snapshot.identity.identity_hash,
                "effect_fingerprint": snapshot.identity.effect_fingerprint,
                "payload_hash": payload_hash,
                "prepared_state_version": expected + 1,
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="PREPARED_ATTEMPT",
                action_id=action,
                command_id=command,
                body=receipt_body,
            )
            connection.execute(
                """
                INSERT INTO prepared_attempts (
                    receipt_id, receipt_hash, attempt_id, action_id, command_id,
                    action_identity_hash, effect_fingerprint, payload_hash,
                    prepared_state_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    receipt_hash,
                    attempt,
                    action,
                    command,
                    snapshot.identity.identity_hash,
                    snapshot.identity.effect_fingerprint,
                    payload_hash,
                    expected + 1,
                    now,
                ),
            )
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.PREPARED,
                reason="prepared_attempt_persisted",
                created_at=now,
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "prepared_attempt": {
                    **receipt_body,
                    "receipt_id": receipt_id,
                    "receipt_hash": receipt_hash,
                },
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="prepare_action",
            request=request,
            body=body,
        )

    def reserve_effect(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        reservation_id: str,
        semantic_key: str,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        reservation = bounded_identifier(reservation_id, "reservation_id")
        semantic = bounded_identifier(semantic_key, "semantic_key")
        expected = validate_expected_state_version(expected_state_version)
        request = {
            "expected_state_version": expected,
            "reservation_id": reservation,
            "semantic_key": semantic,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.PREPARED,
            )
            prepared = connection.execute(
                "SELECT attempt_id FROM prepared_attempts WHERE action_id = ?",
                (action,),
            ).fetchone()
            if prepared is None:
                raise LifecycleConflict("reservation requires a persisted prepared attempt")
            now = _utc_now()
            receipt_body = {
                "reservation_id": reservation,
                "semantic_key": semantic,
                "effect_fingerprint": snapshot.identity.effect_fingerprint,
                "prepared_attempt_id": prepared["attempt_id"],
                "reserved_state_version": expected + 1,
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="RESERVATION",
                action_id=action,
                command_id=command,
                body=receipt_body,
            )
            try:
                connection.execute(
                    """
                    INSERT INTO reservations (
                        receipt_id, receipt_hash, reservation_id, action_id, command_id,
                        semantic_key, effect_fingerprint, prepared_attempt_id,
                        reserved_state_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        receipt_hash,
                        reservation,
                        action,
                        command,
                        semantic,
                        snapshot.identity.effect_fingerprint,
                        prepared["attempt_id"],
                        expected + 1,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ReservationConflict("semantic or effect reservation is already owned") from exc
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.RESERVED,
                reason="effect_identity_reserved",
                created_at=now,
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "reservation": {
                    **receipt_body,
                    "receipt_id": receipt_id,
                    "receipt_hash": receipt_hash,
                },
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="reserve_effect",
            request=request,
            body=body,
        )

    def begin_dispatch(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        invocation_id: str,
        connector_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        invocation = bounded_identifier(invocation_id, "invocation_id")
        expected = validate_expected_state_version(expected_state_version)
        request_hash = sha256_payload(connector_request)
        request = {
            "expected_state_version": expected,
            "invocation_id": invocation,
            "connector_request_hash": request_hash,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.RESERVED,
            )
            prepared = connection.execute(
                "SELECT attempt_id FROM prepared_attempts WHERE action_id = ?",
                (action,),
            ).fetchone()
            reservation = connection.execute(
                "SELECT reservation_id FROM reservations WHERE action_id = ?",
                (action,),
            ).fetchone()
            if prepared is None or reservation is None:
                raise LifecycleConflict("dispatch requires prepared attempt and effect reservation")
            now = _utc_now()
            receipt_body = {
                "invocation_id": invocation,
                "attempt_id": prepared["attempt_id"],
                "reservation_id": reservation["reservation_id"],
                "effect_fingerprint": snapshot.identity.effect_fingerprint,
                "connector_id": snapshot.identity.connector_id,
                "request_hash": request_hash,
                "dispatch_state_version": expected + 1,
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="CONNECTOR_INVOCATION",
                action_id=action,
                command_id=command,
                body=receipt_body,
            )
            connection.execute(
                """
                INSERT INTO connector_invocations (
                    receipt_id, receipt_hash, invocation_id, action_id, command_id,
                    attempt_id, reservation_id, effect_fingerprint, connector_id,
                    request_hash, dispatch_state_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    receipt_hash,
                    invocation,
                    action,
                    command,
                    prepared["attempt_id"],
                    reservation["reservation_id"],
                    snapshot.identity.effect_fingerprint,
                    snapshot.identity.connector_id,
                    request_hash,
                    expected + 1,
                    now,
                ),
            )
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.DISPATCHING,
                reason="connector_invocation_persisted_before_dispatch",
                created_at=now,
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "connector_invocation": {
                    **receipt_body,
                    "receipt_id": receipt_id,
                    "receipt_hash": receipt_hash,
                },
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="begin_dispatch",
            request=request,
            body=body,
        )

    def record_dispatch_outcome(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        outcome: LifecycleState,
        outcome_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        if outcome not in {
            LifecycleState.EXECUTION_UNKNOWN,
            LifecycleState.COMMITTED,
            LifecycleState.EXECUTION_FAILED,
        }:
            raise ValueError("dispatch outcome is invalid")
        return self._simple_transition_command(
            action_id=action_id,
            expected_state_version=expected_state_version,
            command_id=command_id,
            command_type="record_dispatch_outcome",
            required_state=LifecycleState.DISPATCHING,
            target_state=outcome,
            reason="dispatch_outcome:" + sha256_payload(outcome_evidence),
        )

    def begin_readback(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        expected = validate_expected_state_version(expected_state_version)
        request = {"expected_state_version": expected}

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._load_snapshot(connection, action)
            if snapshot.state not in {LifecycleState.COMMITTED, LifecycleState.EXECUTION_UNKNOWN}:
                raise LifecycleConflict("readback requires committed or uncertain execution")
            if snapshot.state_version != expected:
                raise LifecycleConflict("expected_state_version mismatch")
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.READBACK_PENDING,
                reason="independent_source_readback_started",
                created_at=_utc_now(),
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="begin_readback",
            request=request,
            body=body,
        )

    def record_source_effect(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        source_system: str,
        source_effect_id: str,
        source_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        source = bounded_identifier(source_system, "source_system")
        source_effect = bounded_identifier(source_effect_id, "source_effect_id")
        expected = validate_expected_state_version(expected_state_version)
        payload_hash = sha256_payload(source_payload)
        request = {
            "expected_state_version": expected,
            "source_system": source,
            "source_effect_id": source_effect,
            "source_payload_hash": payload_hash,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._load_snapshot(connection, action)
            if snapshot.state_version != expected:
                raise LifecycleConflict("expected_state_version mismatch")
            if snapshot.state not in {
                LifecycleState.COMMITTED,
                LifecycleState.EXECUTION_UNKNOWN,
                LifecycleState.READBACK_PENDING,
            }:
                raise LifecycleConflict("source effect cannot be recorded in the current state")
            if source != snapshot.identity.source_system:
                raise VerificationBlocked("source effect is not from the action's bound source system")
            receipt_body = {
                "effect_fingerprint": snapshot.identity.effect_fingerprint,
                "source_system": source,
                "source_effect_id": source_effect,
                "source_payload_hash": payload_hash,
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="SOURCE_EFFECT",
                action_id=action,
                command_id=command,
                body=receipt_body,
            )
            try:
                connection.execute(
                    """
                    INSERT INTO source_effects (
                        receipt_id, receipt_hash, action_id, command_id,
                        effect_fingerprint, source_system, source_effect_id,
                        source_payload_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        receipt_hash,
                        action,
                        command,
                        snapshot.identity.effect_fingerprint,
                        source,
                        source_effect,
                        payload_hash,
                        _utc_now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LifecycleConflict("source effect identity already exists") from exc
            return {
                "action": snapshot.to_dict(),
                "source_effect": {
                    **receipt_body,
                    "receipt_id": receipt_id,
                    "receipt_hash": receipt_hash,
                },
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="record_source_effect",
            request=request,
            body=body,
        )

    def admit_readback(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        readback_id: str,
        claimed_effect_fingerprint: str,
        source_system: str,
        source_effect_id: str,
        source_payload: Mapping[str, Any],
        observed: bool,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        readback = bounded_identifier(readback_id, "readback_id")
        source = bounded_identifier(source_system, "source_system")
        source_effect = bounded_identifier(source_effect_id, "source_effect_id")
        claim = _bounded_text(claimed_effect_fingerprint, "claimed_effect_fingerprint", maximum=80)
        if not claim.startswith("sha256:") or len(claim) != 71:
            raise ValueError("claimed_effect_fingerprint must be a sha256 digest")
        if not isinstance(observed, bool):
            raise ValueError("observed must be boolean")
        expected = validate_expected_state_version(expected_state_version)
        payload_hash = sha256_payload(source_payload)
        request = {
            "expected_state_version": expected,
            "readback_id": readback,
            "claimed_effect_fingerprint": claim,
            "source_system": source,
            "source_effect_id": source_effect,
            "source_payload_hash": payload_hash,
            "observed": observed,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.READBACK_PENDING,
            )
            source_row = connection.execute(
                """
                SELECT action_id, effect_fingerprint, source_system, source_payload_hash
                FROM source_effects
                WHERE source_system = ? AND source_effect_id = ?
                """,
                (source, source_effect),
            ).fetchone()
            exact = bool(
                observed
                and source_row is not None
                and source_row["action_id"] == action
                and source_row["effect_fingerprint"] == snapshot.identity.effect_fingerprint
                and claim == snapshot.identity.effect_fingerprint
                and source == snapshot.identity.source_system
                and source_row["source_payload_hash"] == payload_hash
            )
            admitted_version = expected + 1 if exact else None
            receipt_body = {
                "readback_id": readback,
                "claimed_effect_fingerprint": claim,
                "source_system": source,
                "source_effect_id": source_effect,
                "source_payload_hash": payload_hash,
                "observed": observed,
                "exact_binding": exact,
                "admitted_state_version": admitted_version,
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="READBACK",
                action_id=action,
                command_id=command,
                body=receipt_body,
            )
            connection.execute(
                """
                INSERT INTO readbacks (
                    receipt_id, receipt_hash, readback_id, action_id, command_id,
                    claimed_effect_fingerprint, source_system, source_effect_id,
                    source_payload_hash, observed, exact_binding,
                    admitted_state_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    receipt_hash,
                    readback,
                    action,
                    command,
                    claim,
                    source,
                    source_effect,
                    payload_hash,
                    int(observed),
                    int(exact),
                    admitted_version,
                    _utc_now(),
                ),
            )
            transition = None
            if exact:
                transition = self._transition(
                    connection,
                    snapshot=snapshot,
                    command_id=command,
                    target=LifecycleState.EFFECT_VERIFIED,
                    reason="exact_action_effect_source_readback",
                    created_at=_utc_now(),
                )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "readback": {
                    **receipt_body,
                    "receipt_id": receipt_id,
                    "receipt_hash": receipt_hash,
                },
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="admit_readback",
            request=request,
            body=body,
        )

    def open_obligation(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        obligation_id: str,
        owner_id: str,
        deadline: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        obligation = bounded_identifier(obligation_id, "obligation_id")
        owner = bounded_identifier(owner_id, "owner_id")
        due = _bounded_text(deadline, "deadline", maximum=128)
        expected = validate_expected_state_version(expected_state_version)
        evidence_hash = sha256_payload(evidence)
        request = {
            "expected_state_version": expected,
            "obligation_id": obligation,
            "owner_id": owner,
            "deadline": due,
            "evidence_hash": evidence_hash,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.EFFECT_VERIFIED,
            )
            receipt = self._append_obligation_receipt(
                connection,
                action_id=action,
                command_id=command,
                obligation_id=obligation,
                event_type="OPENED",
                owner_id=owner,
                deadline=due,
                effect_fingerprint=snapshot.identity.effect_fingerprint,
                evidence_hash=evidence_hash,
                supersedes_receipt_hash=None,
            )
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.OBLIGATION_OPEN,
                reason="durable_obligation_opened",
                created_at=_utc_now(),
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "obligation": receipt,
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="open_obligation",
            request=request,
            body=body,
        )

    def discharge_obligation(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        obligation_id: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        obligation = bounded_identifier(obligation_id, "obligation_id")
        expected = validate_expected_state_version(expected_state_version)
        evidence_hash = sha256_payload(evidence)
        request = {
            "expected_state_version": expected,
            "obligation_id": obligation,
            "evidence_hash": evidence_hash,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.OBLIGATION_OPEN,
            )
            prior = self._latest_obligation(connection, action, obligation)
            if prior is None or prior["event_type"] != "OPENED":
                raise VerificationBlocked("obligation discharge requires one open obligation")
            receipt = self._append_obligation_receipt(
                connection,
                action_id=action,
                command_id=command,
                obligation_id=obligation,
                event_type="DISCHARGED",
                owner_id=prior["owner_id"],
                deadline=prior["deadline"],
                effect_fingerprint=snapshot.identity.effect_fingerprint,
                evidence_hash=evidence_hash,
                supersedes_receipt_hash=prior["receipt_hash"],
            )
            return {"action": snapshot.to_dict(), "obligation": receipt}

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="discharge_obligation",
            request=request,
            body=body,
        )

    def verify_action(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        expected = validate_expected_state_version(expected_state_version)
        request = {"expected_state_version": expected}

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._load_snapshot(connection, action)
            if snapshot.state not in {LifecycleState.EFFECT_VERIFIED, LifecycleState.OBLIGATION_OPEN}:
                raise VerificationBlocked("VERIFIED requires EFFECT_VERIFIED or discharged obligations")
            if snapshot.state_version != expected:
                raise LifecycleConflict("expected_state_version mismatch")
            if not self._has_valid_exact_readback(connection, snapshot):
                raise VerificationBlocked("VERIFIED requires exact action/effect/source readback")
            if self._open_obligation_count(
                connection,
                action,
                snapshot.identity.effect_fingerprint,
            ):
                raise VerificationBlocked("VERIFIED is blocked while obligations remain open")
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.VERIFIED,
                reason="exact_source_truth_and_obligations_closed",
                created_at=_utc_now(),
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="verify_action",
            request=request,
            body=body,
        )

    def require_compensation(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        compensation_id: str,
        original_source_effect_id: str,
        reason_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        compensation = bounded_identifier(compensation_id, "compensation_id")
        original = bounded_identifier(original_source_effect_id, "original_source_effect_id")
        expected = validate_expected_state_version(expected_state_version)
        evidence_hash = sha256_payload(reason_evidence)
        request = {
            "expected_state_version": expected,
            "compensation_id": compensation,
            "original_source_effect_id": original,
            "evidence_hash": evidence_hash,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._load_snapshot(connection, action)
            if snapshot.state not in {
                LifecycleState.READBACK_PENDING,
                LifecycleState.EFFECT_VERIFIED,
                LifecycleState.OBLIGATION_OPEN,
            }:
                raise LifecycleConflict("compensation cannot be required in the current state")
            if snapshot.state_version != expected:
                raise LifecycleConflict("expected_state_version mismatch")
            source_effect = connection.execute(
                """
                SELECT 1 FROM source_effects
                WHERE action_id = ? AND source_effect_id = ? AND effect_fingerprint = ?
                """,
                (action, original, snapshot.identity.effect_fingerprint),
            ).fetchone()
            if source_effect is None:
                raise VerificationBlocked("compensation requires the bound original source effect")
            receipt = self._append_compensation_receipt(
                connection,
                action_id=action,
                command_id=command,
                compensation_id=compensation,
                event_type="REQUIRED",
                original_source_effect_id=original,
                compensation_effect_id=None,
                source_system=snapshot.identity.source_system,
                evidence_hash=evidence_hash,
                supersedes_receipt_hash=None,
            )
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.COMPENSATION_REQUIRED,
                reason="original_effect_requires_forward_compensation",
                created_at=_utc_now(),
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "compensation": receipt,
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="require_compensation",
            request=request,
            body=body,
        )

    def start_compensation(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        compensation_id: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        compensation = bounded_identifier(compensation_id, "compensation_id")
        expected = validate_expected_state_version(expected_state_version)
        evidence_hash = sha256_payload(evidence)
        request = {
            "expected_state_version": expected,
            "compensation_id": compensation,
            "evidence_hash": evidence_hash,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.COMPENSATION_REQUIRED,
            )
            prior = self._latest_compensation(connection, action, compensation)
            if prior is None or prior["event_type"] != "REQUIRED":
                raise VerificationBlocked("compensation start requires a REQUIRED receipt")
            receipt = self._append_compensation_receipt(
                connection,
                action_id=action,
                command_id=command,
                compensation_id=compensation,
                event_type="STARTED",
                original_source_effect_id=prior["original_source_effect_id"],
                compensation_effect_id=None,
                source_system=prior["source_system"],
                evidence_hash=evidence_hash,
                supersedes_receipt_hash=prior["receipt_hash"],
            )
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=LifecycleState.COMPENSATING,
                reason="compensation_attempt_started",
                created_at=_utc_now(),
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "compensation": receipt,
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="start_compensation",
            request=request,
            body=body,
        )

    def record_compensation_readback(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        compensation_id: str,
        compensation_effect_id: str,
        source_system: str,
        evidence: Mapping[str, Any],
        verified: bool,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        compensation = bounded_identifier(compensation_id, "compensation_id")
        compensation_effect = bounded_identifier(compensation_effect_id, "compensation_effect_id")
        source = bounded_identifier(source_system, "source_system")
        if not isinstance(verified, bool):
            raise ValueError("verified must be boolean")
        expected = validate_expected_state_version(expected_state_version)
        evidence_hash = sha256_payload(evidence)
        request = {
            "expected_state_version": expected,
            "compensation_id": compensation,
            "compensation_effect_id": compensation_effect,
            "source_system": source,
            "evidence_hash": evidence_hash,
            "verified": verified,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.COMPENSATING,
            )
            prior = self._latest_compensation(connection, action, compensation)
            if prior is None or prior["event_type"] != "STARTED":
                raise VerificationBlocked("compensation readback requires a STARTED receipt")
            if source != snapshot.identity.source_system:
                raise VerificationBlocked("compensation readback source is not bound to the action")
            event_type = "VERIFIED" if verified else "FAILED"
            receipt = self._append_compensation_receipt(
                connection,
                action_id=action,
                command_id=command,
                compensation_id=compensation,
                event_type=event_type,
                original_source_effect_id=prior["original_source_effect_id"],
                compensation_effect_id=compensation_effect,
                source_system=source,
                evidence_hash=evidence_hash,
                supersedes_receipt_hash=prior["receipt_hash"],
            )
            return {"action": snapshot.to_dict(), "compensation": receipt}

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="record_compensation_readback",
            request=request,
            body=body,
        )

    def complete_compensation(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        compensation_id: str,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        compensation = bounded_identifier(compensation_id, "compensation_id")
        expected = validate_expected_state_version(expected_state_version)
        request = {
            "expected_state_version": expected,
            "compensation_id": compensation,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(
                connection,
                action,
                expected,
                LifecycleState.COMPENSATING,
            )
            latest = self._latest_compensation(connection, action, compensation)
            if latest is None or latest["event_type"] not in {"VERIFIED", "FAILED"}:
                raise VerificationBlocked("compensation terminal state requires source readback")
            target = (
                LifecycleState.COMPENSATED
                if latest["event_type"] == "VERIFIED"
                else LifecycleState.COMPENSATION_FAILED
            )
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=target,
                reason="compensation_source_readback:" + latest["event_type"].lower(),
                created_at=_utc_now(),
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type="complete_compensation",
            request=request,
            body=body,
        )

    def deny_action(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        reason: str,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        expected = validate_expected_state_version(expected_state_version)
        current = self.get_action(action)
        if current.state not in {LifecycleState.PROPOSED, LifecycleState.PREPARED}:
            raise LifecycleConflict("deny is allowed only before reservation")
        return self._simple_transition_command(
            action_id=action,
            expected_state_version=expected,
            command_id=command_id,
            command_type="deny_action",
            required_state=current.state,
            target_state=LifecycleState.DENIED,
            reason="denied:" + _bounded_text(reason, "reason"),
        )

    def revoke_reservation(
        self,
        action_id: str,
        *,
        expected_state_version: int,
        command_id: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._simple_transition_command(
            action_id=action_id,
            expected_state_version=expected_state_version,
            command_id=command_id,
            command_type="revoke_reservation",
            required_state=LifecycleState.RESERVED,
            target_state=LifecycleState.REVOKED,
            reason="revoked:" + _bounded_text(reason, "reason"),
        )

    def get_action(self, action_id: str) -> ActionSnapshotV1:
        action = bounded_identifier(action_id, "action_id")
        with self._read_connection() as connection:
            return self._load_snapshot(connection, action)

    def receipts(self, table: str, *, action_id: str) -> tuple[dict[str, Any], ...]:
        allowed = {
            "transitions",
            "prepared_attempts",
            "reservations",
            "connector_invocations",
            "source_effects",
            "readbacks",
            "obligation_receipts",
            "compensation_receipts",
        }
        if table not in allowed:
            raise ValueError("receipt table is not public")
        action = bounded_identifier(action_id, "action_id")
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM " + table + " WHERE action_id = ? ORDER BY rowid",
                (action,),
            ).fetchall()
            return tuple(dict(row) for row in rows)

    def _simple_transition_command(
        self,
        *,
        action_id: str,
        expected_state_version: int,
        command_id: str,
        command_type: str,
        required_state: LifecycleState,
        target_state: LifecycleState,
        reason: str,
    ) -> dict[str, Any]:
        action = bounded_identifier(action_id, "action_id")
        command = bounded_identifier(command_id, "command_id")
        expected = validate_expected_state_version(expected_state_version)
        request = {
            "expected_state_version": expected,
            "target_state": target_state.value,
            "reason": reason,
        }

        def body(connection: sqlite3.Connection) -> dict[str, Any]:
            snapshot = self._require_snapshot(connection, action, expected, required_state)
            transition = self._transition(
                connection,
                snapshot=snapshot,
                command_id=command,
                target=target_state,
                reason=reason,
                created_at=_utc_now(),
            )
            return {
                "action": self._load_snapshot(connection, action).to_dict(),
                "transition": transition,
            }

        return self._execute_command(
            action_id=action,
            command_id=command,
            command_type=command_type,
            request=request,
            body=body,
        )

    def _execute_command(
        self,
        *,
        action_id: str,
        command_id: str,
        command_type: str,
        request: Mapping[str, Any],
        body: _CommandBody,
    ) -> dict[str, Any]:
        request_hash = sha256_payload(request)
        with self._write_connection() as connection:
            existing = connection.execute(
                """
                SELECT action_id, command_type, request_hash, result_json
                FROM commands WHERE command_id = ?
                """,
                (command_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["action_id"] != action_id
                    or existing["command_type"] != command_type
                    or existing["request_hash"] != request_hash
                ):
                    raise CommandConflict("command_id was reused with a different command")
                return dict(json.loads(existing["result_json"]))
            result = body(connection)
            result_json = canonical_json(result)
            connection.execute(
                """
                INSERT INTO commands (
                    command_id, action_id, command_type, request_hash,
                    result_json, committed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    action_id,
                    command_type,
                    request_hash,
                    result_json,
                    _utc_now(),
                ),
            )
            return dict(json.loads(result_json))

    def _load_snapshot(self, connection: sqlite3.Connection, action_id: str) -> ActionSnapshotV1:
        row = connection.execute(
            "SELECT * FROM actions WHERE action_id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            raise LifecycleConflict("action does not exist")
        identity = ActionIdentityV1(
            action_id=row["action_id"],
            tenant_id=row["tenant_id"],
            connector_id=row["connector_id"],
            source_system=row["source_system"],
            action_type=row["action_type"],
            target_json=row["target_json"],
            parameters_json=row["parameters_json"],
        )
        if identity.identity_hash != row["identity_hash"] or identity.effect_fingerprint != row["effect_fingerprint"]:
            raise ActionIdentityConflict("persisted action identity failed canonical revalidation")
        self._validate_transition_history(
            connection,
            action_id=action_id,
            current_state=LifecycleState(row["current_state"]),
            state_version=row["state_version"],
        )
        return ActionSnapshotV1(
            identity=identity,
            state=LifecycleState(row["current_state"]),
            state_version=row["state_version"],
        )

    def _validate_transition_history(
        self,
        connection: sqlite3.Connection,
        *,
        action_id: str,
        current_state: LifecycleState,
        state_version: int,
    ) -> None:
        rows = connection.execute(
            """
            SELECT * FROM transitions
            WHERE action_id = ? ORDER BY to_version
            """,
            (action_id,),
        ).fetchall()
        if not rows:
            raise LifecycleConflict("action has no creation transition receipt")
        previous_state: LifecycleState | None = None
        previous_version: int | None = None
        for ordinal, row in enumerate(rows):
            to_state = LifecycleState(row["to_state"])
            from_state = LifecycleState(row["from_state"]) if row["from_state"] else None
            if ordinal == 0:
                if (
                    from_state is not None
                    or row["from_version"] is not None
                    or to_state != LifecycleState.PROPOSED
                    or row["to_version"] != 0
                ):
                    raise LifecycleConflict("action creation transition receipt is invalid")
            else:
                if (
                    from_state != previous_state
                    or row["from_version"] != previous_version
                    or row["to_version"] != previous_version + 1
                ):
                    raise LifecycleConflict("transition receipt chain is discontinuous")
                try:
                    validate_transition(from_state, to_state)
                except ValueError as exc:
                    raise LifecycleConflict("transition receipt chain contains an illegal transition") from exc
            body = {
                "from_state": from_state.value if from_state else None,
                "to_state": to_state.value,
                "from_version": row["from_version"],
                "to_version": row["to_version"],
                "reason": row["reason"],
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="TRANSITION",
                action_id=action_id,
                command_id=row["command_id"],
                body=body,
            )
            if row["receipt_id"] != receipt_id or row["receipt_hash"] != receipt_hash:
                raise LifecycleConflict("transition receipt hash validation failed")
            previous_state = to_state
            previous_version = row["to_version"]
        if previous_state != current_state or previous_version != state_version:
            raise LifecycleConflict("materialized action state contradicts transition receipts")

    def _require_snapshot(
        self,
        connection: sqlite3.Connection,
        action_id: str,
        expected_state_version: int,
        required_state: LifecycleState,
    ) -> ActionSnapshotV1:
        snapshot = self._load_snapshot(connection, action_id)
        if snapshot.state_version != expected_state_version:
            raise LifecycleConflict("expected_state_version mismatch")
        if snapshot.state != required_state:
            raise LifecycleConflict(
                "action state mismatch: expected "
                + required_state.value
                + ", found "
                + snapshot.state.value
            )
        return snapshot

    def _transition(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot: ActionSnapshotV1,
        command_id: str,
        target: LifecycleState,
        reason: str,
        created_at: str,
    ) -> dict[str, Any]:
        try:
            validate_transition(snapshot.state, target)
        except ValueError as exc:
            raise LifecycleConflict(str(exc)) from exc
        next_version = snapshot.state_version + 1
        updated = connection.execute(
            """
            UPDATE actions SET current_state = ?, state_version = ?
            WHERE action_id = ? AND current_state = ? AND state_version = ?
            """,
            (
                target.value,
                next_version,
                snapshot.identity.action_id,
                snapshot.state.value,
                snapshot.state_version,
            ),
        )
        if updated.rowcount != 1:
            raise LifecycleConflict("atomic state transition compare-and-swap failed")
        return self._insert_transition_receipt(
            connection,
            action_id=snapshot.identity.action_id,
            command_id=command_id,
            from_state=snapshot.state,
            to_state=target,
            from_version=snapshot.state_version,
            to_version=next_version,
            reason=reason,
            created_at=created_at,
        )

    def _insert_transition_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        action_id: str,
        command_id: str,
        from_state: LifecycleState | None,
        to_state: LifecycleState,
        from_version: int | None,
        to_version: int,
        reason: str,
        created_at: str,
    ) -> dict[str, Any]:
        body = {
            "from_state": from_state.value if from_state else None,
            "to_state": to_state.value,
            "from_version": from_version,
            "to_version": to_version,
            "reason": reason,
        }
        receipt_id, receipt_hash = _receipt(
            receipt_kind="TRANSITION",
            action_id=action_id,
            command_id=command_id,
            body=body,
        )
        connection.execute(
            """
            INSERT INTO transitions (
                receipt_id, receipt_hash, action_id, command_id, from_state,
                to_state, from_version, to_version, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                receipt_hash,
                action_id,
                command_id,
                body["from_state"],
                body["to_state"],
                from_version,
                to_version,
                reason,
                created_at,
            ),
        )
        return {**body, "receipt_id": receipt_id, "receipt_hash": receipt_hash}

    def _latest_obligation(
        self,
        connection: sqlite3.Connection,
        action_id: str,
        obligation_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM obligation_receipts
            WHERE action_id = ? AND obligation_id = ?
            ORDER BY rowid DESC LIMIT 1
            """,
            (action_id, obligation_id),
        ).fetchone()

    def _open_obligation_count(
        self,
        connection: sqlite3.Connection,
        action_id: str,
        effect_fingerprint: str,
    ) -> int:
        rows = connection.execute(
            """
            SELECT * FROM obligation_receipts
            WHERE action_id = ? ORDER BY rowid
            """,
            (action_id,),
        ).fetchall()
        latest: dict[str, str] = {}
        prior_hashes: dict[str, str] = {}
        for row in rows:
            obligation_id = row["obligation_id"]
            prior_hash = prior_hashes.get(obligation_id)
            if row["effect_fingerprint"] != effect_fingerprint:
                raise LifecycleConflict("obligation receipt effect binding is invalid")
            if row["event_type"] == "OPENED":
                if obligation_id in latest or row["supersedes_receipt_hash"] is not None:
                    raise LifecycleConflict("obligation opening receipt chain is invalid")
            elif latest.get(obligation_id) != "OPENED" or row["supersedes_receipt_hash"] != prior_hash:
                raise LifecycleConflict("obligation update receipt chain is invalid")
            body = {
                "obligation_id": obligation_id,
                "event_type": row["event_type"],
                "owner_id": row["owner_id"],
                "deadline": row["deadline"],
                "effect_fingerprint": row["effect_fingerprint"],
                "evidence_hash": row["evidence_hash"],
                "supersedes_receipt_hash": row["supersedes_receipt_hash"],
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="OBLIGATION_" + row["event_type"],
                action_id=action_id,
                command_id=row["command_id"],
                body=body,
            )
            if row["receipt_id"] != receipt_id or row["receipt_hash"] != receipt_hash:
                raise LifecycleConflict("obligation receipt hash validation failed")
            latest[obligation_id] = row["event_type"]
            prior_hashes[obligation_id] = row["receipt_hash"]
        return sum(event == "OPENED" for event in latest.values())

    def _has_valid_exact_readback(
        self,
        connection: sqlite3.Connection,
        snapshot: ActionSnapshotV1,
    ) -> bool:
        rows = connection.execute(
            """
            SELECT
                r.*,
                s.receipt_id AS source_receipt_id,
                s.receipt_hash AS source_receipt_hash,
                s.command_id AS source_command_id,
                s.action_id AS source_action_id,
                s.effect_fingerprint AS recorded_effect_fingerprint,
                s.source_system AS recorded_source_system,
                s.source_effect_id AS recorded_source_effect_id,
                s.source_payload_hash AS recorded_source_payload_hash
            FROM readbacks AS r
            LEFT JOIN source_effects AS s
              ON s.source_system = r.source_system
             AND s.source_effect_id = r.source_effect_id
            WHERE r.action_id = ?
              AND r.observed = 1
              AND r.exact_binding = 1
              AND r.admitted_state_version IS NOT NULL
            ORDER BY r.rowid
            """,
            (snapshot.identity.action_id,),
        ).fetchall()
        for row in rows:
            if (
                row["source_action_id"] != snapshot.identity.action_id
                or row["claimed_effect_fingerprint"] != snapshot.identity.effect_fingerprint
                or row["recorded_effect_fingerprint"] != snapshot.identity.effect_fingerprint
                or row["source_system"] != snapshot.identity.source_system
                or row["recorded_source_system"] != snapshot.identity.source_system
                or row["source_effect_id"] != row["recorded_source_effect_id"]
                or row["source_payload_hash"] != row["recorded_source_payload_hash"]
            ):
                continue
            source_body = {
                "effect_fingerprint": row["recorded_effect_fingerprint"],
                "source_system": row["recorded_source_system"],
                "source_effect_id": row["recorded_source_effect_id"],
                "source_payload_hash": row["recorded_source_payload_hash"],
            }
            source_receipt_id, source_receipt_hash = _receipt(
                receipt_kind="SOURCE_EFFECT",
                action_id=snapshot.identity.action_id,
                command_id=row["source_command_id"],
                body=source_body,
            )
            readback_body = {
                "readback_id": row["readback_id"],
                "claimed_effect_fingerprint": row["claimed_effect_fingerprint"],
                "source_system": row["source_system"],
                "source_effect_id": row["source_effect_id"],
                "source_payload_hash": row["source_payload_hash"],
                "observed": True,
                "exact_binding": True,
                "admitted_state_version": row["admitted_state_version"],
            }
            readback_receipt_id, readback_receipt_hash = _receipt(
                receipt_kind="READBACK",
                action_id=snapshot.identity.action_id,
                command_id=row["command_id"],
                body=readback_body,
            )
            if (
                row["source_receipt_id"] == source_receipt_id
                and row["source_receipt_hash"] == source_receipt_hash
                and row["receipt_id"] == readback_receipt_id
                and row["receipt_hash"] == readback_receipt_hash
            ):
                return True
        return False

    def _append_obligation_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        action_id: str,
        command_id: str,
        obligation_id: str,
        event_type: str,
        owner_id: str,
        deadline: str,
        effect_fingerprint: str,
        evidence_hash: str,
        supersedes_receipt_hash: str | None,
    ) -> dict[str, Any]:
        body = {
            "obligation_id": obligation_id,
            "event_type": event_type,
            "owner_id": owner_id,
            "deadline": deadline,
            "effect_fingerprint": effect_fingerprint,
            "evidence_hash": evidence_hash,
            "supersedes_receipt_hash": supersedes_receipt_hash,
        }
        receipt_id, receipt_hash = _receipt(
            receipt_kind="OBLIGATION_" + event_type,
            action_id=action_id,
            command_id=command_id,
            body=body,
        )
        connection.execute(
            """
            INSERT INTO obligation_receipts (
                receipt_id, receipt_hash, obligation_id, action_id, command_id,
                event_type, owner_id, deadline, effect_fingerprint, evidence_hash,
                supersedes_receipt_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                receipt_hash,
                obligation_id,
                action_id,
                command_id,
                event_type,
                owner_id,
                deadline,
                effect_fingerprint,
                evidence_hash,
                supersedes_receipt_hash,
                _utc_now(),
            ),
        )
        return {**body, "receipt_id": receipt_id, "receipt_hash": receipt_hash}

    def _latest_compensation(
        self,
        connection: sqlite3.Connection,
        action_id: str,
        compensation_id: str,
    ) -> sqlite3.Row | None:
        rows = connection.execute(
            """
            SELECT * FROM compensation_receipts
            WHERE action_id = ? AND compensation_id = ?
            ORDER BY rowid
            """,
            (action_id, compensation_id),
        ).fetchall()
        if not rows:
            return None
        previous: sqlite3.Row | None = None
        for row in rows:
            if previous is None:
                if row["event_type"] != "REQUIRED" or row["supersedes_receipt_hash"] is not None:
                    raise LifecycleConflict("compensation receipt chain must begin with REQUIRED")
            else:
                allowed = {
                    "REQUIRED": {"STARTED"},
                    "STARTED": {"VERIFIED", "FAILED"},
                    "VERIFIED": set(),
                    "FAILED": set(),
                }
                if (
                    row["event_type"] not in allowed[previous["event_type"]]
                    or row["supersedes_receipt_hash"] != previous["receipt_hash"]
                    or row["original_source_effect_id"] != previous["original_source_effect_id"]
                    or row["source_system"] != previous["source_system"]
                ):
                    raise LifecycleConflict("compensation receipt chain is invalid")
            body = {
                "compensation_id": row["compensation_id"],
                "event_type": row["event_type"],
                "original_source_effect_id": row["original_source_effect_id"],
                "compensation_effect_id": row["compensation_effect_id"],
                "source_system": row["source_system"],
                "evidence_hash": row["evidence_hash"],
                "supersedes_receipt_hash": row["supersedes_receipt_hash"],
            }
            receipt_id, receipt_hash = _receipt(
                receipt_kind="COMPENSATION_" + row["event_type"],
                action_id=action_id,
                command_id=row["command_id"],
                body=body,
            )
            if row["receipt_id"] != receipt_id or row["receipt_hash"] != receipt_hash:
                raise LifecycleConflict("compensation receipt hash validation failed")
            previous = row
        return previous

    def _append_compensation_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        action_id: str,
        command_id: str,
        compensation_id: str,
        event_type: str,
        original_source_effect_id: str,
        compensation_effect_id: str | None,
        source_system: str,
        evidence_hash: str,
        supersedes_receipt_hash: str | None,
    ) -> dict[str, Any]:
        body = {
            "compensation_id": compensation_id,
            "event_type": event_type,
            "original_source_effect_id": original_source_effect_id,
            "compensation_effect_id": compensation_effect_id,
            "source_system": source_system,
            "evidence_hash": evidence_hash,
            "supersedes_receipt_hash": supersedes_receipt_hash,
        }
        receipt_id, receipt_hash = _receipt(
            receipt_kind="COMPENSATION_" + event_type,
            action_id=action_id,
            command_id=command_id,
            body=body,
        )
        connection.execute(
            """
            INSERT INTO compensation_receipts (
                receipt_id, receipt_hash, compensation_id, action_id, command_id,
                event_type, original_source_effect_id, compensation_effect_id,
                source_system, evidence_hash, supersedes_receipt_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                receipt_hash,
                compensation_id,
                action_id,
                command_id,
                event_type,
                original_source_effect_id,
                compensation_effect_id,
                source_system,
                evidence_hash,
                supersedes_receipt_hash,
                _utc_now(),
            ),
        )
        return {**body, "receipt_id": receipt_id, "receipt_hash": receipt_hash}


__all__ = [
    "ActionIdentityConflict",
    "CommandConflict",
    "ConsequenceLifecycleStore",
    "LifecycleConflict",
    "LifecycleStoreError",
    "ReservationConflict",
    "VerificationBlocked",
]
