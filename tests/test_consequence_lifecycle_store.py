from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle import (
    ActionIdentityConflict,
    ActionIdentityV1,
    CommandConflict,
    ConsequenceLifecycleStore,
    LifecycleConflict,
    LifecycleState,
    ReservationConflict,
    VerificationBlocked,
)


def _identity(action_id: str = "action-001", *, amount: int = 7500) -> ActionIdentityV1:
    return ActionIdentityV1.from_claims(
        action_id=action_id,
        tenant_id="tenant-demo",
        connector_id="connector-demo",
        source_system="source-demo",
        action_type="bounded-transfer",
        target={"account_id": "account-17"},
        parameters={"amount_minor": amount, "currency": "USD"},
    )


def _created(store: ConsequenceLifecycleStore, identity: ActionIdentityV1 | None = None) -> ActionIdentityV1:
    selected = identity or _identity()
    store.create_action(
        selected,
        expected_state_version=-1,
        command_id="create-" + selected.action_id,
    )
    return selected


def _through_readback_pending(
    store: ConsequenceLifecycleStore,
    identity: ActionIdentityV1 | None = None,
) -> ActionIdentityV1:
    selected = _created(store, identity)
    action_id = selected.action_id
    store.prepare_action(
        action_id,
        expected_state_version=0,
        command_id="prepare-" + action_id,
        attempt_id="attempt-" + action_id,
        prepared_payload={"identity_hash": selected.identity_hash},
    )
    store.reserve_effect(
        action_id,
        expected_state_version=1,
        command_id="reserve-" + action_id,
        reservation_id="reservation-" + action_id,
        semantic_key="semantic-" + action_id,
    )
    store.begin_dispatch(
        action_id,
        expected_state_version=2,
        command_id="dispatch-" + action_id,
        invocation_id="invocation-" + action_id,
        connector_request={"effect_fingerprint": selected.effect_fingerprint},
    )
    store.record_dispatch_outcome(
        action_id,
        expected_state_version=3,
        command_id="outcome-" + action_id,
        outcome=LifecycleState.COMMITTED,
        outcome_evidence={"connector_ack": "accepted-not-proof"},
    )
    store.begin_readback(
        action_id,
        expected_state_version=4,
        command_id="readback-start-" + action_id,
    )
    return selected


def _record_exact_effect_and_readback(
    store: ConsequenceLifecycleStore,
    identity: ActionIdentityV1,
    *,
    version: int = 5,
) -> None:
    action_id = identity.action_id
    payload = {
        "action_id": action_id,
        "effect_fingerprint": identity.effect_fingerprint,
        "committed": True,
    }
    store.record_source_effect(
        action_id,
        expected_state_version=version,
        command_id="source-effect-" + action_id,
        source_system=identity.source_system,
        source_effect_id="source-effect-" + action_id,
        source_payload=payload,
    )
    store.admit_readback(
        action_id,
        expected_state_version=version,
        command_id="readback-" + action_id,
        readback_id="readback-" + action_id,
        claimed_effect_fingerprint=identity.effect_fingerprint,
        source_system=identity.source_system,
        source_effect_id="source-effect-" + action_id,
        source_payload=payload,
        observed=True,
    )


def test_full_committed_lifecycle_requires_exact_source_readback(tmp_path: Path) -> None:
    store = ConsequenceLifecycleStore(tmp_path / "lifecycle.sqlite3")
    identity = _through_readback_pending(store)
    _record_exact_effect_and_readback(store, identity)

    result = store.verify_action(
        identity.action_id,
        expected_state_version=6,
        command_id="verify-action-001",
    )

    assert result["action"]["state"] == "VERIFIED"
    assert result["action"]["state_version"] == 7
    assert len(store.receipts("prepared_attempts", action_id=identity.action_id)) == 1
    assert len(store.receipts("connector_invocations", action_id=identity.action_id)) == 1
    assert len(store.receipts("source_effects", action_id=identity.action_id)) == 1
    assert store.receipts("readbacks", action_id=identity.action_id)[0]["exact_binding"] == 1


