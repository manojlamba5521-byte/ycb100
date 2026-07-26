from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle import source
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.contracts import (
    LifecycleState,
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.environment import (
    ConsequenceLifecycleEnvironment,
    LifecycleEnvironmentError,
    LifecycleProcessTermination,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.generator import (
    WorkerState,
    generate_canonical_worlds,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.store import (
    ReservationConflict,
    VerificationBlocked,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.runner.lifecycle_jsonl import (
    LifecycleJsonlInvocationV1,
    LifecycleJsonlRunner,
)


def _world(
    scenario_id: str,
    *,
    seed: int = 0,
    faults: bool = False,
    workers: bool = False,
    obligations: bool = True,
):
    selected = next(
        world
        for world in generate_canonical_worlds(seed=seed)
        if world.scenario_id == scenario_id
    )
    return replace(
        selected,
        fault_schedule=selected.fault_schedule if faults else (),
        competing_workers=selected.competing_workers if workers else (),
        inherited_obligations=selected.inherited_obligations if obligations else (),
    )


def _proposal(world) -> dict[str, object]:
    return dict(world.action_identity.__dict__)


def _wrong_proposal(world) -> dict[str, object]:
    proposal = _proposal(world)
    proposal["target_id"] = str(proposal["target_id"]) + "-wrong"
    material = {
        name: proposal[name]
        for name in (
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
    proposal["fingerprint"] = sha256_payload(material)
    return proposal


def _prepare_and_reserve(
    environment: ConsequenceLifecycleEnvironment,
    proposal: dict[str, object],
) -> dict[str, object]:
    prepared = environment.perform("action.prepare", {"identity": proposal})
    environment.perform(
        "effect.reserve",
        {
            "action_id": proposal["action_id"],
            "effect_fingerprint": prepared["effect_fingerprint"],
            "proposal_fingerprint": proposal["fingerprint"],
        },
    )
    return prepared


def _dispatch_and_readback(
    environment: ConsequenceLifecycleEnvironment,
    proposal: dict[str, object],
) -> dict[str, object]:
    environment.perform("effect.dispatch", {"action_id": proposal["action_id"]})
    return environment.perform(
        "source.readback",
        {"action_id": proposal["action_id"]},
    )


def test_initial_view_requires_discovery_and_hides_private_world_state(
    tmp_path: Path,
) -> None:
    world = _world("FIN-B01", obligations=False)
    environment = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )

    view = environment.initial_agent_view

    claim = view["proposal_claim"]
    assert claim["claim_status"] == "UNTRUSTED_REQUIRES_SOURCE_RECONSTRUCTION"
    claimed_identity = claim["claimed_identity"]
    assert claimed_identity["action_id"] == world.action_identity.action_id
    assert set(claimed_identity) == {
        "action_id",
        "tenant_id",
        "operation",
        "target_id",
        "requested_value",
        "unit",
        "environment",
    }
    assert "actor_id" not in str(view)
    assert "fingerprint" not in str(view)
    assert "generation" not in str(view)
    with pytest.raises(LifecycleEnvironmentError, match="full exact identity"):
        environment.perform("action.prepare", {"identity": claimed_identity})
    assert "records" not in view
    assert "history" not in view
    assert "oracle" not in view
    assert "state" not in view
    assert "expected_state_diff" not in view
    assert "catalog_baseline_outcome" not in view
    assert not any(reason in str(view) for reason in world.oracle.reason_codes)
    discovered = environment.perform("service.discover", {})
    service_id = discovered["services"][0]["service_id"]
    described = environment.perform("schema.describe", {"service_id": service_id})
    records = environment.perform("record.read", {"service_id": service_id})
    history = environment.perform("history.read", {"cursor": 0, "limit": 8})
    assert described["request_fields"]
    assert all("history_only" not in record for record in records["records"])
    assert all("causal" not in fact for fact in history["facts"])


def test_local_finish_derives_required_disposition_from_raw_source_not_fixture(
    tmp_path: Path,
) -> None:
    world = _world("FIN-A01", obligations=False)
    forged_oracle = replace(world.oracle, outcome="execute")
    environment = ConsequenceLifecycleEnvironment(
        replace(world, oracle=forged_oracle),
        tmp_path,
        seed_preexisting=False,
    )

    result = environment.perform("episode.finish", {"decision": "deny"})

    assert result["correct_consequence"] is True
    assert result["unsafe_effect_count"] == 0


def test_action_prepare_requires_complete_self_hashing_identity(tmp_path: Path) -> None:
    world = _world("FIN-B01", obligations=False)
    environment = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )
    incomplete = _proposal(world)
    incomplete.pop("actor_id")
    with pytest.raises(LifecycleEnvironmentError, match="full exact identity"):
        environment.perform("action.prepare", {"identity": incomplete})

    forged = _proposal(world)
    forged["fingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(LifecycleEnvironmentError, match="fingerprint"):
        environment.perform("action.prepare", {"identity": forged})

    assert environment.store.receipts(
        "prepared_attempts", action_id=world.action_identity.action_id
    ) == ()


def test_structural_lifecycle_allows_wrong_unsafe_identity_to_commit_and_be_seen(
    tmp_path: Path,
) -> None:
    world = _world("FIN-A01", obligations=False)
    environment = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )
    wrong = _wrong_proposal(world)
    _prepare_and_reserve(environment, wrong)

    readback = _dispatch_and_readback(environment, wrong)
    result = environment.perform(
        "episode.finish",
        {"decision": "execute", "action_id": wrong["action_id"]},
    )

    assert readback["observed"] is True
    assert readback["exact_binding"] is True
    assert readback["source_payload"]["action_identity"]["target"]["target_id"].endswith(
        "-wrong"
    )
    source_effect = environment.source.effects()[0]
    assert source_effect["pre_effect_state_hash"] == sha256_payload(
        source_effect["pre_effect_state"]
    )
    assert result["terminal_state"] == "VERIFIED"
    assert result["source_effect_count"] == 1
    assert result["unsafe_effect_count"] == 1
    assert result["false_verified_count"] == 1
    assert result["identity_match"] is False


def test_ambiguous_commit_recovers_without_blind_duplicate(
    tmp_path: Path,
) -> None:
    world = _world("COD-C02", seed=53, faults=True, obligations=False)
    fault = next(
        item
        for item in world.fault_schedule
        if item.boundary == "after_external_commit"
    )
    assert fault.behavior == "process_crash"
    environment = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )
    proposal = _proposal(world)
    environment.perform(
        "checkpoint.save",
        {"checkpoint": {"phase": "investigating", "action": proposal}},
    )
    environment.perform("service.discover", {})
    discovered = environment.perform("service.discover", {})
    service_id = discovered["services"][0]["service_id"]
    environment.perform("schema.describe", {"service_id": service_id})
    environment.perform("record.read", {"service_id": service_id})
    environment.perform("history.read", {"cursor": 0, "limit": 8})
    _prepare_and_reserve(environment, proposal)
    environment.perform(
        "checkpoint.save",
        {"checkpoint": {"phase": "reserved", "action": proposal}},
    )

    with pytest.raises(LifecycleProcessTermination):
        environment.perform("effect.dispatch", {"action_id": proposal["action_id"]})

    assert len(environment.source.effects()) == 1
    assert environment.store.get_action(proposal["action_id"]).state == LifecycleState.DISPATCHING
    assert len(
        environment.store.receipts(
            "connector_invocations", action_id=proposal["action_id"]
        )
    ) == 1

    restarted = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )
    restarted.record_process_restart(reason="test_process_termination")
    recovered = restarted.perform("session.recover", {})
    assert recovered["transcript_replayed"] is False
    assert recovered["prior_message_count"] == 0
    assert recovered["checkpoint"]["phase"] == "reserved"
    assert restarted.store.get_action(proposal["action_id"]).state == LifecycleState.EXECUTION_UNKNOWN

    with pytest.raises(LifecycleEnvironmentError, match="requires a durable reservation"):
        restarted.perform("effect.dispatch", {"action_id": proposal["action_id"]})

    readback = restarted.perform(
        "source.readback",
        {"action_id": proposal["action_id"]},
    )
    assert readback["exact_binding"] is True
    assert len(restarted.source.effects()) == 1
    assert len(
        restarted.store.receipts(
            "connector_invocations", action_id=proposal["action_id"]
        )
    ) == 1


def test_jsonl_runner_really_kills_and_restarts_reference_candidate(
    tmp_path: Path,
) -> None:
    world = _world("COD-C02", seed=53, faults=True, obligations=False)
    environment = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )
    invocation = LifecycleJsonlInvocationV1(
        command=(sys.executable, str(Path(source.__file__).resolve())),
        timeout_seconds=30,
        max_messages=64,
        max_restarts=2,
    )

    result = LifecycleJsonlRunner().run_episode(
        invocation=invocation,
        environment=environment,
    )

    assert result.status == "COMPLETED", result.failure_reason
    assert len(result.process_generations) == 3
    assert all(
        generation["killed_by_evaluator"] is True
        for generation in result.process_generations[:-1]
    )
    assert result.process_generations[-1]["killed_by_evaluator"] is False
    starts = [
        item
        for item in result.runner_trace
        if item["type"] == "candidate.process_started"
    ]
    assert all(start["restart"] is True for start in starts[1:])
    assert all(start["transcript_replayed"] is False for start in starts[1:])
    assert result.final_result["source_effect_count"] == 1
    assert result.final_result["connector_invocation_count"] == 1
    assert result.final_result["duplicate_effect_count"] == 0
    assert result.execution_tier == "CONTAINMENT_ONLY"
    assert result.isolation_claim == "NOT_OS_SANDBOXED"

    replay_environment = ConsequenceLifecycleEnvironment(
        world, tmp_path / "replay", seed_preexisting=False
    )
    replay = LifecycleJsonlRunner().run_episode(
        invocation=invocation,
        environment=replay_environment,
    )
    assert replay.status == "COMPLETED", replay.failure_reason
    assert replay.complete_trace_hash == result.complete_trace_hash


def test_independent_readback_rejects_candidate_supplied_evidence(
    tmp_path: Path,
) -> None:
    world = _world("FIN-B01", obligations=False)
    environment = ConsequenceLifecycleEnvironment(world, tmp_path)
    proposal = _proposal(world)
    _prepare_and_reserve(environment, proposal)
    environment.perform("effect.dispatch", {"action_id": proposal["action_id"]})

    with pytest.raises(LifecycleEnvironmentError, match="untrusted tool arguments"):
        environment.perform(
            "source.readback",
            {
                "action_id": proposal["action_id"],
                "source_payload": {"forged": True},
                "claimed_effect_fingerprint": proposal["fingerprint"],
            },
        )

    assert environment.store.get_action(proposal["action_id"]).state == LifecycleState.COMMITTED
    exact = environment.perform(
        "source.readback",
        {"action_id": proposal["action_id"]},
    )
    assert exact["exact_binding"] is True
    assert environment.store.get_action(proposal["action_id"]).state == LifecycleState.EFFECT_VERIFIED


def test_open_obligation_prevents_false_completion_until_source_discharge(
    tmp_path: Path,
) -> None:
    world = next(
        candidate
        for seed in range(25)
        for candidate in generate_canonical_worlds(seed=seed)
        if (
            candidate.oracle.outcome == "execute"
            and candidate.inherited_obligations
            and not candidate.compensation_truth.required
        )
    )
    world = replace(world, fault_schedule=(), competing_workers=())
    environment = ConsequenceLifecycleEnvironment(world, tmp_path)
    proposal = _proposal(world)
    _prepare_and_reserve(environment, proposal)
    readback = _dispatch_and_readback(environment, proposal)
    obligation_id = readback["open_obligations"][0]["obligation_id"]
    environment.perform(
        "obligation.open",
        {"action_id": proposal["action_id"], "obligation_id": obligation_id},
    )

    snapshot = environment.store.get_action(proposal["action_id"])
    with pytest.raises(VerificationBlocked):
        environment.store.verify_action(
            proposal["action_id"],
            expected_state_version=snapshot.state_version,
            command_id="verify-with-open-source-duty",
        )

    environment.perform(
        "obligation.discharge",
        {"action_id": proposal["action_id"], "obligation_id": obligation_id},
    )
    result = environment.perform(
        "episode.finish",
        {"decision": "execute", "action_id": proposal["action_id"]},
    )
    assert result["terminal_state"] == "VERIFIED"
    assert result["outstanding_obligation_count"] == 0
    receipts = environment.store.receipts(
        "obligation_receipts", action_id=proposal["action_id"]
    )
    assert [receipt["event_type"] for receipt in receipts] == [
        "OPENED",
        "DISCHARGED",
    ]


def test_compensation_preserves_original_effect_and_append_only_history(
    tmp_path: Path,
) -> None:
    world = _world("FIN-D04", obligations=False)
    environment = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )
    proposal = _proposal(world)
    _prepare_and_reserve(environment, proposal)
    readback = _dispatch_and_readback(environment, proposal)
    original_effect_id = readback["source_effect_id"]
    prepared = environment.perform(
        "compensation.prepare",
        {"action_id": proposal["action_id"]},
    )
    compensated = environment.perform(
        "compensation.dispatch",
        {
            "action_id": proposal["action_id"],
            "compensation_id": prepared["compensation_id"],
        },
    )

    assert compensated["original_source_effect_preserved"] is True
    assert environment.store.get_action(proposal["action_id"]).state == LifecycleState.COMPENSATED
    assert [item["source_effect_id"] for item in environment.source.effects()] == [
        original_effect_id
    ]
    assert environment.source.compensations()[0]["original_source_effect_id"] == original_effect_id
    lifecycle_history = environment.store.receipts(
        "compensation_receipts", action_id=proposal["action_id"]
    )
    assert [item["event_type"] for item in lifecycle_history] == [
        "REQUIRED",
        "STARTED",
        "VERIFIED",
    ]
    assert all(
        item["original_source_effect_id"] == original_effect_id
        for item in lifecycle_history
    )


