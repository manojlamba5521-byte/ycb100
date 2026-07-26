"""Integrity-bound qualification identities for completed pressure reports."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload


PRESSURE_AB_STUDY_SCHEMA_VERSION = "ycb100.acc.pressure_ab_study.v2"
PRESSURE_TRIAL_BINDING_SCHEMA_VERSION = "ycb100.acc.pressure_trial_binding.v1"


def _identifier(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256:
        raise ValueError(field_name + " is required")
    return normalized


def _integer(value: object, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(field_name + " must be an integer >= " + str(minimum))
    return value


def _digest(value: object, field_name: str) -> str:
    normalized = str(value or "")
    if len(normalized) != 71 or not normalized.startswith("sha256:"):
        raise ValueError(field_name + " must be a sha256 digest")
    try:
        int(normalized[7:], 16)
    except ValueError as exc:
        raise ValueError(field_name + " must be a sha256 digest") from exc
    return normalized


def bind_pressure_trial_report(
    report: Mapping[str, Any],
    *,
    model_id: str,
    seed: int,
    trial_index: int,
    expected_source_report_hash: str,
) -> dict[str, Any]:
    """Bind an immutable raw report to an evaluator-assigned repeated trial.

    The source hash is required from outside the report so a caller cannot
    silently edit a child receipt and then bind the edited value as evidence.
    """

    if not isinstance(report, Mapping):
        raise ValueError("pressure source report must be an object")
    source = deepcopy(dict(report))
    if "qualification_binding" in source or "unbound_report_hash" in source:
        raise ValueError("pressure source report is already qualification-bound")
    if source.get("schema_version") != PRESSURE_AB_STUDY_SCHEMA_VERSION:
        raise ValueError("pressure source report schema mismatch")
    if (
        source.get("status") != "DEVELOPMENT_ONLY"
        or source.get("qualification_eligible") is not False
        or source.get("difficulty_claim_eligible") is not False
    ):
        raise ValueError("pressure source report claim boundary is invalid")

    source_hash = _digest(source.pop("report_hash", None), "source report_hash")
    if source_hash != sha256_payload(source):
        raise ValueError("pressure source report hash mismatch")
    expected_hash = _digest(
        expected_source_report_hash,
        "expected_source_report_hash",
    )
    if source_hash != expected_hash:
        raise ValueError("evaluator-held source report hash mismatch")

    normalized_model = _identifier(model_id, "model_id")
    normalized_seed = _integer(seed, "seed")
    normalized_trial = _integer(trial_index, "trial_index", minimum=1)
    manifest = source.get("agent_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("pressure source report agent_manifest is required")
    if _identifier(manifest.get("model_id"), "agent_manifest.model_id") != normalized_model:
        raise ValueError("qualification model does not match agent manifest")

    rows = source.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("pressure source report rows are required")
    observed_seeds: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("pressure source report row must be an object")
        conditions = row.get("conditions")
        if not isinstance(conditions, Mapping):
            raise ValueError("pressure row conditions are required")
        spec = conditions.get("spec")
        if not isinstance(spec, Mapping):
            raise ValueError("pressure row spec is required")
        observed_seeds.add(_integer(spec.get("seed"), "row seed"))
    if observed_seeds != {normalized_seed}:
        raise ValueError("pressure row seed does not match qualification binding")

    source["unbound_report_hash"] = source_hash
    source["qualification_binding"] = {
        "model_id": normalized_model,
        "seed": normalized_seed,
        "trial_index": normalized_trial,
        "schema_version": PRESSURE_TRIAL_BINDING_SCHEMA_VERSION,
    }
    source["report_hash"] = sha256_payload(source)
    return source


__all__ = [
    "PRESSURE_TRIAL_BINDING_SCHEMA_VERSION",
    "bind_pressure_trial_report",
]
