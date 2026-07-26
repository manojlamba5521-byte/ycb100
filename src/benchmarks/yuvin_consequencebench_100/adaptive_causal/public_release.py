"""Fail-closed Gate 5 public-development release contracts for Adaptive Causal.

This module can make a deterministic, offline *development* bundle and verify
its contents. It deliberately cannot attest that a bundle was reproduced on
an independent clean machine, and it never makes a sealed-qualification claim.
Those claims require records supplied by independent evaluator operations.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .contracts import canonical_json, sha256_payload


PUBLIC_RELEASE_FILE_SCHEMA_VERSION = "ycb100.acc.public_release.file.v1"
PUBLIC_RELEASE_DESCRIPTOR_SCHEMA_VERSION = "ycb100.acc.public_release.descriptor.v1"
PUBLIC_IMAGE_SCHEMA_VERSION = "ycb100.acc.public_release.image.v1"
CLEAN_MACHINE_RECORD_SCHEMA_VERSION = "ycb100.acc.public_release.clean_machine.v1"
PUBLIC_RELEASE_MANIFEST_SCHEMA_VERSION = "ycb100.acc.public_release.manifest.v1"
PUBLIC_RELEASE_VALIDATION_SCHEMA_VERSION = "ycb100.acc.public_release.validation.v1"

REQUIRED_FILE_ROLES = frozenset(
    {"evaluator", "world_generator", "oracle", "baseline", "corpus", "report"}
)
REQUIRED_DESCRIPTOR_IDS = frozenset(
    {"source_lock", "language_lock", "sbom", "license_inventory", "threat_model", "oci_recipe"}
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@=-]{0,255}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


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
        raise ValueError(f"{field_name} must not escape the public-release root")
    return path.as_posix()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _resolve_under_root(root: Path, relative_path: str) -> tuple[Path | None, str | None]:
    try:
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "release_root_unavailable"
    if not resolved_root.is_dir():
        return None, "release_root_not_directory"
    candidate = resolved_root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except FileNotFoundError:
        return None, "release_file_missing"
    except (OSError, RuntimeError, ValueError):
        return None, "release_path_out_of_root"
    if not resolved.is_file():
        return None, "release_path_not_file"
    return resolved, None


@dataclass(frozen=True)
class PublicReleaseFileV1:
    """One payload file required in an offline development bundle."""

    relative_path: str
    content_sha256: str
    role: str
    schema_version: str = PUBLIC_RELEASE_FILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_RELEASE_FILE_SCHEMA_VERSION:
            raise ValueError("public release file schema version mismatch")
        object.__setattr__(self, "relative_path", _relative_path(self.relative_path, "relative_path"))
        object.__setattr__(self, "content_sha256", _sha256(self.content_sha256, "content_sha256"))
        object.__setattr__(self, "role", _identifier(self.role, "role"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
            "role": self.role,
        }


@dataclass(frozen=True)
class PublicReleaseDescriptorV1:
    """A required release descriptor whose actual bytes are bundled and bound."""

    descriptor_id: str
    relative_path: str
    content_sha256: str
    schema_version: str = PUBLIC_RELEASE_DESCRIPTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_RELEASE_DESCRIPTOR_SCHEMA_VERSION:
            raise ValueError("public release descriptor schema version mismatch")
        object.__setattr__(self, "descriptor_id", _identifier(self.descriptor_id, "descriptor_id"))
        object.__setattr__(self, "relative_path", _relative_path(self.relative_path, "relative_path"))
        object.__setattr__(self, "content_sha256", _sha256(self.content_sha256, "content_sha256"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "descriptor_id": self.descriptor_id,
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class PublicImageDigestV1:
    """A public image reference pinned by immutable OCI digest, never a tag."""

    image_id: str
    image_digest: str
    schema_version: str = PUBLIC_IMAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_IMAGE_SCHEMA_VERSION:
            raise ValueError("public image schema version mismatch")
        object.__setattr__(self, "image_id", _identifier(self.image_id, "image_id"))
        object.__setattr__(self, "image_digest", _sha256(self.image_digest, "image_digest"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "image_id": self.image_id,
            "image_digest": self.image_digest,
        }


@dataclass(frozen=True)
class CleanMachineReproductionRecordV1:
    """A supplied record of one independent clean-machine reproduction.

    The data is deliberately only a signed-record *binding*. This module has
    no authority to establish that its operator or machine is actually
    independent, so consumers must not turn this into a sealed claim.
    """

    record_id: str
    operator_id: str
    machine_fingerprint_hash: str
    bundle_sha256: str
    report_sha256: str
    attestation_sha256: str
    source_commit: str
    schema_version: str = CLEAN_MACHINE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CLEAN_MACHINE_RECORD_SCHEMA_VERSION:
            raise ValueError("clean-machine record schema version mismatch")
        for field_name in ("record_id", "operator_id"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        for field_name in ("machine_fingerprint_hash", "bundle_sha256", "report_sha256", "attestation_sha256"):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        object.__setattr__(self, "source_commit", _commit(self.source_commit, "source_commit"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "operator_id": self.operator_id,
            "machine_fingerprint_hash": self.machine_fingerprint_hash,
            "bundle_sha256": self.bundle_sha256,
            "report_sha256": self.report_sha256,
            "attestation_sha256": self.attestation_sha256,
            "source_commit": self.source_commit,
        }


@dataclass(frozen=True)
class PublicReleaseManifestV1:
    """Deterministic, source-root-independent public development manifest."""

    release_id: str
    source_commit: str
    source_date_epoch: int
    files: tuple[PublicReleaseFileV1, ...]
    descriptors: tuple[PublicReleaseDescriptorV1, ...]
    public_images: tuple[PublicImageDigestV1, ...]
    report_sha256: str
    manifest_hash: str = ""
    release_tier: str = "DEVELOPMENT_ONLY"
    network_default: str = "none"
    schema_version: str = PUBLIC_RELEASE_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_RELEASE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("public release manifest schema version mismatch")
        if self.release_tier != "DEVELOPMENT_ONLY":
            raise ValueError("only DEVELOPMENT_ONLY public releases are valid")
        if self.network_default != "none":
            raise ValueError("public release network_default must be none")
        object.__setattr__(self, "release_id", _identifier(self.release_id, "release_id"))
        object.__setattr__(self, "source_commit", _commit(self.source_commit, "source_commit"))
        if isinstance(self.source_date_epoch, bool) or not isinstance(self.source_date_epoch, int) or self.source_date_epoch < 315532800:
            raise ValueError("source_date_epoch must be an integer no earlier than 1980-01-01")
        files = tuple(self.files)
        descriptors = tuple(self.descriptors)
        images = tuple(self.public_images)
        if not files or not all(isinstance(item, PublicReleaseFileV1) for item in files):
            raise ValueError("files must be non-empty PublicReleaseFileV1 records")
        if not descriptors or not all(isinstance(item, PublicReleaseDescriptorV1) for item in descriptors):
            raise ValueError("descriptors must be non-empty PublicReleaseDescriptorV1 records")
        if not images or not all(isinstance(item, PublicImageDigestV1) for item in images):
            raise ValueError("public_images must be non-empty PublicImageDigestV1 records")
        if len({item.relative_path for item in files}) != len(files):
            raise ValueError("files must not duplicate paths")
        if len({item.descriptor_id for item in descriptors}) != len(descriptors):
            raise ValueError("descriptors must not duplicate descriptor IDs")
        if len({item.image_id for item in images}) != len(images):
            raise ValueError("public_images must not duplicate image IDs")
        object.__setattr__(self, "files", tuple(sorted(files, key=lambda item: item.relative_path)))
        object.__setattr__(self, "descriptors", tuple(sorted(descriptors, key=lambda item: item.descriptor_id)))
        object.__setattr__(self, "public_images", tuple(sorted(images, key=lambda item: item.image_id)))
        object.__setattr__(self, "report_sha256", _sha256(self.report_sha256, "report_sha256"))
        declared = str(self.manifest_hash or "").strip()
        object.__setattr__(self, "manifest_hash", _sha256(declared, "manifest_hash") if declared else self.recomputed_manifest_hash)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "source_commit": self.source_commit,
            "source_date_epoch": self.source_date_epoch,
            "release_tier": self.release_tier,
            "network_default": self.network_default,
            "files": [item.to_dict() for item in self.files],
            "descriptors": [item.to_dict() for item in self.descriptors],
            "public_images": [item.to_dict() for item in self.public_images],
            "report_sha256": self.report_sha256,
        }

    @property
    def recomputed_manifest_hash(self) -> str:
        return sha256_payload(self._hash_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "manifest_hash": self.manifest_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicReleaseManifestV1":
        if not isinstance(value, Mapping):
            raise ValueError("public release manifest must be a mapping")
        try:
            files = tuple(PublicReleaseFileV1(**item) for item in value["files"])
            descriptors = tuple(PublicReleaseDescriptorV1(**item) for item in value["descriptors"])
            images = tuple(PublicImageDigestV1(**item) for item in value["public_images"])
        except (KeyError, TypeError) as error:
            raise ValueError("public release manifest members are invalid") from error
        return cls(
            release_id=value.get("release_id", ""),
            source_commit=value.get("source_commit", ""),
            source_date_epoch=value.get("source_date_epoch"),
            files=files,
            descriptors=descriptors,
            public_images=images,
            report_sha256=value.get("report_sha256", ""),
            manifest_hash=value.get("manifest_hash", ""),
            release_tier=value.get("release_tier", "DEVELOPMENT_ONLY"),
            network_default=value.get("network_default", "none"),
            schema_version=value.get("schema_version", PUBLIC_RELEASE_MANIFEST_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class PublicReleaseValidationResultV1:
    """Verification result. Gate 5 alone never makes a qualification claim."""

    valid: bool
    failures: tuple[str, ...]
    local_determinism_verified: bool
    supplied_clean_machine_record_count: int
    clean_machine_evidence_structurally_complete: bool
    qualification_eligible: bool = False
    schema_version: str = PUBLIC_RELEASE_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "valid": self.valid,
            "failures": list(self.failures),
            "local_determinism_verified": self.local_determinism_verified,
            "supplied_clean_machine_record_count": self.supplied_clean_machine_record_count,
            "clean_machine_evidence_structurally_complete": self.clean_machine_evidence_structurally_complete,
            "qualification_eligible": False,
        }


def _manifest_structure_failures(manifest: PublicReleaseManifestV1) -> list[str]:
    failures: list[str] = []
    if manifest.manifest_hash != manifest.recomputed_manifest_hash:
        failures.append("manifest_hash_mismatch")
    roles = {item.role for item in manifest.files}
    failures.extend("required_file_role_missing:" + role for role in sorted(REQUIRED_FILE_ROLES - roles))
    descriptor_ids = {item.descriptor_id for item in manifest.descriptors}
    failures.extend("required_descriptor_missing:" + item for item in sorted(REQUIRED_DESCRIPTOR_IDS - descriptor_ids))
    files_by_path = {item.relative_path: item for item in manifest.files}
    for descriptor in manifest.descriptors:
        declared_file = files_by_path.get(descriptor.relative_path)
        if declared_file is None:
            failures.append("descriptor_not_in_bundle:" + descriptor.descriptor_id)
        elif declared_file.content_sha256 != descriptor.content_sha256:
            failures.append("descriptor_hash_not_bound:" + descriptor.descriptor_id)
    report_files = [item for item in manifest.files if item.role == "report"]
    if not any(item.content_sha256 == manifest.report_sha256 for item in report_files):
        failures.append("report_hash_not_bound_to_report_file")
    return failures


def validate_public_release_source(manifest: PublicReleaseManifestV1, *, source_root: Path) -> tuple[str, ...]:
    """Reopen every declared source file and reject missing, escaped, or altered data."""
    failures = _manifest_structure_failures(manifest)
    source_root = source_root.expanduser().resolve()
    try:
        top = Path(
            subprocess.run(
                ["git", "-C", str(source_root), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ).resolve()
        head = subprocess.run(
            ["git", "-C", str(top), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            [
                "git",
                "-C",
                str(top),
                "cat-file",
                "-e",
                manifest.source_commit + "^{commit}",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        top = None
        head = ""
        failures.append("release_source_git_commit_unverifiable")
    if top is not None and head != manifest.source_commit:
        failures.append("release_source_commit_not_current_head")
    for item in manifest.files:
        resolved, error = _resolve_under_root(source_root, item.relative_path)
        if error:
            failures.append(error + ":" + item.relative_path)
            continue
        if _file_sha256(resolved) != item.content_sha256:
            failures.append("release_file_hash_mismatch:" + item.relative_path)
        if top is None:
            continue
        try:
            git_relative = resolved.relative_to(top).as_posix()
        except ValueError:
            failures.append("release_file_outside_git_root:" + item.relative_path)
            continue
        try:
            committed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(top),
                    "show",
                    manifest.source_commit + ":" + git_relative,
                ],
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            failures.append("release_file_not_tracked_at_commit:" + item.relative_path)
            continue
        if _bytes_sha256(committed) != item.content_sha256:
            failures.append("release_file_not_bound_to_commit:" + item.relative_path)
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(top),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                git_relative,
            ],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if dirty:
            failures.append("release_file_dirty_or_untracked:" + item.relative_path)
    return tuple(sorted(set(failures)))


def _checksums_text(manifest: PublicReleaseManifestV1) -> bytes:
    rows = [item.content_sha256.removeprefix("sha256:") + "  " + item.relative_path for item in manifest.files]
    return ("\n".join(rows) + "\n").encode("utf-8")


def _archive_entries(manifest: PublicReleaseManifestV1, source_root: Path) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    for item in manifest.files:
        resolved, error = _resolve_under_root(source_root, item.relative_path)
        if error or resolved is None:
            raise ValueError("cannot package invalid public release source")
        entries.append((item.relative_path, resolved.read_bytes()))
    entries.append(("release_manifest.json", (canonical_json(manifest.to_dict()) + "\n").encode("utf-8")))
    entries.append(("checksums.sha256", _checksums_text(manifest)))
    return sorted(entries, key=lambda item: item[0])


def _write_deterministic_zip(destination: Path, entries: Iterable[tuple[str, bytes]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
        for relative_path, content in entries:
            info = zipfile.ZipInfo(relative_path, date_time=_ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content)


def build_public_release_bundle(
    manifest: PublicReleaseManifestV1,
    *,
    source_root: Path,
    destination: Path,
) -> PublicReleaseValidationResultV1:
    """Build a deterministic local bundle after rejecting every unsafe source binding."""
    failures = list(validate_public_release_source(manifest, source_root=source_root))
    local_determinism_verified = False
    if not failures:
        entries = _archive_entries(manifest, source_root)
        _write_deterministic_zip(destination, entries)
        with tempfile.TemporaryDirectory(prefix="ycb100-release-repro-") as temporary:
            replay = Path(temporary) / "replay.zip"
            _write_deterministic_zip(replay, entries)
            local_determinism_verified = destination.read_bytes() == replay.read_bytes()
            if not local_determinism_verified:
                failures.append("local_deterministic_packaging_failed")
        failures.extend(verify_public_release_bundle(destination, expected_manifest=manifest))
    return PublicReleaseValidationResultV1(
        valid=not failures,
        failures=tuple(sorted(set(failures))),
        local_determinism_verified=local_determinism_verified,
        supplied_clean_machine_record_count=0,
        clean_machine_evidence_structurally_complete=False,
    )


def verify_public_release_bundle(
    bundle_path: Path,
    *,
    expected_manifest: PublicReleaseManifestV1 | None = None,
) -> tuple[str, ...]:
    """Verify only archive-contained, content-addressed release data."""
    failures: list[str] = []
    try:
        with zipfile.ZipFile(bundle_path, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                failures.append("bundle_duplicate_paths")
            for name in names:
                try:
                    _relative_path(name, "bundle_path")
                except ValueError:
                    failures.append("bundle_path_invalid:" + name)
            required = {"release_manifest.json", "checksums.sha256"}
            if not required.issubset(names):
                failures.append("bundle_required_metadata_missing")
                return tuple(sorted(set(failures)))
            try:
                embedded = PublicReleaseManifestV1.from_dict(json.loads(archive.read("release_manifest.json")))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return tuple(sorted(set(failures + ["bundle_manifest_invalid"])))
            failures.extend(_manifest_structure_failures(embedded))
            if expected_manifest is not None and embedded.to_dict() != expected_manifest.to_dict():
                failures.append("bundle_manifest_not_expected_manifest")
            expected_names = {item.relative_path for item in embedded.files} | required
            if set(names) != expected_names:
                failures.append("bundle_file_set_mismatch")
            for item in embedded.files:
                if item.relative_path not in names:
                    failures.append("bundle_payload_missing:" + item.relative_path)
                elif _bytes_sha256(archive.read(item.relative_path)) != item.content_sha256:
                    failures.append("bundle_payload_hash_mismatch:" + item.relative_path)
            if "checksums.sha256" in names and archive.read("checksums.sha256") != _checksums_text(embedded):
                failures.append("bundle_checksums_mismatch")
    except (OSError, zipfile.BadZipFile):
        failures.append("bundle_unreadable")
    return tuple(sorted(set(failures)))


def validate_clean_machine_reproduction_records(
    manifest: PublicReleaseManifestV1,
    *,
    bundle_sha256: str,
    records: Sequence[CleanMachineReproductionRecordV1],
) -> PublicReleaseValidationResultV1:
    """Validate supplied record bindings without claiming independent custody."""
    failures = _manifest_structure_failures(manifest)
    try:
        expected_bundle = _sha256(bundle_sha256, "bundle_sha256")
    except ValueError:
        expected_bundle = ""
        failures.append("bundle_sha256_invalid")
    normalized = tuple(records)
    if not all(isinstance(item, CleanMachineReproductionRecordV1) for item in normalized):
        failures.append("clean_machine_record_invalid")
        normalized = tuple(item for item in normalized if isinstance(item, CleanMachineReproductionRecordV1))
    if len({item.record_id for item in normalized}) != len(normalized):
        failures.append("clean_machine_record_duplicate")
    if len({item.operator_id for item in normalized}) != len(normalized):
        failures.append("clean_machine_operator_not_distinct")
    if len({item.machine_fingerprint_hash for item in normalized}) != len(normalized):
        failures.append("clean_machine_fingerprint_not_distinct")
    for item in normalized:
        if item.bundle_sha256 != expected_bundle:
            failures.append("clean_machine_bundle_hash_mismatch:" + item.record_id)
        if item.report_sha256 != manifest.report_sha256:
            failures.append("clean_machine_report_hash_mismatch:" + item.record_id)
        if item.source_commit != manifest.source_commit:
            failures.append("clean_machine_source_commit_mismatch:" + item.record_id)
    complete = len(normalized) >= 2 and not failures
    return PublicReleaseValidationResultV1(
        valid=not failures,
        failures=tuple(sorted(set(failures))),
        local_determinism_verified=False,
        supplied_clean_machine_record_count=len(normalized),
        clean_machine_evidence_structurally_complete=complete,
    )


__all__ = [
    "CLEAN_MACHINE_RECORD_SCHEMA_VERSION",
    "CleanMachineReproductionRecordV1",
    "PUBLIC_RELEASE_MANIFEST_SCHEMA_VERSION",
    "PublicImageDigestV1",
    "PublicReleaseDescriptorV1",
    "PublicReleaseFileV1",
    "PublicReleaseManifestV1",
    "PublicReleaseValidationResultV1",
    "build_public_release_bundle",
    "validate_clean_machine_reproduction_records",
    "validate_public_release_source",
    "verify_public_release_bundle",
]
