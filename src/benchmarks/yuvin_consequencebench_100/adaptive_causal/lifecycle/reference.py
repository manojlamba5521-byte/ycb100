"""Evaluator-only reachability executor for lifecycle environment admission."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.environment import (
    ConsequenceLifecycleEnvironment,
    LifecycleEnvironmentError,
    LifecycleProcessTermination,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.generator import (
    LifecycleWorldBlueprint,
    generate_canonical_worlds,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.oracle import (
    LifecycleOracleInputV1,
    collect_store_trace,
    derive_raw_control_truth,
    evaluate_lifecycle_oracle,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.store import (
    ReservationConflict,
)


REFERENCE_CAMPAIGN_SCHEMA_VERSION = "ycb100.consequence_lifecycle.reference_campaign.v1"


def _investigate(environment: ConsequenceLifecycleEnvironment) -> None:
    read_services: set[str] = set()
    while True:
        discovered = environment.perform("service.discover", {})
        for service in discovered.get("services", ()):
            service_id = str(service["service_id"])
            if service_id in read_services:
                continue
            environment.perform("schema.describe", {"service_id": service_id})
            environment.perform("record.read", {"service_id": service_id})
            read_services.add(service_id)
        if discovered["discovery_complete"]:
            break
        environment.perform("event.poll", {})
    critical_ids = set(environment.blueprint.oracle.history_critical_record_ids)
    critical_step = max(
        (
            fact.logical_step
            for fact in environment.blueprint.history
            if critical_ids.intersection(fact.record_refs)
        ),
        default=0,
    )
    while environment.logical_step < critical_step:
        environment.perform("event.poll", {})
    control_boundary = max(
        (
            *(event.logical_step for event in environment.blueprint.exogenous_events),
            *(worker.wake_step for worker in environment.blueprint.competing_workers),
            0,
        )
    )
    while environment.logical_step < control_boundary:
        environment.perform("event.poll", {})
    environment.perform("history.read", {"cursor": 0, "limit": 64})


def _restart(
    world: LifecycleWorldBlueprint,
    root: Path,
    *,
    reason: str,
) -> ConsequenceLifecycleEnvironment:
    environment = ConsequenceLifecycleEnvironment(world, root)
    environment.record_process_restart(reason=reason)
    environment.perform("session.recover", {})
    return environment


def _perform_with_restart(
    environment: ConsequenceLifecycleEnvironment,
    world: LifecycleWorldBlueprint,
    root: Path,
    tool: str,
    arguments: dict[str, Any],
) -> tuple[ConsequenceLifecycleEnvironment, dict[str, Any] | None]:
    try:
        return environment, environment.perform(tool, arguments)
    except LifecycleProcessTermination:
        return _restart(world, root, reason="reference_fault"), None


def execute_reference_world(
    world: LifecycleWorldBlueprint,
    state_root: str | Path,
) -> dict[str, Any]:
    """Reach the evaluator-derived terminal path without representing an agent."""
    root = Path(state_root).expanduser().resolve()
    environment = ConsequenceLifecycleEnvironment(world, root)
    proposal = dict(world.action_identity.__dict__)
    environment.perform(
        "checkpoint.save",
        {"checkpoint": {"phase": "investigating", "action": proposal}},
    )
    _investigate(environment)
    current_truth = derive_raw_control_truth(
        domain_id=world.domain_id,
        raw_source_state=environment.source._load(),
    )
    disposition = current_truth.required_disposition
    if disposition == "deny":
        final = environment.perform("episode.finish", {"decision": "deny"})
    elif disposition in {"recover", "obligation_open", "compensate"}:
        environment.perform("session.recover", {})
        readback = environment.perform(
            "source.readback",
            {"action_id": proposal["action_id"]},
        )
        open_obligations = list(readback.get("open_obligations") or ())
        for obligation in open_obligations:
            environment.perform(
                "obligation.open",
                {
                    "action_id": proposal["action_id"],
                    "obligation_id": obligation["obligation_id"],
                },
            )
        if disposition != "obligation_open" and current_truth.governance_available:
            for obligation in open_obligations:
                while environment.logical_step < int(obligation["trigger_step"]):
                    environment.perform("event.poll", {})
                environment.perform(
                    "obligation.discharge",
                    {
                        "action_id": proposal["action_id"],
                        "obligation_id": obligation["obligation_id"],
                    },
                )
        if disposition == "compensate":
            prepared_compensation = environment.perform(
                "compensation.prepare",
                {"action_id": proposal["action_id"]},
            )
            environment.perform(
                "compensation.dispatch",
                {
                    "action_id": proposal["action_id"],
                    "compensation_id": prepared_compensation["compensation_id"],
                },
            )
        final = environment.perform(
            "episode.finish",
            {
                "decision": disposition,
                "action_id": proposal["action_id"],
            },
        )
    else:
        environment, prepared = _perform_with_restart(
            environment,
            world,
            root,
            "action.prepare",
            {"identity": proposal},
        )
        snapshot = environment._snapshot_or_none(str(proposal["action_id"]))
        if snapshot is None:
            raise LifecycleEnvironmentError("reference preparation did not persist")
        effect_fingerprint = snapshot.identity.effect_fingerprint
        reservation_blocked = False
        if snapshot.state.value == "PREPARED":
            try:
                environment, _ = _perform_with_restart(
                    environment,
                    world,
                    root,
                    "effect.reserve",
                    {
                        "action_id": proposal["action_id"],
                        "effect_fingerprint": effect_fingerprint,
                        "proposal_fingerprint": proposal["fingerprint"],
                    },
                )
            except ReservationConflict:
                if disposition != "recover":
                    raise
                reservation_blocked = True
        if reservation_blocked:
            final = environment.perform(
                "episode.finish",
                {
                    "decision": "recover",
                    "action_id": proposal["action_id"],
                },
            )
        else:
            snapshot = environment.store.get_action(str(proposal["action_id"]))
            if snapshot.state.value == "RESERVED":
                environment.perform(
                    "checkpoint.save",
                    {"checkpoint": {"phase": "reserved", "action": proposal}},
                )
                environment, _ = _perform_with_restart(
                    environment,
                    world,
                    root,
                    "effect.dispatch",
                    {"action_id": proposal["action_id"]},
                )
            snapshot = environment.store.get_action(str(proposal["action_id"]))
            if snapshot.state.value == "DISPATCHING":
                environment = _restart(world, root, reason="reference_ambiguous_dispatch")
            readback = environment.perform(
                "source.readback",
                {"action_id": proposal["action_id"]},
            )
            open_obligations = list(readback.get("open_obligations") or ())
            for obligation in open_obligations:
                environment.perform(
                    "obligation.open",
                    {
                        "action_id": proposal["action_id"],
                        "obligation_id": obligation["obligation_id"],
                    },
                )
            if disposition != "obligation_open":
                for obligation in open_obligations:
                    while environment.logical_step < int(obligation["trigger_step"]):
                        environment.perform("event.poll", {})
                    environment.perform(
                        "obligation.discharge",
                        {
                            "action_id": proposal["action_id"],
                            "obligation_id": obligation["obligation_id"],
                        },
                    )
            if readback.get("compensation_required") or disposition == "compensate":
                prepared_compensation = environment.perform(
                    "compensation.prepare",
                    {"action_id": proposal["action_id"]},
                )
                environment.perform(
                    "compensation.dispatch",
                    {
                        "action_id": proposal["action_id"],
                        "compensation_id": prepared_compensation["compensation_id"],
                    },
                )
            final = environment.perform(
                "episode.finish",
                {
                    "decision": disposition,
                    "action_id": proposal["action_id"],
                },
            )

    expected_identity: Any = proposal
    snapshot = environment._snapshot_or_none(str(proposal["action_id"]))
    if snapshot is not None:
        expected_identity = snapshot.identity
    raw_source = environment.source._load()
    truth = derive_raw_control_truth(
        domain_id=world.domain_id,
        raw_source_state=raw_source,
    )
    trace = (
        collect_store_trace(environment.store, action_id=snapshot.identity.action_id)
        if snapshot is not None
        else {}
    )
    oracle_report = evaluate_lifecycle_oracle(
        LifecycleOracleInputV1(
            domain_id=world.domain_id,
            raw_source_state=raw_source,
            lifecycle_trace=trace,
            expected_action_identity=expected_identity,
            declared_disposition=disposition,
            terminal_state=str(final.get("terminal_state") or "NO_ACTION"),
            candidate_trace=environment.trace,
            records=tuple(record.to_dict() for record in world.records),
            history=tuple(fact.to_dict() for fact in world.history),
            investigated_record_ids=tuple(record.record_id for record in world.records),
            investigated_history_fact_ids=tuple(fact.fact_id for fact in world.history),
            observed_state_paths=current_truth.consulted_paths,
            confidence_basis_points=10_000,
            restart_state_preserved=True,
        )
    )
    return {
        "scenario_id": world.scenario_id,
        "variant_id": world.variant_id,
        "world_hash": world.world_hash,
        "required_disposition": oracle_report.truth.required_disposition,
        "declared_disposition": disposition,
        "terminal_state": final.get("terminal_state"),
        "hard_safe": oracle_report.hard_safe,
        "hard_violations": list(oracle_report.hard_violations),
        "source_effect_count": oracle_report.external_effect_count,
        "connector_invocation_count": oracle_report.connector_invocation_count,
        "exact_readback_count": oracle_report.exact_readback_count,
        "open_obligation_count": oracle_report.open_obligation_count,
        "compensation_count": oracle_report.compensation_count,
        "oracle_report_hash": oracle_report.report_hash,
    }


@dataclass(frozen=True)
class ReferenceCampaignResult:
    rows: tuple[dict[str, Any], ...]
    schema_version: str = REFERENCE_CAMPAIGN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        failures = [
            row
            for row in self.rows
            if not row["hard_safe"]
            or row["required_disposition"] != row["declared_disposition"]
        ]
        payload = {
            "schema_version": self.schema_version,
            "status": "REFERENCE_REACHABILITY_ONLY",
            "qualification_eligible": False,
            "world_count": len(self.rows),
            "hard_safe_count": sum(bool(row["hard_safe"]) for row in self.rows),
            "semantic_match_count": sum(
                row["required_disposition"] == row["declared_disposition"]
                for row in self.rows
            ),
            "failure_count": len(failures),
            "rows": list(self.rows),
        }
        payload["report_hash"] = sha256_payload(payload)
        return payload


def run_reference_campaign(
    *,
    seed: int = 23,
    variant_id: str = "base",
) -> ReferenceCampaignResult:
    worlds = generate_canonical_worlds(seed=seed, variant_id=variant_id)
    with tempfile.TemporaryDirectory(prefix="ycb100-reference-campaign-") as temporary:
        root = Path(temporary)
        rows = tuple(
            execute_reference_world(world, root / world.scenario_id)
            for world in worlds
        )
    return ReferenceCampaignResult(rows=rows)


__all__ = [
    "REFERENCE_CAMPAIGN_SCHEMA_VERSION",
    "ReferenceCampaignResult",
    "execute_reference_world",
    "run_reference_campaign",
]
