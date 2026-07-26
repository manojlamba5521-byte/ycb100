"""Fail-closed validation for development banking score reports."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload


def validate_banking_slice_report(
    report: Mapping[str, Any],
    *,
    expected_report_hash: str | None = None,
) -> tuple[str, ...]:
    """Validate a banking score report against an evaluator-held expectation.

    A report hash only proves that a report is self-consistent.  It cannot
    authenticate a score report because the report author can recompute it.
    Callers therefore must supply the hash captured by the evaluator from the
    measured run before accepting a report.  The expectation intentionally
    stays outside the untrusted report payload.
    """
    if not isinstance(report, Mapping):
        return ("report_not_mapping",)
    failures: list[str] = []
    expected = str(expected_report_hash or "").strip()
    if not expected:
        failures.append("evaluator_expected_report_hash_required")
    elif not expected.startswith("sha256:") or len(expected) != 71:
        failures.append("evaluator_expected_report_hash_invalid")
    if report.get("schema_version") != "ycb100.acc.banking_slice_score_report.v1":
        failures.append("schema_version_invalid")
    if report.get("status") != "PARTIAL_DEVELOPMENT_ONLY":
        failures.append("development_status_invalid")
    if report.get("qualification_eligible") is not False:
        failures.append("qualification_must_be_false")
    measured = report.get("measured_counter_names")
    if not isinstance(measured, list) or not measured or len(measured) != len(set(measured)):
        failures.append("measured_counter_names_invalid")
    paired = report.get("paired_result")
    if not isinstance(paired, Mapping):
        failures.append("paired_result_missing")
    else:
        binding = paired.get("binding")
        if not isinstance(binding, Mapping):
            failures.append("paired_binding_missing")
        else:
            direct = paired.get("direct")
            trace = direct.get("trace") if isinstance(direct, Mapping) else None
            first_trace = trace[0] if isinstance(trace, list) and trace else None
            if not isinstance(first_trace, Mapping):
                failures.append("direct_trace_missing")
            elif binding.get("candidate_hash") != first_trace.get("candidate_hash"):
                failures.append("candidate_trace_binding_mismatch")
    body = dict(report)
    declared_hash = str(body.pop("report_hash", ""))
    try:
        computed_hash = sha256_payload(body)
    except Exception:
        failures.append("report_hash_unverifiable")
    else:
        if declared_hash != computed_hash:
            failures.append("report_hash_mismatch")
        elif expected and declared_hash != expected:
            failures.append("evaluator_expected_report_hash_mismatch")
    return tuple(failures)


__all__ = ["validate_banking_slice_report"]
