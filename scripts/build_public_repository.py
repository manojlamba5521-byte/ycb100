"""Build a deterministic, allowlisted ConsequenceBench GitHub source snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
ROOT_FILES = (
    ".editorconfig",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "CHANGELOG.md",
    "CITATION.cff",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
    "setup.py",
)
DIRECTORIES = (
    ".github",
    "docs",
    "results",
    "scripts",
    "src",
    "tests",
)
EXCLUDED_DIRECTORY_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    "arms",
    "oracle",
    "scoring",
    "studies",
}
EXCLUDED_SCRIPT_NAMES = {
    "run_ycb100_agent_ab_study.py",
    "run_ycb100_codex_cli_feedback_ab.py",
    "run_ycb100_compositional_paired_replay.py",
    "run_ycb100_ollama_feedback_ab.py",
    "run_ycb100_ollama_pressure_ab.py",
    "run_ycb100_pressure_agent_ab.py",
    "run_ycb100_public.py",
    "run_ycb100_public_causal_controls.py",
    "run_ycb100_vertex_gemini_ab.py",
    "run_ycb100_vertex_gemini_feedback_ab.py",
    "run_ycb100_vertex_gemini_pressure_ab.py",
}
PUBLIC_TEST_NAMES = {
    "conftest.py",
    "test_development_leaderboard.py",
    "test_public_repository.py",
    "test_scenario_manifest.py",
    "test_adaptive_causal_portable_entrypoint.py",
    "test_adaptive_causal_package_isolation.py",
    "test_consequence_lifecycle_admission.py",
    "test_consequence_lifecycle_cli.py",
    "test_consequence_lifecycle_environment.py",
    "test_consequence_lifecycle_generator.py",
    "test_consequence_lifecycle_paired.py",
    "test_consequence_lifecycle_reference.py",
    "test_consequence_lifecycle_store.py",
    "test_consequence_frozen_pack.py",
    "test_pressure_effect_binding.py",
}
PUBLIC_DOC_NAMES = {
    "CATALOG.md",
    "CLAIMS_AND_EVIDENCE.md",
    "CONSEQUENCE_LIFECYCLE_PROTOCOL.md",
    "INDEPENDENT_EVALUATION.md",
    "INDEX.md",
    "LEADERBOARD.md",
    "LIMITATIONS.md",
    "RUN_A_CANDIDATE.md",
    "SCORING.md",
    "SUBMIT_RESULTS.md",
    "VALIDITY_HARDENING.md",
    "YCB100_BENCHMARK_PLAN.md",
    "YCB100_EVALUATOR_HANDBOOK.md",
    "YCB100_OPERATOR_GUIDE.md",
    "YCB100_QUALIFICATION_PLAN.md",
    "YCB100_THREAT_MODEL.md",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".log",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}
SECRET_PATTERNS = (
    re.compile(rb"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(rb"ghp_[A-Za-z0-9]{16,}"),
    re.compile(rb"sk_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(
        rb"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)"
        rb"://[^/\s:@]+:[^@\s/]+@"
    ),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        rb"\beyJ[A-Za-z0-9_-]{12,}\.eyJ[A-Za-z0-9_-]{12,}\."
        rb"[A-Za-z0-9_-]{12,}\b"
    ),
    re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}\b"),
    re.compile(
        rb"(?i)\b(?:aws_secret_access_key|client_secret|api_key|access_token|"
        rb"refresh_token|password)\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{20,}"
    ),
    re.compile(rb"-----BEGIN (?:OPENSSH )?PRIVATE KEY-----"),
)
FIXED_ZIP_TIME = (2026, 7, 25, 0, 0, 0)
ARCHIVE_ROOT = "ConsequenceBench-" + VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _is_public_file(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
        return False
    if any(part.casefold().endswith(".egg-info") for part in relative.parts):
        return False
    if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
        return False
    if relative.parts[0] == "scripts" and path.name in EXCLUDED_SCRIPT_NAMES:
        return False
    if relative.parts[0] == "docs":
        is_leaderboard_asset = (
            len(relative.parts) == 3
            and relative.parts[1] == "assets"
            and path.suffix.casefold() == ".svg"
        )
        if path.name not in PUBLIC_DOC_NAMES and not is_leaderboard_asset:
            return False
    if relative.parts[0] == "tests" and path.name not in PUBLIC_TEST_NAMES:
        return False
    return path.is_file() and not path.is_symlink()


def _source_files() -> list[Path]:
    files = [ROOT / name for name in ROOT_FILES]
    for directory_name in DIRECTORIES:
        directory = ROOT / directory_name
        files.extend(path for path in directory.rglob("*") if _is_public_file(path))
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise ValueError("missing required release files: " + ", ".join(missing))
    return sorted(set(files), key=lambda item: item.relative_to(ROOT).as_posix())


def _scan_file(path: Path) -> None:
    data = path.read_bytes()
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise ValueError(
                f"credential-like marker in {path.relative_to(ROOT).as_posix()}"
            )


def _copy_files(files: Iterable[Path], output: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in files:
        _scan_file(source)
        relative = source.relative_to(ROOT)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        rows.append(
            {
                "path": relative.as_posix(),
                "size_bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )
    return rows


def _write_deterministic_zip(source: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(ARCHIVE_ROOT) / path.relative_to(source)
            info = zipfile.ZipInfo(relative.as_posix(), FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())


def build_public_repository(output: Path) -> dict[str, object]:
    output = output.resolve()
    release_root = (ROOT / "release").resolve()
    if output == ROOT or ROOT in output.parents and release_root not in output.parents:
        raise ValueError("output must be outside source or under the release directory")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    source_files = _source_files()
    for source in source_files:
        _scan_file(source)
    output.mkdir(parents=True)
    rows = _copy_files(source_files, output)
    body: dict[str, object] = {
        "schema_version": "consequencebench.public_repository_integrity.v1",
        "benchmark_id": "CONSEQUENCEBENCH",
        "version": VERSION,
        "release_tier": "DEVELOPMENT_PREVIEW_NOT_QUALIFIED",
        "file_count": len(rows),
        "files": rows,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body["manifest_hash"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    manifest_path = output / "PUBLIC_REPOSITORY_INTEGRITY.json"
    manifest_path.write_text(
        json.dumps(body, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    archive_path = output.parent / f"{output.name}.zip"
    if archive_path.exists():
        raise FileExistsError(f"archive already exists: {archive_path}")
    _write_deterministic_zip(output, archive_path)
    receipt = {
        "schema_version": "consequencebench.public_repository_archive.v1",
        "archive": archive_path.name,
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": _sha256(archive_path),
        "source_manifest_hash": body["manifest_hash"],
        "source_file_count": len(rows),
        "qualification_eligible": False,
        "failure_count": 0,
    }
    receipt_path = output.parent / f"{output.name}.integrity.json"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = build_public_repository(args.out)
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