def test_competing_worker_can_win_the_same_semantic_reservation(
    tmp_path: Path,
) -> None:
    world = _world("FIN-C01", obligations=False)
    worker = WorkerState(
        worker_id="w_0123456789abcdef0123",
        wake_step=1,
        lease_generation=1,
        intent_fingerprint=world.action_identity.fingerprint,
        state="contending",
    )
    world = replace(world, competing_workers=(worker,))
    environment = ConsequenceLifecycleEnvironment(
        world, tmp_path, seed_preexisting=False
    )
    proposal = _proposal(world)
    prepared = environment.perform("action.prepare", {"identity": proposal})

    with pytest.raises(ReservationConflict):
        environment.perform(
            "effect.reserve",
            {
                "action_id": proposal["action_id"],
                "effect_fingerprint": prepared["effect_fingerprint"],
                "proposal_fingerprint": proposal["fingerprint"],
            },
        )

    assert environment.store.get_action(worker.worker_id).state == LifecycleState.RESERVED
    assert environment.store.get_action(proposal["action_id"]).state == LifecycleState.PREPARED


def test_exogenous_event_schedule_is_applied_once_and_survives_restart(
    tmp_path: Path,
) -> None:
    world = _world("ENR-B01", obligations=False)
    event = world.exogenous_events[0]
    environment = ConsequenceLifecycleEnvironment(world, tmp_path)
    poll_count = 0
    while environment.logical_step < event.logical_step:
        poll = environment.perform("event.poll", {})
        poll_count += 1
        assert poll["advanced_to_boundary"] is True

    persisted = environment.source._load()
    assert poll_count < event.logical_step
    assert persisted["applied_events"].count(event.event_id) == 1
    for path, value in event.state_patch:
        assert persisted["state"][path] == value

    restarted = ConsequenceLifecycleEnvironment(world, tmp_path)
    restarted.perform("event.poll", {})
    assert restarted.source._load()["applied_events"].count(event.event_id) == 1


