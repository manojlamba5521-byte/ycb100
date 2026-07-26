"""Fail-closed, local-only qualification evidence contracts for Adaptive Causal.

This module validates files already produced by a qualification run.  It does
not execute an agent, create a sealed runtime, or make any difficulty claim.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as element_tree
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contracts import sha256_payload


AGENT_SUBMISSION_SCHEMA_VERSION = "ycb100.acc.qualification.agent_submission.v1"
CHILD_ARTIFACT_SCHEMA_VERSION = "ycb100.acc.qualification.child_artifact.v1"
QUALIFICATION_EPOCH_SCHEMA_VERSION = "ycb100.acc.qualification.epoch.v1"
QUALIFICATION_MANIFEST_SCHEMA_VERSION = "ycb100.acc.qualification.manifest.v1"

REQUIRED_FAILURE_COUNTERS = (
    "junit_failure_count",
    "campaign_failure_count",
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@=-]{0,255}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


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
    if not _GIT_COMMIT.fullmatch(text):
        raise ValueError(f"{field_name} must be a 40-64 character lowercase git commit")
    return text


def _relative_path(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or "\\" in text or re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"{field_name} must be a relative POSIX path")
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must not escape its artifact root")
    return path.as_posix()


def _string_tuple(values: Sequence[Any] | str, field_name: str, normalizer: Any = _identifier) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    normalized = tuple(normalizer(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


def _frozen_mapping(values: Mapping[Any, Any], field_name: str, value_normalizer: Any) -> Mapping[str, Any]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    normalized = {
        _identifier(key, f"{field_name} key"): value_normalizer(value, f"{field_name}[{key}]")
        for key, value in values.items()
    }
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return MappingProxyType(dict(sorted(normalized.items())))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _resolve_under_root(root: Path, relative_path: str) -> tuple[Path | None, str | None]:
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "artifact_root_unavailable"
    if not root.is_dir():
        return None, "artifact_root_not_directory"
    candidate = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None, "artifact_path_unresolvable"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, "artifact_path_out_of_root"
    if not resolved.exists():
        return None, "artifact_missing"
    if not resolved.is_file():
        return None, "artifact_not_file"
    return resolved, None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_junit(path: Path) -> tuple[set[str], int, list[str]]:
    try:
        root = element_tree.parse(path).getroot()
    except (OSError, element_tree.ParseError):
        return set(), 0, ["junit_parse_failure"]
    if _local_name(root.tag) not in {"testsuite", "testsuites"}:
        return set(), 0, ["junit_root_invalid"]

    test_files: set[str] = set()
    failures = 0
    problems: list[str] = []
    for case in root.iter():
        if _local_name(case.tag) != "testcase":
            continue
        file_name = case.attrib.get("file")
        if file_name is None:
            problems.append("junit_testcase_file_missing")
        else:
            try:
                test_files.add(_relative_path(file_name, "junit testcase file"))
            except ValueError:
                problems.append("junit_testcase_file_invalid")
        failures += sum(1 for member in case if _local_name(member.tag) in {"failure", "error"})
    if not test_files:
        problems.append("junit_testcase_coverage_missing")
    return test_files, failures, problems


@dataclass(frozen=True)
class AgentSubmissionV1:
    """A pinned description of an agent submitted to local qualification."""

    submission_id: str
    agent_manifest_hash: str
    source_commit: str
    model_config_hash: str
    execution_contract_hash: str
    schema_version: str = AGENT_SUBMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_SUBMISSION_SCHEMA_VERSION:
            raise ValueError("agent submission schema version mismatch")
        object.__setattr__(self, "submission_id", _identifier(self.submission_id, "submission_id"))
        for field_name in ("agent_manifest_hash", "model_config_hash", "execution_contract_hash"):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        object.__setattr__(self, "source_commit", _commit(self.source_commit, "source_commit"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def submission_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class ChildArtifactV1:
    """One file that must be reopened and re-hashed during closeout."""

    artifact_id: str
    artifact_kind: str
    relative_path: str
    artifact_sha256: str
    content_schema_version: str
    campaign_id: str
    source_commit: str
    failure_count: Any = 0
    schema_version: str = CHILD_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CHILD_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("child artifact schema version mismatch")
        object.__setattr__(self, "artifact_id", _identifier(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "artifact_kind", _identifier(self.artifact_kind, "artifact_kind"))
        object.__setattr__(self, "relative_path", _relative_path(self.relative_path, "relative_path"))
        object.__setattr__(self, "artifact_sha256", _sha256(self.artifact_sha256, "artifact_sha256"))
        object.__setattr__(self, "content_schema_version", _identifier(self.content_schema_version, "content_schema_version"))
        object.__setattr__(self, "campaign_id", _identifier(self.campaign_id, "campaign_id"))
        object.__setattr__(self, "source_commit", _commit(self.source_commit, "source_commit"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "relative_path": self.relative_path,
            "artifact_sha256": self.artifact_sha256,
            "content_schema_version": self.content_schema_version,
            "campaign_id": self.campaign_id,
            "source_commit": self.source_commit,
            "failure_count": self.failure_count,
        }

    @property
    def artifact_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class QualificationEpochV1:
    """An immutable epoch binding a submission to the expected child records."""

    epoch_id: str
    benchmark_commit: str
    agent_submission_hash: str
    child_artifact_hashes: Mapping[str, str]
    epoch_hash: str = ""
    schema_version: str = QUALIFICATION_EPOCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != QUALIFICATION_EPOCH_SCHEMA_VERSION:
            raise ValueError("qualification epoch schema version mismatch")
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        object.__setattr__(self, "benchmark_commit", _commit(self.benchmark_commit, "benchmark_commit"))
        object.__setattr__(self, "agent_submission_hash", _sha256(self.agent_submission_hash, "agent_submission_hash"))
        object.__setattr__(
            self,
            "child_artifact_hashes",
            _frozen_mapping(self.child_artifact_hashes, "child_artifact_hashes", _sha256),
        )
        declared = str(self.epoch_hash or "").strip()
        if declared:
            object.__setattr__(self, "epoch_hash", _sha256(declared, "epoch_hash"))
        else:
            object.__setattr__(self, "epoch_hash", self.recomputed_epoch_hash)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "epoch_id": self.epoch_id,
            "benchmark_commit": self.benchmark_commit,
            "agent_submission_hash": self.agent_submission_hash,
            "child_artifact_hashes": dict(self.child_artifact_hashes),
        }

    @property
    def recomputed_epoch_hash(self) -> str:
        return sha256_payload(self._hash_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "epoch_hash": self.epoch_hash}


@dataclass(frozen=True)
class QualificationManifestV1:
    """Local closeout input. Every listed evidence item is required evidence."""

    manifest_id: str
    target_commit: str
    artifact_root: str
    agent_submission: AgentSubmissionV1
    epoch: QualificationEpochV1
    child_artifacts: tuple[ChildArtifactV1, ...]
    expected_junit_test_files: tuple[str, ...]
    failure_counters: Mapping[str, Any]
    manifest_hash: str = ""
    schema_version: str = QUALIFICATION_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != QUALIFICATION_MANIFEST_SCHEMA_VERSION:
            raise ValueError("qualification manifest schema version mismatch")
        object.__setattr__(self, "manifest_id", _identifier(self.manifest_id, "manifest_id"))
        object.__setattr__(self, "target_commit", _commit(self.target_commit, "target_commit"))
        root = Path(str(self.artifact_root or ""))
        if not root.is_absolute():
            raise ValueError("artifact_root must be an absolute local path")
        object.__setattr__(self, "artifact_root", str(root))
        if not isinstance(self.agent_submission, AgentSubmissionV1):
            raise ValueError("agent_submission must be AgentSubmissionV1")
        if not isinstance(self.epoch, QualificationEpochV1):
            raise ValueError("epoch must be QualificationEpochV1")
        artifacts = tuple(self.child_artifacts)
        if not artifacts or not all(isinstance(item, ChildArtifactV1) for item in artifacts):
            raise ValueError("child_artifacts must be non-empty ChildArtifactV1 records")
        object.__setattr__(self, "child_artifacts", artifacts)
        junit_files = _string_tuple(self.expected_junit_test_files, "expected_junit_test_files", _relative_path)
        if not junit_files:
            raise ValueError("expected_junit_test_files must not be empty")
        object.__setattr__(self, "expected_junit_test_files", junit_files)
        if not isinstance(self.failure_counters, Mapping):
            raise ValueError("failure_counters must be a mapping")
        object.__setattr__(self, "failure_counters", MappingProxyType(dict(self.failure_counters)))
        declared = str(self.manifest_hash or "").strip()
        if declared:
            object.__setattr__(self, "manifest_hash", _sha256(declared, "manifest_hash"))
        else:
            object.__setattr__(self, "manifest_hash", self.recomputed_manifest_hash)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "target_commit": self.target_commit,
            "artifact_root": self.artifact_root,
            "agent_submission": self.agent_submission.to_dict(),
            "epoch": self.epoch.to_dict(),
            "child_artifacts": [artifact.to_dict() for artifact in self.child_artifacts],
            "expected_junit_test_files": list(self.expected_junit_test_files),
            "failure_counters": dict(self.failure_counters),
        }

    @property
    def recomputed_manifest_hash(self) -> str:
        return sha256_payload(self._hash_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "manifest_hash": self.manifest_hash}


@dataclass(frozen=True)
class QualificationValidationResultV1:
    """A deterministic validation result; any finding makes a closeout invalid."""

    valid: bool
    failures: tuple[str, ...] = field(default_factory=tuple)
    observed_junit_test_files: tuple[str, ...] = field(default_factory=tuple)
    observed_junit_failure_count: int = 0


def validate_qualification_manifest(
    manifest: QualificationManifestV1,
    *,
    expected_commit: str,
) -> QualificationValidationResultV1:
    """Reopen local evidence and reject every integrity or coverage discrepancy."""
    failures: list[str] = []
    observed_junit_files: set[str] = set()
    observed_junit_failure_count = 0

    try:
        expected_commit = _commit(expected_commit, "expected_commit")
    except ValueError:
        failures.append("expected_commit_invalid")
        expected_commit = ""

    if manifest.manifest_hash != manifest.recomputed_manifest_hash:
        failures.append("manifest_hash_mismatch")
    if manifest.epoch.epoch_hash != manifest.epoch.recomputed_epoch_hash:
        failures.append("epoch_hash_mismatch")
    if manifest.epoch.agent_submission_hash != manifest.agent_submission.submission_hash:
        failures.append("agent_submission_hash_mismatch")

    for label, commit in (
        ("manifest", manifest.target_commit),
        ("epoch", manifest.epoch.benchmark_commit),
        ("agent_submission", manifest.agent_submission.source_commit),
    ):
        if expected_commit and commit != expected_commit:
            failures.append(f"{label}_commit_mismatch")

    artifact_ids = [artifact.artifact_id for artifact in manifest.child_artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        failures.append("child_artifact_id_duplicate")
    expected_ids = set(manifest.epoch.child_artifact_hashes)
    actual_ids = set(artifact_ids)
    if expected_ids - actual_ids:
        failures.append("child_artifact_missing")
    if actual_ids - expected_ids:
        failures.append("child_artifact_unexpected")

    counter_names = set(manifest.failure_counters)
    required_counter_names = set(REQUIRED_FAILURE_COUNTERS)
    if counter_names - required_counter_names:
        failures.append("failure_counter_unexpected")
    if required_counter_names - counter_names:
        failures.append("failure_counter_missing")
    counters_valid: dict[str, int] = {}
    for name in sorted(required_counter_names & counter_names):
        value = manifest.failure_counters[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            failures.append(f"failure_counter_invalid:{name}")
        else:
            counters_valid[name] = value

    root = Path(manifest.artifact_root)
    campaign_failure_count = 0
    for artifact in sorted(manifest.child_artifacts, key=lambda item: item.artifact_id):
        if expected_commit and artifact.source_commit != expected_commit:
            failures.append(f"child_artifact_commit_mismatch:{artifact.artifact_id}")
        expected_hash = manifest.epoch.child_artifact_hashes.get(artifact.artifact_id)
        if expected_hash != artifact.artifact_hash:
            failures.append(f"child_artifact_descriptor_hash_mismatch:{artifact.artifact_id}")
        if not isinstance(artifact.failure_count, int) or isinstance(artifact.failure_count, bool) or artifact.failure_count < 0:
            failures.append(f"child_artifact_failure_count_invalid:{artifact.artifact_id}")
        else:
            campaign_failure_count += artifact.failure_count if artifact.artifact_kind != "junit" else 0

        path, error = _resolve_under_root(root, artifact.relative_path)
        if error:
            failures.append(f"{error}:{artifact.artifact_id}")
            continue
        assert path is not None
        if _file_sha256(path) != artifact.artifact_sha256:
            failures.append(f"child_artifact_content_hash_mismatch:{artifact.artifact_id}")
            continue
        if artifact.artifact_kind == "junit":
            test_files, junit_failures, junit_problems = _parse_junit(path)
            observed_junit_files.update(test_files)
            observed_junit_failure_count += junit_failures
            failures.extend(f"{problem}:{artifact.artifact_id}" for problem in junit_problems)
            if isinstance(artifact.failure_count, int) and not isinstance(artifact.failure_count, bool) and artifact.failure_count >= 0:
                if artifact.failure_count != junit_failures:
                    failures.append(f"child_artifact_failure_count_mismatch:{artifact.artifact_id}")

    expected_junit_files = set(manifest.expected_junit_test_files)
    if observed_junit_files != expected_junit_files:
        failures.append("junit_coverage_mismatch")
    if counters_valid.get("junit_failure_count") != observed_junit_failure_count:
        failures.append("junit_failure_counter_mismatch")
    if counters_valid.get("campaign_failure_count") != campaign_failure_count:
        failures.append("campaign_failure_counter_mismatch")
    if any(value > 0 for value in counters_valid.values()):
        failures.append("declared_failure_counter_nonzero")

    return QualificationValidationResultV1(
        valid=not failures,
        failures=tuple(sorted(set(failures))),
        observed_junit_test_files=tuple(sorted(observed_junit_files)),
        observed_junit_failure_count=observed_junit_failure_count,
    )


__all__ = [
    "AGENT_SUBMISSION_SCHEMA_VERSION",
    "AgentSubmissionV1",
    "CHILD_ARTIFACT_SCHEMA_VERSION",
    "ChildArtifactV1",
    "QUALIFICATION_EPOCH_SCHEMA_VERSION",
    "QUALIFICATION_MANIFEST_SCHEMA_VERSION",
    "QualificationEpochV1",
    "QualificationManifestV1",
    "QualificationValidationResultV1",
    "REQUIRED_FAILURE_COUNTERS",
    "validate_qualification_manifest",
]
