"""Deterministic materialization and verification for lifecycle world packs."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import (
    sha256_payload,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.generator import (
    VARIANT_IDS,
    LifecycleWorldBlueprint,
    generate_canonical_worlds,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.oracle import (
    assert_no_oracle_data,
)


FROZEN_PACK_SCHEMA_VERSION = "ycb100.consequence_lifecycle.frozen_pack.v1"
FROZEN_ARCHIVE_SCHEMA_VERSION = "ycb100.consequence_lifecycle.archive.v1"
FROZEN_WORLD_SCHEMA_VERSION = "ycb100.consequence_lifecycle.frozen_world.v1"
FIXED_ZIP_TIME = (2026, 7, 25, 0, 0, 0)
PUBLIC_ARCHIVE_NAME = "ycb100-consequence-lifecycle-public.zip"
EVALUATOR_ARCHIVE_NAME = "ycb100-consequence-lifecycle-evaluator.zip"
RECEIPT_NAME = "ycb100-consequence-lifecycle-pack.json"
def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _safe_relative_path(value: object) -> PurePosixPath:
    text = str(value or "")
    path = PurePosixPath(text)
    if (
        not text
        or path.is_absolute()
        or "\\" in text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("frozen pack contains an unsafe relative path")
    return path


def _source_bindings() -> tuple[dict[str, Any], ...]:
    root = Path(__file__).resolve().parent.parent
    paths = sorted(root.rglob("*.py"))
    paths.append(root / "data" / "archetypes.v1.json")
    rows = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        rows.append(
            {
                "path": "adaptive_causal/" + relative,
                "size_bytes": path.stat().st_size,
                "sha256": _file_hash(path),
            }
        )
    return tuple(rows)


def _world_path(world: LifecycleWorldBlueprint) -> str:
    return f"worlds/{world.scenario_id}/{world.variant_id}.json"


def _world_envelope(
    world: LifecycleWorldBlueprint,
    *,
    evaluator: bool,
) -> dict[str, Any]:
    payload = (
        world.to_evaluator_dict()
        if evaluator
        else world.to_agent_view()
    )
    if not evaluator:
        assert_no_oracle_data(payload)
    return {
        "schema_version": FROZEN_WORLD_SCHEMA_VERSION,
        "visibility": "EVALUATOR_ONLY" if evaluator else "CANDIDATE_SAFE",
        "scenario_id": world.scenario_id,
        "variant_id": world.variant_id,
        "seed": world.seed,
        "world_hash": world.world_hash,
        "payload_hash": sha256_payload(payload),
        "payload": payload,
    }


def _archive_entries(
    worlds: Sequence[LifecycleWorldBlueprint],
    *,
    evaluator: bool,
) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    rows: list[dict[str, Any]] = []
    for world in worlds:
        name = _world_path(world)
        data = _canonical_bytes(_world_envelope(world, evaluator=evaluator))
        entries[name] = data
        rows.append(
            {
                "path": name,
                "scenario_id": world.scenario_id,
                "variant_id": world.variant_id,
                "seed": world.seed,
                "world_hash": world.world_hash,
                "size_bytes": len(data),
                "sha256": _bytes_hash(data),
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": FROZEN_ARCHIVE_SCHEMA_VERSION,
        "visibility": "EVALUATOR_ONLY" if evaluator else "CANDIDATE_SAFE",
        "world_count": len(rows),
        "worlds": rows,
    }
    manifest["manifest_hash"] = sha256_payload(manifest)
    entries["MANIFEST.json"] = _canonical_bytes(manifest)
    return entries


def _write_zip(path: Path, entries: Mapping[str, bytes]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in sorted(entries):
            _safe_relative_path(name)
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, entries[name])
    os.replace(temporary, path)


def materialize_frozen_pack(
    output_directory: str | Path,
    *,
    seed: int = 23,
) -> dict[str, Any]:
    """Write both archives and publish the receipt only after they are durable."""
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    targets = (
        output / PUBLIC_ARCHIVE_NAME,
        output / EVALUATOR_ARCHIVE_NAME,
        output / RECEIPT_NAME,
    )
    if any(path.exists() for path in targets):
        raise FileExistsError("frozen pack targets already exist")

    worlds = tuple(
        world
        for variant_id in VARIANT_IDS
        for world in generate_canonical_worlds(seed=seed, variant_id=variant_id)
    )
    if len(worlds) != 300:
        raise ValueError("frozen pack requires exactly 300 worlds")

    public_path, evaluator_path, receipt_path = targets
    _write_zip(public_path, _archive_entries(worlds, evaluator=False))
    _write_zip(evaluator_path, _archive_entries(worlds, evaluator=True))
    bindings = _source_bindings()
    receipt: dict[str, Any] = {
        "schema_version": FROZEN_PACK_SCHEMA_VERSION,
        "benchmark_id": "YCB-100",
        "track_id": "consequence_lifecycle",
        "release_tier": "DEVELOPMENT_PREVIEW_NOT_QUALIFIED",
        "seed": int(seed),
        "world_count": len(worlds),
        "scenario_count": len({world.scenario_id for world in worlds}),
        "variant_counts": dict(
            sorted(Counter(world.variant_id for world in worlds).items())
        ),
        "source_bindings": list(bindings),
        "source_root_hash": sha256_payload(list(bindings)),
        "artifacts": [
            {
                "role": "candidate_public",
                "path": PUBLIC_ARCHIVE_NAME,
                "size_bytes": public_path.stat().st_size,
                "sha256": _file_hash(public_path),
            },
            {
                "role": "evaluator_private",
                "path": EVALUATOR_ARCHIVE_NAME,
                "size_bytes": evaluator_path.stat().st_size,
                "sha256": _file_hash(evaluator_path),
            },
        ],
        "qualification_eligible": False,
        "execution_tier": "MATERIALIZED_DATA_ONLY",
        "failure_count": 0,
    }
    receipt["pack_hash"] = sha256_payload(receipt)
    _atomic_write(receipt_path, _canonical_bytes(receipt) + b"\n")
    return receipt


def _read_archive(
    path: Path,
    *,
    expected_visibility: str,
) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("frozen archive contains duplicate paths")
            if names != sorted(names) or archive.comment:
                raise ValueError("frozen archive encoding is not canonical")
            for info in infos:
                if (
                    info.date_time != FIXED_ZIP_TIME
                    or info.compress_type != zipfile.ZIP_DEFLATED
                    or info.external_attr != (stat.S_IFREG | 0o644) << 16
                    or info.is_dir()
                ):
                    raise ValueError("frozen archive encoding is not canonical")
            if any(_safe_relative_path(name) is None for name in names):
                raise AssertionError("unreachable")
            if "MANIFEST.json" not in names:
                raise ValueError("frozen archive manifest is missing")
            manifest_bytes = archive.read("MANIFEST.json")
            manifest = json.loads(manifest_bytes)
            if not isinstance(manifest, dict):
                raise ValueError("frozen archive manifest must be an object")
            if manifest_bytes != _canonical_bytes(manifest):
                raise ValueError("frozen archive manifest encoding is not canonical")
            declared_hash = manifest.pop("manifest_hash", None)
            if declared_hash != sha256_payload(manifest):
                raise ValueError("frozen archive manifest hash mismatch")
            manifest["manifest_hash"] = declared_hash
            if (
                manifest.get("schema_version") != FROZEN_ARCHIVE_SCHEMA_VERSION
                or manifest.get("visibility") != expected_visibility
            ):
                raise ValueError("frozen archive manifest contract mismatch")
            rows = manifest.get("worlds")
            if not isinstance(rows, list) or manifest.get("world_count") != len(rows):
                raise ValueError("frozen archive world count mismatch")
            expected_names = {"MANIFEST.json"}
            worlds: dict[tuple[str, str], dict[str, Any]] = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("frozen archive row must be an object")
                name = str(_safe_relative_path(row.get("path")))
                if name != (
                    "worlds/"
                    + str(row.get("scenario_id") or "")
                    + "/"
                    + str(row.get("variant_id") or "")
                    + ".json"
                ):
                    raise ValueError("frozen archive world path binding mismatch")
                expected_names.add(name)
                data = archive.read(name)
                if (
                    row.get("size_bytes") != len(data)
                    or row.get("sha256") != _bytes_hash(data)
                ):
                    raise ValueError("frozen archive child hash mismatch")
                envelope = json.loads(data)
                if not isinstance(envelope, dict):
                    raise ValueError("frozen world envelope must be an object")
                if data != _canonical_bytes(envelope):
                    raise ValueError("frozen world encoding is not canonical")
                if (
                    envelope.get("schema_version") != FROZEN_WORLD_SCHEMA_VERSION
                    or envelope.get("visibility") != expected_visibility
                    or envelope.get("scenario_id") != row.get("scenario_id")
                    or envelope.get("variant_id") != row.get("variant_id")
                    or envelope.get("seed") != row.get("seed")
                    or envelope.get("world_hash") != row.get("world_hash")
                    or envelope.get("payload_hash")
                    != sha256_payload(envelope.get("payload"))
                ):
                    raise ValueError("frozen world envelope binding mismatch")
                key = (str(row["scenario_id"]), str(row["variant_id"]))
                if key in worlds:
                    raise ValueError("frozen archive contains a duplicate world identity")
                if expected_visibility == "CANDIDATE_SAFE":
                    assert_no_oracle_data(envelope["payload"])
                worlds[key] = envelope
            if set(names) != expected_names:
                raise ValueError("frozen archive has undeclared or missing entries")
            return manifest, worlds
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("frozen archive is unreadable") from exc


def verify_frozen_pack(
    receipt_file: str | Path,
    *,
    verify_current_sources: bool = True,
) -> dict[str, Any]:
    """Fail closed on any receipt, artifact, child, join, or source mismatch."""
    receipt_path = Path(receipt_file).expanduser().resolve()
    root = receipt_path.parent
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("frozen pack receipt is unreadable") from exc
    if not isinstance(receipt, dict):
        raise ValueError("frozen pack receipt must be an object")
    if receipt.get("schema_version") != FROZEN_PACK_SCHEMA_VERSION:
        raise ValueError("frozen pack receipt schema mismatch")
    supplied_hash = receipt.pop("pack_hash", None)
    if supplied_hash != sha256_payload(receipt):
        raise ValueError("frozen pack receipt hash mismatch")
    receipt["pack_hash"] = supplied_hash
    for field in ("seed", "world_count", "scenario_count", "failure_count"):
        value = receipt.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("frozen pack counters must be non-negative integers")
    if (
        receipt.get("benchmark_id") != "YCB-100"
        or receipt.get("track_id") != "consequence_lifecycle"
        or receipt.get("release_tier") != "DEVELOPMENT_PREVIEW_NOT_QUALIFIED"
        or receipt.get("execution_tier") != "MATERIALIZED_DATA_ONLY"
        or
        receipt["world_count"] != 300
        or receipt["scenario_count"] != 100
        or receipt["variant_counts"] != {variant: 100 for variant in VARIANT_IDS}
        or receipt["failure_count"] != 0
        or receipt.get("qualification_eligible") is not False
    ):
        raise ValueError("frozen pack receipt completion contract mismatch")
    bindings = receipt.get("source_bindings")
    if (
        not isinstance(bindings, list)
        or receipt.get("source_root_hash") != sha256_payload(bindings)
    ):
        raise ValueError("frozen pack source binding mismatch")
    if verify_current_sources and bindings != list(_source_bindings()):
        raise ValueError("frozen pack source files are stale")

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise ValueError("frozen pack must bind exactly two artifacts")
    by_role: dict[str, Path] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("frozen pack artifact row must be an object")
        role = str(artifact.get("role") or "")
        relative = _safe_relative_path(artifact.get("path"))
        path = (root / Path(*relative.parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("frozen pack artifact escaped its receipt root") from exc
        if role in by_role or role not in {"candidate_public", "evaluator_private"}:
            raise ValueError("frozen pack artifact role mismatch")
        if (
            not path.is_file()
            or path.is_symlink()
            or artifact.get("size_bytes") != path.stat().st_size
            or artifact.get("sha256") != _file_hash(path)
        ):
            raise ValueError("frozen pack artifact hash mismatch")
        by_role[role] = path

    public_manifest, public_worlds = _read_archive(
        by_role["candidate_public"],
        expected_visibility="CANDIDATE_SAFE",
    )
    evaluator_manifest, evaluator_worlds = _read_archive(
        by_role["evaluator_private"],
        expected_visibility="EVALUATOR_ONLY",
    )
    if set(public_worlds) != set(evaluator_worlds):
        raise ValueError("public and evaluator world identities do not match")
    if len(public_worlds) != receipt["world_count"]:
        raise ValueError("frozen pack identity count mismatch")
    expected_worlds = {
        (world.scenario_id, world.variant_id): world
        for variant_id in VARIANT_IDS
        for world in generate_canonical_worlds(
            seed=receipt["seed"],
            variant_id=variant_id,
        )
    }
    if set(expected_worlds) != set(public_worlds):
        raise ValueError("frozen pack does not match the canonical world corpus")
    for key, public in public_worlds.items():
        evaluator = evaluator_worlds[key]
        if (
            public["seed"] != evaluator["seed"]
            or public["world_hash"] != evaluator["world_hash"]
            or evaluator["payload"].get("world_hash") != evaluator["world_hash"]
        ):
            raise ValueError("public/evaluator world join mismatch")
        evaluator_payload = dict(evaluator["payload"])
        evaluator_world_hash = evaluator_payload.pop("world_hash", None)
        if evaluator_world_hash != sha256_payload(evaluator_payload):
            raise ValueError("evaluator world self-hash mismatch")
        expected = expected_worlds[key]
        if public != _world_envelope(expected, evaluator=False):
            raise ValueError("public world does not match canonical regeneration")
        if evaluator != _world_envelope(expected, evaluator=True):
            raise ValueError("evaluator world does not match canonical regeneration")
    report = {
        "schema_version": "ycb100.consequence_lifecycle.frozen_pack_verification.v1",
        "valid": True,
        "pack_hash": receipt["pack_hash"],
        "world_count": len(public_worlds),
        "public_manifest_hash": public_manifest["manifest_hash"],
        "evaluator_manifest_hash": evaluator_manifest["manifest_hash"],
        "source_root_hash": receipt["source_root_hash"],
        "qualification_eligible": False,
        "failure_count": 0,
    }
    report["report_hash"] = sha256_payload(report)
    return report


__all__ = [
    "EVALUATOR_ARCHIVE_NAME",
    "FROZEN_PACK_SCHEMA_VERSION",
    "PUBLIC_ARCHIVE_NAME",
    "RECEIPT_NAME",
    "materialize_frozen_pack",
    "verify_frozen_pack",
]