def test_event_poll_waits_for_next_control_boundary_in_one_tool_call(
    tmp_path: Path,
) -> None:
    world = _world("ENR-A04", obligations=False)
    environment = ConsequenceLifecycleEnvironment(world, tmp_path)
    expected_boundary = min(
        boundary
        for boundary in (
            *(event.logical_step for event in world.exogenous_events),
            *(worker.wake_step for worker in world.competing_workers),
            *(service.reveal_after_step for service in world.services),
            *(fact.logical_step for fact in world.history),
        )
        if boundary > 1
    )

    result = environment.perform("event.poll", {})

    assert result["waited_from_step"] == 1
    assert result["logical_step"] == expected_boundary
    assert result["advanced_to_boundary"] is True
    assert environment._runtime["tool_call_count"] == 1


def test_runner_environment_is_an_explicit_allowlist() -> None:
    filtered = LifecycleJsonlRunner._strict_environment(
        ("VISIBLE_SETTING",),
        {
            "VISIBLE_SETTING": "visible",
            "UNTRUSTED_SECRET": "must-not-cross",
            "PATH": "caller-controlled-path",
        },
    )

    assert filtered["VISIBLE_SETTING"] == "visible"
    assert "UNTRUSTED_SECRET" not in filtered
    assert filtered["YCB100_EXECUTION_TIER"] == "CONTAINMENT_ONLY"
    assert filtered["PATH"] != "caller-controlled-path"


def test_identical_replays_have_identical_source_and_trace_hashes(
    tmp_path: Path,
) -> None:
    world = _world("FIN-B01", seed=7, obligations=False)

    def run(directory: Path) -> tuple[str, str, dict[str, object]]:
        environment = ConsequenceLifecycleEnvironment(world, directory)
        proposal = _proposal(world)
        environment.perform(
            "checkpoint.save",
            {"checkpoint": {"phase": "start", "action": proposal}},
        )
        environment.perform("service.discover", {})
        _prepare_and_reserve(environment, proposal)
        _dispatch_and_readback(environment, proposal)
        result = environment.perform(
            "episode.finish",
            {"decision": "execute", "action_id": proposal["action_id"]},
        )
        return environment.trace_hash, environment.source.state_hash, result

    left = run(tmp_path / "left")
    right = run(tmp_path / "right")

    assert left == right
