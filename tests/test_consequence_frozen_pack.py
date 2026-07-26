from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.frozen_pack import (
    EVALUATOR_ARCHIVE_NAME,
    PUBLIC_ARCHIVE_NAME,
    RECEIPT_NAME,
    _canonical_bytes,
    _write_zip,
    materialize_frozen_pack,
    verify_frozen_pack,
)


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    receipt.pop("pack_hash", None)
    receipt["pack_hash"] = sha256_payload(receipt)
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")


def _rebind_artifact(receipt_path: Path, archive_path: Path) -> None:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    artifact = next(
        row for row in receipt["artifacts"] if row["path"] == archive_path.name
    )
    artifact["size_bytes"] = archive_path.stat().st_size
    artifact["sha256"] = _file_hash(archive_path)
    _write_receipt(receipt_path, receipt)


@pytest.fixture(scope="module")
def frozen_pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("frozen-pack")
    materialize_frozen_pack(root, seed=23)
    return root


def _copy_pack(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


def test_pack_contains_exact_300_joined_worlds_and_verifies(frozen_pack: Path) -> None:
    report = verify_frozen_pack(frozen_pack / RECEIPT_NAME)
    assert report["valid"] is True
    assert report["world_count"] == 300
    assert report["qualification_eligible"] is False
    assert report["failure_count"] == 0


def test_pack_regeneration_is_byte_for_byte_deterministic(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    materialize_frozen_pack(tmp_path, seed=23)
    for name in (PUBLIC_ARCHIVE_NAME, EVALUATOR_ARCHIVE_NAME, RECEIPT_NAME):
        assert (tmp_path / name).read_bytes() == (frozen_pack / name).read_bytes()


def test_public_archive_contains_no_evaluator_oracle(frozen_pack: Path) -> None:
    with zipfile.ZipFile(frozen_pack / PUBLIC_ARCHIVE_NAME) as archive:
        rendered = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name != "MANIFEST.json"
        ).lower()
    for forbidden in (
        b'"oracle"',
        b'"catalog_baseline_outcome"',
        b'"expected_state_diff"',
        b'"mechanism_id"',
        b'"structural_signature"',
    ):
        assert forbidden not in rendered


def test_outer_artifact_tampering_fails_closed(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "tampered")
    archive = root / PUBLIC_ARCHIVE_NAME
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="artifact hash"):
        verify_frozen_pack(root / RECEIPT_NAME)


def test_child_tampering_fails_after_outer_hash_is_reforged(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "child")
    archive_path = root / PUBLIC_ARCHIVE_NAME
    rebuilt = root / "rebuilt.zip"
    with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(
        rebuilt, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.startswith("worlds/"):
                data += b" "
                target.writestr(info, data)
                for remaining in source.infolist()[source.infolist().index(info) + 1 :]:
                    target.writestr(remaining, source.read(remaining.filename))
                break
            target.writestr(info, data)
    rebuilt.replace(archive_path)
    receipt_path = root / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    artifact = next(
        row for row in receipt["artifacts"] if row["role"] == "candidate_public"
    )
    artifact["size_bytes"] = archive_path.stat().st_size
    artifact["sha256"] = _file_hash(archive_path)
    _write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="child hash"):
        verify_frozen_pack(receipt_path)


def test_swapped_public_and_evaluator_roles_fail_closed(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "swapped")
    receipt_path = root / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifacts"][0]["role"], receipt["artifacts"][1]["role"] = (
        receipt["artifacts"][1]["role"],
        receipt["artifacts"][0]["role"],
    )
    _write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="manifest contract"):
        verify_frozen_pack(receipt_path)


def test_out_of_root_artifact_path_fails_closed(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "traversal")
    receipt_path = root / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifacts"][0]["path"] = "../outside.zip"
    _write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="unsafe relative path"):
        verify_frozen_pack(receipt_path)


def test_stale_or_forged_source_binding_fails_closed(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "stale")
    receipt_path = root / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_bindings"][0]["sha256"] = "sha256:" + "0" * 64
    receipt["source_root_hash"] = sha256_payload(receipt["source_bindings"])
    _write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="source files are stale"):
        verify_frozen_pack(receipt_path)


def test_rehashed_forged_public_world_fails_canonical_regeneration(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "forged-public")
    archive_path = root / PUBLIC_ARCHIVE_NAME
    with zipfile.ZipFile(archive_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["MANIFEST.json"])
    row = manifest["worlds"][0]
    envelope = json.loads(entries[row["path"]])
    envelope["payload"]["title"] = "attacker-authored-world"
    envelope["payload_hash"] = sha256_payload(envelope["payload"])
    child = _canonical_bytes(envelope)
    entries[row["path"]] = child
    row["size_bytes"] = len(child)
    row["sha256"] = "sha256:" + hashlib.sha256(child).hexdigest()
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = sha256_payload(manifest)
    entries["MANIFEST.json"] = _canonical_bytes(manifest)
    _write_zip(archive_path, entries)
    _rebind_artifact(root / RECEIPT_NAME, archive_path)

    with pytest.raises(ValueError, match="canonical regeneration"):
        verify_frozen_pack(root / RECEIPT_NAME)


def test_forged_release_identity_and_execution_tier_fail_closed(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "forged-claim")
    receipt_path = root / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["release_tier"] = "NINE_OF_TEN_QUALIFIED"
    receipt["execution_tier"] = "EVALUATOR_OPERATED_MICROVM"
    _write_receipt(receipt_path, receipt)

    with pytest.raises(ValueError, match="completion contract"):
        verify_frozen_pack(receipt_path)


def test_noncanonical_archive_encoding_fails_closed(
    frozen_pack: Path,
    tmp_path: Path,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / "noncanonical-zip")
    archive_path = root / PUBLIC_ARCHIVE_NAME
    with zipfile.ZipFile(archive_path) as archive:
        entries = [(name, archive.read(name)) for name in archive.namelist()]
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in reversed(entries):
            archive.writestr(name, data)
    _rebind_artifact(root / RECEIPT_NAME, archive_path)

    with pytest.raises(ValueError, match="encoding is not canonical"):
        verify_frozen_pack(root / RECEIPT_NAME)


@pytest.mark.parametrize("field,value", [("failure_count", -1), ("world_count", "300")])
def test_invalid_counters_fail_closed(
    frozen_pack: Path,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    root = _copy_pack(frozen_pack, tmp_path / ("counter-" + field))
    receipt_path = root / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt[field] = value
    _write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="counters"):
        verify_frozen_pack(receipt_path)