def test_crash_restart_replays_dispatch_without_second_invocation(tmp_path: Path) -> None:
    database = tmp_path / "restart.sqlite3"
    first = ConsequenceLifecycleStore(database)
    identity = _created(first)
    first.prepare_action(
        identity.action_id,
        expected_state_version=0,
        command_id="prepare-action-001",
        attempt_id="attempt-action-001",
        prepared_payload={"payload": "durable"},
    )
    first.reserve_effect(
        identity.action_id,
        expected_state_version=1,
        command_id="reserve-action-001",
        reservation_id="reservation-action-001",
        semantic_key="semantic-action-001",
    )
    original = first.begin_dispatch(
        identity.action_id,
        expected_state_version=2,
        command_id="dispatch-action-001",
        invocation_id="invocation-action-001",
        connector_request={"operation": "bounded-transfer"},
    )

    restarted = ConsequenceLifecycleStore(database)
    replay = restarted.begin_dispatch(
        identity.action_id,
        expected_state_version=2,
        command_id="dispatch-action-001",
        invocation_id="invocation-action-001",
        connector_request={"operation": "bounded-transfer"},
    )

    assert replay == original
    assert restarted.get_action(identity.action_id).state == LifecycleState.DISPATCHING
    assert len(restarted.receipts("connector_invocations", action_id=identity.action_id)) == 1

    restarted.record_dispatch_outcome(
        identity.action_id,
        expected_state_version=3,
        command_id="outcome-action-001",
        outcome=LifecycleState.EXECUTION_UNKNOWN,
        outcome_evidence={"connection": "lost"},
    )
    restarted.begin_readback(
        identity.action_id,
        expected_state_version=4,
        command_id="readback-start-action-001",
    )
    _record_exact_effect_and_readback(restarted, identity)
    assert restarted.get_action(identity.action_id).state == LifecycleState.EFFECT_VERIFIED


def test_prepared_attempt_and_reservation_are_required_before_dispatch(tmp_path: Path) -> None:
    store = ConsequenceLifecycleStore(tmp_path / "ordering.sqlite3")
    identity = _created(store)

    with pytest.raises(LifecycleConflict):
        store.begin_dispatch(
            identity.action_id,
            expected_state_version=0,
            command_id="dispatch-too-early",
            invocation_id="invocation-too-early",
            connector_request={"unsafe": True},
        )

    assert store.get_action(identity.action_id).state == LifecycleState.PROPOSED
    assert store.receipts("connector_invocations", action_id=identity.action_id) == ()


def test_identity_stale_version_and_command_reuse_fail_closed(tmp_path: Path) -> None:
    store = ConsequenceLifecycleStore(tmp_path / "identity.sqlite3")
    identity = _created(store)

    with pytest.raises(ActionIdentityConflict):
        store.create_action(
            _identity(amount=9999),
            expected_state_version=-1,
            command_id="create-conflicting",
        )

    store.prepare_action(
        identity.action_id,
        expected_state_version=0,
        command_id="prepare-action-001",
        attempt_id="attempt-action-001",
        prepared_payload={"version": 1},
    )
    with pytest.raises(LifecycleConflict):
        store.reserve_effect(
            identity.action_id,
            expected_state_version=0,
            command_id="stale-reserve",
            reservation_id="stale-reservation",
            semantic_key="stale-semantic",
        )
    with pytest.raises(CommandConflict):
        store.prepare_action(
            identity.action_id,
            expected_state_version=0,
            command_id="prepare-action-001",
            attempt_id="attempt-action-001",
            prepared_payload={"version": 2},
        )


def test_concurrent_semantic_effect_reservation_has_one_winner(tmp_path: Path) -> None:
    database = tmp_path / "concurrency.sqlite3"
    setup = ConsequenceLifecycleStore(database)
    identities = (_identity("action-001"), _identity("action-002"))
    for identity in identities:
        _created(setup, identity)
        setup.prepare_action(
            identity.action_id,
            expected_state_version=0,
            command_id="prepare-" + identity.action_id,
            attempt_id="attempt-" + identity.action_id,
            prepared_payload={"same_effect": True},
        )

    def reserve(identity: ActionIdentityV1) -> str:
        store = ConsequenceLifecycleStore(database)
        try:
            store.reserve_effect(
                identity.action_id,
                expected_state_version=1,
                command_id="reserve-" + identity.action_id,
                reservation_id="reservation-" + identity.action_id,
                semantic_key="one-shared-semantic-key",
            )
            return "won"
        except ReservationConflict:
            return "lost"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, identities))

    assert sorted(outcomes) == ["lost", "won"]
    states = [ConsequenceLifecycleStore(database).get_action(item.action_id).state for item in identities]
    assert states.count(LifecycleState.RESERVED) == 1
    assert states.count(LifecycleState.PREPARED) == 1


def test_forged_or_cross_source_readback_never_reaches_verified(tmp_path: Path) -> None:
    store = ConsequenceLifecycleStore(tmp_path / "forgery.sqlite3")
    identity = _through_readback_pending(store)
    payload = {"action_id": identity.action_id, "committed": True}
    store.record_source_effect(
        identity.action_id,
        expected_state_version=5,
        command_id="source-effect-action-001",
        source_system=identity.source_system,
        source_effect_id="source-effect-action-001",
        source_payload=payload,
    )
    result = store.admit_readback(
        identity.action_id,
        expected_state_version=5,
        command_id="forged-readback",
        readback_id="forged-readback",
        claimed_effect_fingerprint="sha256:" + "0" * 64,
        source_system=identity.source_system,
        source_effect_id="source-effect-action-001",
        source_payload=payload,
        observed=True,
    )

    assert result["readback"]["exact_binding"] is False
    assert store.get_action(identity.action_id).state == LifecycleState.READBACK_PENDING
    with pytest.raises(VerificationBlocked):
        store.verify_action(
            identity.action_id,
            expected_state_version=5,
            command_id="forged-verify",
        )


