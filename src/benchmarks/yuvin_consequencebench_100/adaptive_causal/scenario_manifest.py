"""Validation for the canonical catalog-to-executable-world identity map."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from importlib.resources import files
from typing import Any, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.world.pressure_episode import (
    build_public_pressure_specs,
)


SCENARIO_MANIFEST_SCHEMA_VERSION = "ycb100.scenario_manifest.v1"
SCENARIO_MANIFEST_RESOURCE = "data/archetypes.v1.json"
DOMAIN_IDS = (
    "banking",
    "cybersecurity",
    "energy",
    "healthcare",
    "software_delivery",
)
GOVERNANCE_LENSES = (
    "authority_policy",
    "evidence_provenance",
    "execution_recovery",
    "delayed_consequence",
)


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_scenario_manifest() -> dict[str, Any]:
    resource = files(
        "benchmarks.yuvin_consequencebench_100.adaptive_causal"
    ).joinpath(SCENARIO_MANIFEST_RESOURCE)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scenario manifest must be a JSON object")
    return payload


def validate_scenario_manifest(
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed unless all 100 catalog identities bind to executable worlds."""
    manifest = dict(payload or load_scenario_manifest())
    failures: list[str] = []
    claimed_hash = manifest.pop("manifest_hash", None)
    actual_hash = _digest(manifest)
    if claimed_hash != actual_hash:
        failures.append("manifest_hash_mismatch")
    if manifest.get("schema_version") != SCENARIO_MANIFEST_SCHEMA_VERSION:
        failures.append("schema_version_mismatch")
    if manifest.get("release_tier") != "DEVELOPMENT_PREVIEW_NOT_QUALIFIED":
        failures.append("claim_boundary_mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        entries = []
        failures.append("entries_not_array")
    if len(entries) != 100 or manifest.get("catalog_entry_count") != 100:
        failures.append("catalog_entry_count_mismatch")

    ids: list[str] = []
    domains: Counter[str] = Counter()
    lenses: Counter[str] = Counter()
    bindings: set[tuple[str, int, str]] = set()
    executable_specs = {
        (spec.domain_id, spec.family_index, spec.variant_id)
        for spec in build_public_pressure_specs(seed=0)
    }
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, Mapping):
            failures.append(f"entry_{index}_not_object")
            continue
        scenario_id = str(raw_entry.get("scenario_id") or "")
        ids.append(scenario_id)
        domain_id = str(raw_entry.get("domain_id") or "")
        lens = str(raw_entry.get("governance_lens") or "")
        domains[domain_id] += 1
        lenses[lens] += 1
        binding = raw_entry.get("executable_binding")
        oracle = raw_entry.get("oracle_binding")
        if not isinstance(binding, Mapping):
            failures.append(f"{scenario_id}:missing_executable_binding")
            continue
        if not isinstance(oracle, Mapping):
            failures.append(f"{scenario_id}:missing_oracle_binding")
            continue
        family_index = binding.get("family_index")
        if isinstance(family_index, bool) or not isinstance(family_index, int):
            failures.append(f"{scenario_id}:invalid_family_index")
            continue
        key = (
            str(binding.get("domain_id") or ""),
            family_index,
            str(binding.get("variant_id") or ""),
        )
        if key in bindings:
            failures.append(f"{scenario_id}:duplicate_executable_binding")
        bindings.add(key)
        if key not in executable_specs:
            failures.append(f"{scenario_id}:missing_executable_world")
        if key[0] != domain_id:
            failures.append(f"{scenario_id}:domain_binding_mismatch")
        decision_space = oracle.get("decision_space")
        if decision_space != [
            "execute",
            "deny",
            "defer",
            "escalate",
            "compensate",
        ]:
            failures.append(f"{scenario_id}:oracle_decision_space_mismatch")

    if len(set(ids)) != 100:
        failures.append("scenario_ids_not_unique")
    if domains != Counter({domain: 20 for domain in DOMAIN_IDS}):
        failures.append("domain_balance_mismatch")
    if lenses != Counter({lens: 25 for lens in GOVERNANCE_LENSES}):
        failures.append("governance_lens_balance_mismatch")
    if bindings != executable_specs:
        failures.append("executable_coverage_mismatch")

    return {
        "schema_version": "ycb100.scenario_manifest_validation.v1",
        "status": "PASS" if not failures else "FAIL",
        "qualification_eligible": False,
        "scenario_count": len(entries),
        "executable_binding_count": len(bindings),
        "manifest_hash": claimed_hash,
        "validation_failures": failures,
        "failure_count": len(failures),
    }


__all__ = [
    "SCENARIO_MANIFEST_SCHEMA_VERSION",
    "load_scenario_manifest",
    "validate_scenario_manifest",
]
