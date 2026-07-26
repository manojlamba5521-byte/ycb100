"""Fail-closed custody contracts for Adaptive Causal sealed evaluator evidence.

This module does not launch a microVM or implement cryptography.  It accepts
only independently verified attestation evidence for an evaluator-operated
microVM and rejects local-process and OCI-only claims.  The caller must supply
an attestation verifier owned outside the participant submission path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Callable, Sequence

from .contracts import sha256_payload


SEALED_CUSTODY_SCHEMA_VERSION = "ycb100.acc.sealed_custody.v1"
PARTICIPANT_PIN_SCHEMA_VERSION = "ycb100.acc.sealed_custody.participant_pin.v1"
MICROVM_ATTESTATION_SCHEMA_VERSION = "ycb100.acc.sealed_custody.microvm_attestation.v1"
SEALED_SEED_SCHEMA_VERSION = "ycb100.acc.sealed_custody.seed_commitment.v1"
ENCRYPTED_STORE_SCHEMA_VERSION = "ycb100.acc.sealed_custody.encrypted_store.v1"
KEY_LIFECYCLE_SCHEMA_VERSION = "ycb100.acc.sealed_custody.key_lifecycle.v1"
THRESHOLD_SIGNATURE_SCHEMA_VERSION = "ycb100.acc.sealed_custody.threshold_signature.v1"
RETENTION_DISCLOSURE_SCHEMA_VERSION = "ycb100.acc.sealed_custody.retention_disclosure.v1"
ESCAPE_PROBE_SCHEMA_VERSION = "ycb100.acc.sealed_custody.escape_probe.v1"
INDEPENDENT_ATTESTATION_SCHEMA_VERSION = "ycb100.acc.sealed_custody.independent_attestation.v1"

EVALUATOR_MICROVM_BOUNDARY = "evaluator_operated_microvm"
PARTICIPANT_PAYLOAD_KINDS = frozenset({"oci_image", "source_bundle"})
ENCRYPTION_ALGORITHMS = frozenset({"aes_256_gcm", "xchacha20_poly1305"})
REQUIRED_MICROVM_CONSTRAINTS = frozenset(
    {
        "bounded_scratch",
        "gateway_only_interface",
        "immutable_rootfs",
        "no_cloud_metadata",
        "no_credentials",
        "no_devices",
        "no_docker_socket",
        "no_evaluator_oracle_sources",
        "no_host_mounts",
        "no_network_egress",
        "no_package_install",
        "no_sibling_visibility",
        "non_root_guest",
    }
)
REQUIRED_ESCAPE_PROBES = frozenset(
    {
        "cloud_metadata",
        "docker_socket",
        "evaluator_file_read",
        "hidden_environment",
        "host_mount",
        "network_egress",
        "secret_leakage",
        "sibling_episode",
        "tool_forgery",
        "trace_tamper",
    }
)
LOCAL_OR_OCI_BOUNDARY_VALUES = frozenset(
    {
        "container",
        "docker",
        "local_process",
        "oci",
        "oci_isolated",
        "process",
    }
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@=-]{0,255}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
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
    if not _COMMIT.fullmatch(text):
        raise ValueError(f"{field_name} must be a lowercase 40-64 character git commit")
    return text


def _positive_int(value: Any, field_name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer >= {minimum}")
    return value


def _identifier_tuple(values: Sequence[Any] | str, field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    result = tuple(_identifier(value, field_name) for value in values)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result))


def _require_schema(actual: str, expected: str, subject: str) -> None:
    if actual != expected:
        raise ValueError(f"{subject} schema version mismatch")


@dataclass(frozen=True)
class ParticipantArtifactPinV1:
    submission_id: str
    participant_artifact_hash: str
    source_commit: str
    protocol_version: str
    payload_kind: str
    model_config_hash: str
    schema_version: str = PARTICIPANT_PIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, PARTICIPANT_PIN_SCHEMA_VERSION, "participant pin")
        object.__setattr__(self, "submission_id", _identifier(self.submission_id, "submission_id"))
        object.__setattr__(self, "participant_artifact_hash", _sha256(self.participant_artifact_hash, "participant_artifact_hash"))
        object.__setattr__(self, "source_commit", _commit(self.source_commit, "source_commit"))
        object.__setattr__(self, "protocol_version", _identifier(self.protocol_version, "protocol_version"))
        if self.payload_kind not in PARTICIPANT_PAYLOAD_KINDS:
            raise ValueError("payload_kind must be an immutable participant payload kind")
        object.__setattr__(self, "model_config_hash", _sha256(self.model_config_hash, "model_config_hash"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def pin_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class MicroVMRuntimeAttestationV1:
    attestation_id: str
    evaluator_id: str
    execution_boundary: str
    microvm_backend: str
    host_profile_hash: str
    guest_kernel_hash: str
    guest_rootfs_hash: str
    gateway_build_hash: str
    participant_artifact_hash: str
    measurement_hash: str
    enforced_constraints: tuple[str, ...]
    schema_version: str = MICROVM_ATTESTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, MICROVM_ATTESTATION_SCHEMA_VERSION, "microVM attestation")
        for field_name in ("attestation_id", "evaluator_id", "microvm_backend"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        boundary = _identifier(self.execution_boundary, "execution_boundary")
        backend = self.microvm_backend.lower()
        if boundary != EVALUATOR_MICROVM_BOUNDARY or backend in LOCAL_OR_OCI_BOUNDARY_VALUES:
            raise ValueError("an OCI or local process is not an evaluator-operated microVM")
        object.__setattr__(self, "execution_boundary", boundary)
        for field_name in (
            "host_profile_hash",
            "guest_kernel_hash",
            "guest_rootfs_hash",
            "gateway_build_hash",
            "participant_artifact_hash",
            "measurement_hash",
        ):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        constraints = _identifier_tuple(self.enforced_constraints, "enforced_constraints")
        if frozenset(constraints) != REQUIRED_MICROVM_CONSTRAINTS:
            raise ValueError("enforced_constraints must exactly describe the sealed microVM boundary")
        object.__setattr__(self, "enforced_constraints", constraints)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def attestation_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class SealedSeedCommitmentV1:
    epoch_id: str
    participant_artifact_hash: str
    run_nonce_hash: str
    episode_index: int
    generator_build_hash: str
    oracle_build_hash: str
    policy_hash: str
    corpus_merkle_root: str
    seed_commitment_hash: str
    artifact_pinned_before_seed: bool
    fresh_episode_generated: bool
    schema_version: str = SEALED_SEED_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, SEALED_SEED_SCHEMA_VERSION, "sealed seed commitment")
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        for field_name in (
            "participant_artifact_hash",
            "run_nonce_hash",
            "generator_build_hash",
            "oracle_build_hash",
            "policy_hash",
            "corpus_merkle_root",
            "seed_commitment_hash",
        ):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        object.__setattr__(self, "episode_index", _positive_int(self.episode_index, "episode_index", minimum=0))
        if not self.artifact_pinned_before_seed or not self.fresh_episode_generated:
            raise ValueError("sealed seed must be derived after a pinned artifact for a fresh episode")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def commitment_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class EncryptedEpochStoreV1:
    epoch_id: str
    store_id: str
    encryption_algorithm: str
    active_key_version: str
    encrypted_store_hash: str
    access_policy_hash: str
    schema_version: str = ENCRYPTED_STORE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, ENCRYPTED_STORE_SCHEMA_VERSION, "encrypted epoch store")
        for field_name in ("epoch_id", "store_id", "active_key_version"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        if self.encryption_algorithm not in ENCRYPTION_ALGORITHMS:
            raise ValueError("encryption_algorithm is not an approved authenticated-encryption algorithm")
        for field_name in ("encrypted_store_hash", "access_policy_hash"):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def store_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class KeyLifecycleEvidenceV1:
    key_authority_id: str
    active_key_version: str
    predecessor_key_version: str
    revoked_key_version: str
    rotation_receipt_hash: str
    revocation_receipt_hash: str
    key_custody_policy_hash: str
    rotation_completed: bool
    revocation_completed: bool
    schema_version: str = KEY_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, KEY_LIFECYCLE_SCHEMA_VERSION, "key lifecycle evidence")
        for field_name in ("key_authority_id", "active_key_version", "predecessor_key_version", "revoked_key_version"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        versions = {self.active_key_version, self.predecessor_key_version, self.revoked_key_version}
        if len(versions) != 3:
            raise ValueError("key lifecycle versions must prove rotation and revocation")
        for field_name in ("rotation_receipt_hash", "revocation_receipt_hash", "key_custody_policy_hash"):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        if not self.rotation_completed or not self.revocation_completed:
            raise ValueError("key rotation and revocation must be completed and recorded")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def lifecycle_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class ThresholdSignatureV1:
    signature_set_id: str
    signed_subject_hash: str
    threshold: int
    signer_key_ids: tuple[str, ...]
    signature_bundle_hash: str
    schema_version: str = THRESHOLD_SIGNATURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, THRESHOLD_SIGNATURE_SCHEMA_VERSION, "threshold signature")
        object.__setattr__(self, "signature_set_id", _identifier(self.signature_set_id, "signature_set_id"))
        object.__setattr__(self, "signed_subject_hash", _sha256(self.signed_subject_hash, "signed_subject_hash"))
        signers = _identifier_tuple(self.signer_key_ids, "signer_key_ids")
        object.__setattr__(self, "threshold", _positive_int(self.threshold, "threshold", minimum=2))
        if len(signers) < self.threshold:
            raise ValueError("threshold signature has fewer signers than its threshold")
        object.__setattr__(self, "signer_key_ids", signers)
        object.__setattr__(self, "signature_bundle_hash", _sha256(self.signature_bundle_hash, "signature_bundle_hash"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def signature_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class RetentionDisclosureRecordV1:
    policy_id: str
    retention_days: int
    destruction_process_hash: str
    disclosure_policy_hash: str
    incident_disclosure_channel: str
    participant_notice_hash: str
    schema_version: str = RETENTION_DISCLOSURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, RETENTION_DISCLOSURE_SCHEMA_VERSION, "retention/disclosure record")
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "retention_days", _positive_int(self.retention_days, "retention_days"))
        for field_name in ("destruction_process_hash", "disclosure_policy_hash", "participant_notice_hash"):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        object.__setattr__(self, "incident_disclosure_channel", _identifier(self.incident_disclosure_channel, "incident_disclosure_channel"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def record_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class EscapeProbeResultV1:
    probe_id: str
    probe_kind: str
    outcome: str
    measurement_state: str
    evaluator_record_hash: str
    trace_hash: str
    schema_version: str = ESCAPE_PROBE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, ESCAPE_PROBE_SCHEMA_VERSION, "escape probe")
        object.__setattr__(self, "probe_id", _identifier(self.probe_id, "probe_id"))
        if self.probe_kind not in REQUIRED_ESCAPE_PROBES:
            raise ValueError("probe_kind is not a required sealed-evaluator escape probe")
        if self.outcome != "BLOCKED":
            raise ValueError("escape probe outcome must be BLOCKED")
        if self.measurement_state != "MEASURED":
            raise ValueError("escape probe must be measured")
        for field_name in ("evaluator_record_hash", "trace_hash"):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def result_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class IndependentCustodyAttestationV1:
    attestation_id: str
    attestor_id: str
    attestor_key_id: str
    subject_hash: str
    attestation_bundle_hash: str
    scope: str
    schema_version: str = INDEPENDENT_ATTESTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, INDEPENDENT_ATTESTATION_SCHEMA_VERSION, "independent custody attestation")
        for field_name in ("attestation_id", "attestor_id", "attestor_key_id"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        for field_name in ("subject_hash", "attestation_bundle_hash"):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        if self.scope != "sealed_evaluator_custody":
            raise ValueError("attestation scope must cover sealed evaluator custody")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def attestation_hash(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True)
class SealedEvaluatorCustodyV1:
    custody_id: str
    epoch_id: str
    participant_pin: ParticipantArtifactPinV1
    microvm_attestation: MicroVMRuntimeAttestationV1
    seed_commitment: SealedSeedCommitmentV1
    encrypted_store: EncryptedEpochStoreV1
    key_lifecycle: KeyLifecycleEvidenceV1
    threshold_signature: ThresholdSignatureV1
    retention_disclosure: RetentionDisclosureRecordV1
    escape_probes: tuple[EscapeProbeResultV1, ...]
    independent_attestation: IndependentCustodyAttestationV1
    custody_hash: str = ""
    schema_version: str = SEALED_CUSTODY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, SEALED_CUSTODY_SCHEMA_VERSION, "sealed custody")
        object.__setattr__(self, "custody_id", _identifier(self.custody_id, "custody_id"))
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        probes = tuple(self.escape_probes)
        kinds = tuple(probe.probe_kind for probe in probes)
        if len(kinds) != len(set(kinds)) or frozenset(kinds) != REQUIRED_ESCAPE_PROBES:
            raise ValueError("escape_probes must contain every required probe exactly once")
        object.__setattr__(self, "escape_probes", tuple(sorted(probes, key=lambda probe: probe.probe_kind)))
        declared = str(self.custody_hash or "").strip()
        expected = self.recomputed_custody_hash
        if declared and declared != expected:
            raise ValueError("custody_hash mismatch")
        object.__setattr__(self, "custody_hash", expected)

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "custody_id": self.custody_id,
            "epoch_id": self.epoch_id,
            "participant_pin_hash": self.participant_pin.pin_hash,
            "microvm_attestation_hash": self.microvm_attestation.attestation_hash,
            "seed_commitment_hash": self.seed_commitment.commitment_hash,
            "encrypted_store_hash": self.encrypted_store.store_hash,
            "key_lifecycle_hash": self.key_lifecycle.lifecycle_hash,
            "retention_disclosure_hash": self.retention_disclosure.record_hash,
            "escape_probe_hashes": [probe.result_hash for probe in self.escape_probes],
        }

    @property
    def unsigned_custody_hash(self) -> str:
        return sha256_payload(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.unsigned_dict(),
            "threshold_signature_hash": self.threshold_signature.signature_hash,
            "independent_attestation_hash": self.independent_attestation.attestation_hash,
            "custody_hash": self.custody_hash,
        }

    @property
    def recomputed_custody_hash(self) -> str:
        return sha256_payload(self.to_dict_without_declared_hash())

    def to_dict_without_declared_hash(self) -> dict[str, Any]:
        return {
            **self.unsigned_dict(),
            "threshold_signature_hash": self.threshold_signature.signature_hash,
            "independent_attestation_hash": self.independent_attestation.attestation_hash,
        }


@dataclass(frozen=True)
class SealedCustodyValidationResultV1:
    valid: bool
    qualification_eligible: bool
    failures: tuple[str, ...]
    validation_hash: str
    schema_version: str = SEALED_CUSTODY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


IndependentAttestationVerifier = Callable[[IndependentCustodyAttestationV1], bool]


def validate_sealed_evaluator_custody(
    custody: SealedEvaluatorCustodyV1,
    *,
    independent_attestation_verifier: IndependentAttestationVerifier | None,
) -> SealedCustodyValidationResultV1:
    """Validate Gate 6 evidence without claiming a sealed qualification.

    An independently operated verifier is mandatory.  A participant-provided
    boolean or self-signed text cannot substitute for that verifier.
    """
    failures: list[str] = []

    if custody.custody_hash != custody.recomputed_custody_hash:
        failures.append("custody_hash_mismatch")
    for label, item, hash_name in (
        ("participant_pin", custody.participant_pin, "pin_hash"),
        ("microvm_attestation", custody.microvm_attestation, "attestation_hash"),
        ("seed_commitment", custody.seed_commitment, "commitment_hash"),
        ("encrypted_store", custody.encrypted_store, "store_hash"),
        ("key_lifecycle", custody.key_lifecycle, "lifecycle_hash"),
        ("threshold_signature", custody.threshold_signature, "signature_hash"),
        ("retention_disclosure", custody.retention_disclosure, "record_hash"),
        ("independent_attestation", custody.independent_attestation, "attestation_hash"),
    ):
        try:
            expected = sha256_payload(item.to_dict())
        except (TypeError, ValueError):
            failures.append(f"{label}_serialization_invalid")
            continue
        if getattr(item, hash_name) != expected:
            failures.append(f"{label}_hash_mismatch")

    for probe in custody.escape_probes:
        if probe.result_hash != sha256_payload(probe.to_dict()):
            failures.append(f"escape_probe_hash_mismatch:{probe.probe_kind}")
        if probe.outcome != "BLOCKED":
            failures.append(f"escape_probe_not_blocked:{probe.probe_kind}")
        if probe.measurement_state != "MEASURED":
            failures.append(f"escape_probe_unmeasured:{probe.probe_kind}")
    kinds = [probe.probe_kind for probe in custody.escape_probes]
    for probe_kind in sorted(REQUIRED_ESCAPE_PROBES - set(kinds)):
        failures.append(f"escape_probe_missing:{probe_kind}")
    if len(kinds) != len(set(kinds)):
        failures.append("escape_probe_duplicate")

    pin_hash = custody.participant_pin.participant_artifact_hash
    if custody.microvm_attestation.participant_artifact_hash != pin_hash:
        failures.append("microvm_participant_pin_mismatch")
    if custody.seed_commitment.participant_artifact_hash != pin_hash:
        failures.append("seed_participant_pin_mismatch")
    if custody.seed_commitment.epoch_id != custody.epoch_id:
        failures.append("seed_epoch_mismatch")
    if custody.encrypted_store.epoch_id != custody.epoch_id:
        failures.append("store_epoch_mismatch")
    if custody.encrypted_store.active_key_version != custody.key_lifecycle.active_key_version:
        failures.append("store_active_key_mismatch")
    if custody.microvm_attestation.execution_boundary != EVALUATOR_MICROVM_BOUNDARY:
        failures.append("microvm_boundary_invalid")
    if custody.microvm_attestation.microvm_backend.lower() in LOCAL_OR_OCI_BOUNDARY_VALUES:
        failures.append("microvm_backend_is_local_or_oci")
    if frozenset(custody.microvm_attestation.enforced_constraints) != REQUIRED_MICROVM_CONSTRAINTS:
        failures.append("microvm_constraints_incomplete")
    if not custody.seed_commitment.artifact_pinned_before_seed:
        failures.append("seed_not_bound_after_participant_pin")
    if not custody.seed_commitment.fresh_episode_generated:
        failures.append("fresh_sealed_episode_unmeasured")
    if custody.threshold_signature.signed_subject_hash != custody.unsigned_custody_hash:
        failures.append("threshold_signature_subject_mismatch")
    if custody.independent_attestation.subject_hash != custody.unsigned_custody_hash:
        failures.append("independent_attestation_subject_mismatch")

    if independent_attestation_verifier is None:
        failures.append("independent_attestation_verifier_missing")
    else:
        try:
            independently_verified = independent_attestation_verifier(custody.independent_attestation)
        except Exception:
            independently_verified = False
        if independently_verified is not True:
            failures.append("independent_attestation_unverified")

    normalized_failures = tuple(sorted(set(failures)))
    valid = not normalized_failures
    payload = {
        "schema_version": SEALED_CUSTODY_SCHEMA_VERSION,
        "custody_hash": custody.custody_hash,
        "valid": valid,
        "qualification_eligible": False,
        "failures": normalized_failures,
    }
    return SealedCustodyValidationResultV1(
        valid=valid,
        qualification_eligible=False,
        failures=normalized_failures,
        validation_hash=sha256_payload(payload),
    )


__all__ = [
    "ENCRYPTION_ALGORITHMS",
    "EVALUATOR_MICROVM_BOUNDARY",
    "REQUIRED_ESCAPE_PROBES",
    "REQUIRED_MICROVM_CONSTRAINTS",
    "EncryptedEpochStoreV1",
    "EscapeProbeResultV1",
    "IndependentCustodyAttestationV1",
    "KeyLifecycleEvidenceV1",
    "MicroVMRuntimeAttestationV1",
    "ParticipantArtifactPinV1",
    "RetentionDisclosureRecordV1",
    "SEALED_CUSTODY_SCHEMA_VERSION",
    "SealedCustodyValidationResultV1",
    "SealedEvaluatorCustodyV1",
    "SealedSeedCommitmentV1",
    "ThresholdSignatureV1",
    "validate_sealed_evaluator_custody",
]