def test_obligation_blocks_verified_until_append_only_discharge(tmp_path: Path) -> None:
    store = ConsequenceLifecycleStore(tmp_path / "obligation.sqlite3")
    identity = _through_readback_pending(store)
    _record_exact_effect_and_readback(store, identity)
    store.open_obligation(
        identity.action_id,
        expected_state_version=6,
        command_id="open-obligation",
        obligation_id="obligation-monitor",
        owner_id="safety-owner",
        deadline="2030-01-01T00:00:00Z",
        evidence={"trigger": "post-effect-watch"},
    )

    with pytest.raises(VerificationBlocked):
        store.verify_action(
            identity.action_id,
            expected_state_version=7,
            command_id="verify-too-early",
        )

    store.discharge_obligation(
        identity.action_id,
        expected_state_version=7,
        command_id="discharge-obligation",
        obligation_id="obligation-monitor",
        evidence={"source_watch": "stable"},
    )
    store.verify_action(
        identity.action_id,
        expected_state_version=7,
        command_id="verify-after-duty",
    )
    receipts = store.receipts("obligation_receipts", action_id=identity.action_id)
    assert [row["event_type"] for row in receipts] == ["OPENED", "DISCHARGED"]
    assert receipts[1]["supersedes_receipt_hash"] == receipts[0]["receipt_hash"]


def test_compensation_preserves_original_source_effect_and_history(tmp_path: Path) -> None:
    store = ConsequenceLifecycleStore(tmp_path / "compensation.sqlite3")
    identity = _through_readback_pending(store)
    original_payload = {"action_id": identity.action_id, "partial": True}
    store.record_source_effect(
        identity.action_id,
        expected_state_version=5,
        command_id="source-effect-action-001",
        source_system=identity.source_system,
        source_effect_id="original-effect",
        source_payload=original_payload,
    )
    store.require_compensation(
        identity.action_id,
        expected_state_version=5,
        command_id="require-compensation",
        compensation_id="compensation-001",
        original_source_effect_id="original-effect",
        reason_evidence={"reason": "partial-effect"},
    )
    store.start_compensation(
        identity.action_id,
        expected_state_version=6,
        command_id="start-compensation",
        compensation_id="compensation-001",
        evidence={"approved": True},
    )
    store.record_compensation_readback(
        identity.action_id,
        expected_state_version=7,
        command_id="compensation-readback",
        compensation_id="compensation-001",
        compensation_effect_id="compensation-effect-001",
        source_system=identity.source_system,
        evidence={"source_status": "compensated"},
        verified=True,
    )
    store.complete_compensation(
        identity.action_id,
        expected_state_version=7,
        command_id="complete-compensation",
        compensation_id="compensation-001",
    )

    assert store.get_action(identity.action_id).state == LifecycleState.COMPENSATED
    assert len(store.receipts("source_effects", action_id=identity.action_id)) == 1
    compensation = store.receipts("compensation_receipts", action_id=identity.action_id)
    assert [row["event_type"] for row in compensation] == ["REQUIRED", "STARTED", "VERIFIED"]
    assert all(row["original_source_effect_id"] == "original-effect" for row in compensation)


def test_receipts_and_identity_are_sqlite_immutable(tmp_path: Path) -> None:
    database = tmp_path / "immutable.sqlite3"
    store = ConsequenceLifecycleStore(database)
    identity = _created(store)

    connection = sqlite3.connect(database)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE actions SET tenant_id = 'attacker' WHERE action_id = ?",
                (identity.action_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE transitions SET reason = 'forged' WHERE action_id = ?",
                (identity.action_id,),
            )
    finally:
        connection.close()


def test_materialized_state_without_transition_receipt_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "state-forgery.sqlite3"
    store = ConsequenceLifecycleStore(database)
    identity = _created(store)

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE actions SET current_state = 'VERIFIED', state_version = 99 WHERE action_id = ?",
            (identity.action_id,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(LifecycleConflict, match="contradicts transition receipts"):
        store.get_action(identity.action_id)


def test_connections_close_so_database_can_be_renamed_immediately(tmp_path: Path) -> None:
    database = tmp_path / "closable.sqlite3"
    store = ConsequenceLifecycleStore(database)
    _created(store)
    store.get_action("action-001")

    moved = tmp_path / "moved.sqlite3"
    os.replace(database, moved)
    assert moved.is_file()
    os.replace(moved, database)
    assert ConsequenceLifecycleStore(database).get_action("action-001").state == LifecycleState.PROPOSED
