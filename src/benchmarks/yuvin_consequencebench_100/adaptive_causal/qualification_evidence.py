"""Local, fail-closed Gate 0 evidence contracts for Adaptive Causal qualification.

These contracts bind local evidence files to a proposed qualification input.
They deliberately do not create a sealed evaluator, attest a release, or make
any claim about benchmark difficulty or safety.  Timing is accepted only as a
non-binding observation and is excluded from every deterministic digest.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contracts import sha256_payload


CORPUS_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.qualification_evidence.corpus.v1"
ORACLE_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.qualification_evidence.oracle.v1"
ENVIRONMENT_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.qualification_evidence.environment.v1"
RED_TEAM_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.qualification_evidence.red_team.v1"
TRUST_BOUNDARY_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.qualification_evidence.trust_boundary.v1"
CHILD_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.qualification_evidence.child.v1"
QUALIFICATION_EVIDENCE_SCHEMA_VERSION = "ycb100.acc.qualification_evidence.bundle.v1"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@=-]{0,255}$")

REQUIRED_BOUNDARY_COMPONENTS = frozenset(
    {
        "participant_image",
        "model_relay",
        "gateway",
        "world",
        "oracle",
        "sealed_store",
        "signing",
        "evaluator_operator",
    }
)
REQUIRED_RED_TEAM_ROUNDS = frozenset({"specification_driven", "open_ended"})
CHILD_EVIDENCE_KINDS = frozenset(
    {"audit", "campaign", "junit", "reproducibility", "review"}
)

_COUNTER_NAMES_BY_KIND: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "corpus": frozenset({"invalid_episode_count", "unmeasured_counter_count"}),
        "oracle": frozenset({"oracle_access_count", "oracle_disagreement_count", "unmeasured_counter_count"}),
        "environment": frozenset(
            {
                "secret_leakage_count",
                "uncontrolled_network_access_count",
                "unmeasured_counter_count",
            }
        ),
        "red_team": frozenset({"confirmed_open_exploit_count", "unmeasured_counter_count"}),
        "trust_boundary": frozenset({"boundary_violation_count", "unmeasured_counter_count"}),
        "child": frozenset({"failure_count", "hard_failure_count", "unmeasured_counter_count"}),
    }
)


def _identifier(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field_name} must be a bounded identifier")
    return text


def _sha256(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{field_name} must be a sha256 digest")
    return text


def _commit(value: Any, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _COMMIT.fullmatch(text):
        raise ValueError(f"{field_name} must be a 40-64 character lowercase git commit")
    return text


def _relative_path(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or "\\" in text or re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"{field_name} must be a relative POSIX path")
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must not escape the evidence root")
    return path.as_posix()


def _tuple_of_identifiers(values: Sequence[Any] | str, field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    normalized = tuple(_identifier(value, field_name) for value in values)
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must be non-empty and unique")
    return normalized


def _counter_mapping(values: Mapping[Any, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    normalized = {_identifier(key, f"{field_name} key"): value for key, value in values.items()}
    return MappingProxyType(dict(sorted(normalized.items())))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _resolve_under_root(root: Path, relative_path: Any) -> tuple[Path | None, str | None]:
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "evidence_root_unavailable"
    if not root.is_dir():
        return None, "evidence_root_not_directory"
    try:
        normalized = _relative_path(relative_path, "relative_path")
    except ValueError:
        return None, "evidence_path_invalid"
    try:
        candidate = root.joinpath(*PurePosixPath(normalized).parts).resolve(strict=False)
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None, "evidence_path_out_of_root"
    if not candidate.exists():
        return None, "evidence_file_missing"
    if not candidate.is_file():
        return None, "evidence_path_not_file"
    return candidate, None


@dataclass(frozen=True)
class _ReceiptBaseV1:
    """Common immutable binding fields for a local evidence receipt."""

    receipt_id: str
    receipt_kind: str
    relative_path: str
    content_sha256: str
    source_commit: str
    counters: Mapping[str, Any]
    observed_elapsed_ms: int | None = field(default=None, compare=False, repr=False)
    receipt_hash: str = ""

    def _validate_common(self, *, expected_kind: str) -> None:
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        if self.receipt_kind != expected_kind:
            raise ValueError(f"receipt_kind must be {expected_kind}")
        object.__setattr__(self, "relative_path", _relative_path(self.relative_path, "relative_path"))
        object.__setattr__(self, "content_sha256", _sha256(self.content_sha256, "content_sha256"))
        object.__setattr__(self, "source_commit", _commit(self.source_commit, "source_commit"))
        object.__setattr__(self, "counters", _counter_mapping(self.counters, "counters"))
        if self.observed_elapsed_ms is not None and (
            isinstance(self.observed_elapsed_ms, bool)
            or not isinstance(self.observed_elapsed_ms, int)
            or self.observed_elapsed_ms < 0
        ):
            raise ValueError("observed_elapsed_ms must be a non-negative integer or None")

    def _common_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "receipt_kind": self.receipt_kind,
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
            "source_commit": self.source_commit,
            "counters": dict(self.counters),
        }

    def _seal_receipt_hash(self, recomputed_hash: str) -> None:
        declared = str(self.receipt_hash or "").strip()
        if declared:
            object.__setattr__(self, "receipt_hash", _sha256(declared, "receipt_hash"))
        else:
            object.__setattr__(self, "receipt_hash", recomputed_hash)


@dataclass(frozen=True)
class CorpusEvidenceReceiptV1(_ReceiptBaseV1):
    corpus_merkle_root: str = ""
    generator_build_hash: str = ""
    seed_derivation_policy_hash: str = ""
    schema_version: str = CORPUS_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_common(expected_kind="corpus")
        if self.schema_version != CORPUS_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("corpus evidence schema version mismatch")
        for name in ("corpus_merkle_root", "generator_build_hash", "seed_derivation_policy_hash"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        self._seal_receipt_hash(self.recomputed_receipt_hash)

    def binding_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self._common_dict(),
            "corpus_merkle_root": self.corpus_merkle_root,
            "generator_build_hash": self.generator_build_hash,
            "seed_derivation_policy_hash": self.seed_derivation_policy_hash,
        }

    @property
    def recomputed_receipt_hash(self) -> str:
        return sha256_payload(self.binding_dict())


@dataclass(frozen=True)
class OracleEvidenceReceiptV1(_ReceiptBaseV1):
    oracle_build_hash: str = ""
    reference_solver_hash: str = ""
    differential_check_hash: str = ""
    oracle_outside_participant: bool = True
    schema_version: str = ORACLE_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_common(expected_kind="oracle")
        if self.schema_version != ORACLE_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("oracle evidence schema version mismatch")
        for name in ("oracle_build_hash", "reference_solver_hash", "differential_check_hash"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        if not isinstance(self.oracle_outside_participant, bool) or not self.oracle_outside_participant:
            raise ValueError("oracle_outside_participant must be true")
        self._seal_receipt_hash(self.recomputed_receipt_hash)

    def binding_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self._common_dict(),
            "oracle_build_hash": self.oracle_build_hash,
            "reference_solver_hash": self.reference_solver_hash,
            "differential_check_hash": self.differential_check_hash,
            "oracle_outside_participant": self.oracle_outside_participant,
        }

    @property
    def recomputed_receipt_hash(self) -> str:
        return sha256_payload(self.binding_dict())


@dataclass(frozen=True)
class EnvironmentEvidenceReceiptV1(_ReceiptBaseV1):
    evaluator_build_hash: str = ""
    participant_image_hash: str = ""
    world_build_hash: str = ""
    isolation_tier: str = ""
    schema_version: str = ENVIRONMENT_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_common(expected_kind="environment")
        if self.schema_version != ENVIRONMENT_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("environment evidence schema version mismatch")
        for name in ("evaluator_build_hash", "participant_image_hash", "world_build_hash"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(self, "isolation_tier", _identifier(self.isolation_tier, "isolation_tier"))
        self._seal_receipt_hash(self.recomputed_receipt_hash)

    def binding_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self._common_dict(),
            "evaluator_build_hash": self.evaluator_build_hash,
            "participant_image_hash": self.participant_image_hash,
            "world_build_hash": self.world_build_hash,
            "isolation_tier": self.isolation_tier,
        }

    @property
    def recomputed_receipt_hash(self) -> str:
        return sha256_payload(self.binding_dict())


@dataclass(frozen=True)
class RedTeamEvidenceReceiptV1(_ReceiptBaseV1):
    issue_tracker_hash: str = ""
    round_kinds: tuple[str, ...] = ()
    schema_version: str = RED_TEAM_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_common(expected_kind="red_team")
        if self.schema_version != RED_TEAM_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("red-team evidence schema version mismatch")
        object.__setattr__(self, "issue_tracker_hash", _sha256(self.issue_tracker_hash, "issue_tracker_hash"))
        rounds = _tuple_of_identifiers(self.round_kinds, "round_kinds")
        if set(rounds) != REQUIRED_RED_TEAM_ROUNDS:
            raise ValueError("round_kinds must exactly name both required red-team rounds")
        object.__setattr__(self, "round_kinds", tuple(sorted(rounds)))
        self._seal_receipt_hash(self.recomputed_receipt_hash)

    def binding_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self._common_dict(),
            "issue_tracker_hash": self.issue_tracker_hash,
            "round_kinds": list(self.round_kinds),
        }

    @property
    def recomputed_receipt_hash(self) -> str:
        return sha256_payload(self.binding_dict())


@dataclass(frozen=True)
class TrustBoundaryEvidenceReceiptV1(_ReceiptBaseV1):
    boundary_model_hash: str = ""
    declared_components: tuple[str, ...] = ()
    schema_version: str = TRUST_BOUNDARY_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_common(expected_kind="trust_boundary")
        if self.schema_version != TRUST_BOUNDARY_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("trust-boundary evidence schema version mismatch")
        object.__setattr__(self, "boundary_model_hash", _sha256(self.boundary_model_hash, "boundary_model_hash"))
        components = _tuple_of_identifiers(self.declared_components, "declared_components")
        if set(components) != REQUIRED_BOUNDARY_COMPONENTS:
            raise ValueError("declared_components must exactly name the required trust boundaries")
        object.__setattr__(self, "declared_components", tuple(sorted(components)))
        self._seal_receipt_hash(self.recomputed_receipt_hash)

    def binding_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self._common_dict(),
            "boundary_model_hash": self.boundary_model_hash,
            "declared_components": list(self.declared_components),
        }

    @property
    def recomputed_receipt_hash(self) -> str:
        return sha256_payload(self.binding_dict())


@dataclass(frozen=True)
class ChildEvidenceReceiptV1(_ReceiptBaseV1):
    child_kind: str = ""
    producer_build_hash: str = ""
    schema_version: str = CHILD_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_common(expected_kind="child")
        if self.schema_version != CHILD_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("child evidence schema version mismatch")
        object.__setattr__(self, "child_kind", _identifier(self.child_kind, "child_kind"))
        if self.child_kind not in CHILD_EVIDENCE_KINDS:
            raise ValueError("child_kind is not a recognized local evidence kind")
        object.__setattr__(self, "producer_build_hash", _sha256(self.producer_build_hash, "producer_build_hash"))
        self._seal_receipt_hash(self.recomputed_receipt_hash)

    def binding_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self._common_dict(),
            "child_kind": self.child_kind,
            "producer_build_hash": self.producer_build_hash,
        }

    @property
    def recomputed_receipt_hash(self) -> str:
        return sha256_payload(self.binding_dict())


@dataclass(frozen=True)
class QualificationEvidenceBundleV1:
    """Exact local evidence set; validation is intentionally not a qualification claim."""

    bundle_id: str
    target_commit: str
    evidence_root: str
    corpus: CorpusEvidenceReceiptV1
    oracle: OracleEvidenceReceiptV1
    environment: EnvironmentEvidenceReceiptV1
    red_team: RedTeamEvidenceReceiptV1
    trust_boundary: TrustBoundaryEvidenceReceiptV1
    child_receipts: tuple[ChildEvidenceReceiptV1, ...]
    expected_child_receipt_ids: tuple[str, ...]
    bundle_hash: str = ""
    schema_version: str = QUALIFICATION_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != QUALIFICATION_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("qualification evidence bundle schema version mismatch")
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, "bundle_id"))
        object.__setattr__(self, "target_commit", _commit(self.target_commit, "target_commit"))
        root = Path(str(self.evidence_root or ""))
        if not root.is_absolute():
            raise ValueError("evidence_root must be an absolute local path")
        object.__setattr__(self, "evidence_root", str(root))
        expected_types = {
            "corpus": CorpusEvidenceReceiptV1,
            "oracle": OracleEvidenceReceiptV1,
            "environment": EnvironmentEvidenceReceiptV1,
            "red_team": RedTeamEvidenceReceiptV1,
            "trust_boundary": TrustBoundaryEvidenceReceiptV1,
        }
        for field_name, expected_type in expected_types.items():
            if not isinstance(getattr(self, field_name), expected_type):
                raise ValueError(f"{field_name} must be {expected_type.__name__}")
        children = tuple(self.child_receipts)
        if not children or not all(isinstance(item, ChildEvidenceReceiptV1) for item in children):
            raise ValueError("child_receipts must be non-empty ChildEvidenceReceiptV1 records")
        object.__setattr__(self, "child_receipts", tuple(sorted(children, key=lambda item: item.receipt_id)))
        object.__setattr__(
            self,
            "expected_child_receipt_ids",
            tuple(sorted(_tuple_of_identifiers(self.expected_child_receipt_ids, "expected_child_receipt_ids"))),
        )
        declared = str(self.bundle_hash or "").strip()
        if declared:
            object.__setattr__(self, "bundle_hash", _sha256(declared, "bundle_hash"))
        else:
            object.__setattr__(self, "bundle_hash", self.recomputed_bundle_hash)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "target_commit": self.target_commit,
            "evidence_root": self.evidence_root,
            "corpus": self.corpus.binding_dict(),
            "oracle": self.oracle.binding_dict(),
            "environment": self.environment.binding_dict(),
            "red_team": self.red_team.binding_dict(),
            "trust_boundary": self.trust_boundary.binding_dict(),
            "child_receipts": [item.binding_dict() for item in self.child_receipts],
            "expected_child_receipt_ids": list(self.expected_child_receipt_ids),
        }

    @property
    def recomputed_bundle_hash(self) -> str:
        return sha256_payload(self._hash_payload())


@dataclass(frozen=True)
class QualificationEvidenceValidationResultV1:
    valid: bool
    failures: tuple[str, ...] = ()


def _record_failure(failures: list[str], failure: str) -> None:
    if failure not in failures:
        failures.append(failure)


def _validate_counter_map(receipt: Any, failures: list[str]) -> None:
    kind = getattr(receipt, "receipt_kind", "")
    expected = _COUNTER_NAMES_BY_KIND.get(kind)
    counters = getattr(receipt, "counters", None)
    receipt_id = str(getattr(receipt, "receipt_id", "unknown"))
    if expected is None:
        _record_failure(failures, f"receipt_kind_unknown:{receipt_id}")
        return
    if not isinstance(counters, Mapping) or set(counters) != set(expected):
        _record_failure(failures, f"counter_schema_invalid:{receipt_id}")
        return
    for counter_name, value in counters.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _record_failure(failures, f"counter_invalid:{receipt_id}:{counter_name}")
            continue
        # Every registered counter is a violation or measurement-completeness
        # counter. None may be averaged away or offset by a favorable metric.
        if value:
            _record_failure(failures, f"counter_nonzero_hard_or_unmeasured:{receipt_id}:{counter_name}")


def _validate_receipt(
    receipt: Any,
    *,
    expected_type: type[Any],
    expected_kind: str,
    expected_schema: str,
    root: Path,
    expected_commit: str,
    failures: list[str],
) -> None:
    receipt_id = str(getattr(receipt, "receipt_id", "unknown"))
    if not isinstance(receipt, expected_type):
        _record_failure(failures, f"receipt_type_invalid:{expected_kind}")
        return
    if getattr(receipt, "receipt_kind", None) != expected_kind:
        _record_failure(failures, f"receipt_kind_invalid:{receipt_id}")
    if getattr(receipt, "schema_version", None) != expected_schema:
        _record_failure(failures, f"receipt_schema_invalid:{receipt_id}")
    try:
        recomputed_hash = sha256_payload(receipt.binding_dict())
    except (AttributeError, TypeError, ValueError):
        _record_failure(failures, f"receipt_binding_invalid:{receipt_id}")
        return
    if getattr(receipt, "receipt_hash", None) != recomputed_hash:
        _record_failure(failures, f"receipt_hash_mismatch:{receipt_id}")
    if getattr(receipt, "source_commit", None) != expected_commit:
        _record_failure(failures, f"receipt_commit_mismatch:{receipt_id}")
    _validate_counter_map(receipt, failures)
    path, problem = _resolve_under_root(root, getattr(receipt, "relative_path", ""))
    if problem:
        _record_failure(failures, f"{problem}:{receipt_id}")
        return
    assert path is not None
    if _file_sha256(path) != getattr(receipt, "content_sha256", None):
        _record_failure(failures, f"receipt_content_hash_mismatch:{receipt_id}")


def validate_qualification_evidence_bundle(
    bundle: QualificationEvidenceBundleV1,
    *,
    expected_commit: str,
) -> QualificationEvidenceValidationResultV1:
    """Reopen an exact local evidence set and report every fail-closed finding."""
    failures: list[str] = []
    try:
        expected_commit = _commit(expected_commit, "expected_commit")
    except ValueError:
        return QualificationEvidenceValidationResultV1(False, ("expected_commit_invalid",))
    if not isinstance(bundle, QualificationEvidenceBundleV1):
        return QualificationEvidenceValidationResultV1(False, ("bundle_type_invalid",))
    if bundle.schema_version != QUALIFICATION_EVIDENCE_SCHEMA_VERSION:
        _record_failure(failures, "bundle_schema_invalid")
    try:
        root = Path(bundle.evidence_root).resolve(strict=True)
    except (OSError, RuntimeError):
        return QualificationEvidenceValidationResultV1(False, ("evidence_root_unavailable",))
    if not root.is_dir():
        return QualificationEvidenceValidationResultV1(False, ("evidence_root_not_directory",))
    if bundle.target_commit != expected_commit:
        _record_failure(failures, "bundle_commit_mismatch")
    try:
        if bundle.bundle_hash != bundle.recomputed_bundle_hash:
            _record_failure(failures, "bundle_hash_mismatch")
    except (AttributeError, TypeError, ValueError):
        _record_failure(failures, "bundle_binding_invalid")

    core = (
        (bundle.corpus, CorpusEvidenceReceiptV1, "corpus", CORPUS_EVIDENCE_SCHEMA_VERSION),
        (bundle.oracle, OracleEvidenceReceiptV1, "oracle", ORACLE_EVIDENCE_SCHEMA_VERSION),
        (bundle.environment, EnvironmentEvidenceReceiptV1, "environment", ENVIRONMENT_EVIDENCE_SCHEMA_VERSION),
        (bundle.red_team, RedTeamEvidenceReceiptV1, "red_team", RED_TEAM_EVIDENCE_SCHEMA_VERSION),
        (bundle.trust_boundary, TrustBoundaryEvidenceReceiptV1, "trust_boundary", TRUST_BOUNDARY_EVIDENCE_SCHEMA_VERSION),
    )
    receipt_ids: list[str] = []
    for receipt, expected_type, kind, schema in core:
        receipt_ids.append(str(getattr(receipt, "receipt_id", "unknown")))
        _validate_receipt(
            receipt,
            expected_type=expected_type,
            expected_kind=kind,
            expected_schema=schema,
            root=root,
            expected_commit=expected_commit,
            failures=failures,
        )

    child_ids: list[str] = []
    children = tuple(bundle.child_receipts)
    for child in children:
        child_id = str(getattr(child, "receipt_id", "unknown"))
        receipt_ids.append(child_id)
        child_ids.append(child_id)
        _validate_receipt(
            child,
            expected_type=ChildEvidenceReceiptV1,
            expected_kind="child",
            expected_schema=CHILD_EVIDENCE_SCHEMA_VERSION,
            root=root,
            expected_commit=expected_commit,
            failures=failures,
        )
        if getattr(child, "child_kind", None) not in CHILD_EVIDENCE_KINDS:
            _record_failure(failures, f"child_kind_unknown:{child_id}")

    for receipt_id in sorted({item for item in receipt_ids if receipt_ids.count(item) > 1}):
        _record_failure(failures, f"receipt_id_duplicate:{receipt_id}")
    expected_children = tuple(bundle.expected_child_receipt_ids)
    if len(expected_children) != len(set(expected_children)):
        _record_failure(failures, "expected_child_receipt_id_duplicate")
    for child_id in sorted(set(expected_children) - set(child_ids)):
        _record_failure(failures, f"child_receipt_missing:{child_id}")
    for child_id in sorted(set(child_ids) - set(expected_children)):
        _record_failure(failures, f"child_receipt_unknown:{child_id}")
    for child_id in sorted({item for item in child_ids if child_ids.count(item) > 1}):
        _record_failure(failures, f"child_receipt_duplicate:{child_id}")
    return QualificationEvidenceValidationResultV1(not failures, tuple(failures))
