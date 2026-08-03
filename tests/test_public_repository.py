from __future__ import annotations

import importlib
import importlib.util
import json
import re
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import unquote

import pytest

from benchmarks.yuvin_consequencebench_100.adaptive_causal.cli import (
    main,
    run_public_controls,
)
from benchmarks.yuvin_consequencebench_100.adaptive_causal.scenario_manifest import (
    validate_scenario_manifest,
)


def test_public_package_has_no_required_yuvin_runtime_import() -> None:
    package = importlib.import_module(
        "benchmarks.yuvin_consequencebench_100.adaptive_causal"
    )

    assert package is not None
    assert validate_scenario_manifest()["failure_count"] == 0
    assert run_public_controls()["failure_count"] == 0


def test_public_export_excludes_vendor_specific_adapters() -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "build_public_repository.py"
    spec = importlib.util.spec_from_file_location("build_public_repository", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    exported = {
        path.relative_to(root).as_posix()
        for path in module._source_files()
    }

    assert not any(path.startswith("integrations/") for path in exported)
    assert "tests/test_yuvin_pressure_integration.py" not in exported


def test_cli_writes_machine_readable_validation_receipts(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.json"
    controls_path = tmp_path / "controls.json"

    assert main(["validate-scenarios", "--out", str(scenario_path)]) == 0
    assert main(["public-controls", "--out", str(controls_path)]) == 0
    assert json.loads(scenario_path.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(controls_path.read_text(encoding="utf-8"))["failure_count"] == 0


def test_public_repository_essential_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]

    required = {
        ".github/workflows/ci.yml",
        "CHANGELOG.md",
        "CITATION.cff",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "GOVERNANCE.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "docs/CLAIMS_AND_EVIDENCE.md",
        "docs/INDEPENDENT_EVALUATION.md",
        "docs/LEADERBOARD.md",
        "docs/LIMITATIONS.md",
        "docs/RUN_A_CANDIDATE.md",
        "docs/SUBMIT_RESULTS.md",
        "docs/YCB100_BENCHMARK_PLAN.md",
        "docs/YCB100_QUALIFICATION_PLAN.md",
        "results/development_leaderboard.v1.json",
    }
    assert not sorted(path for path in required if not (root / path).is_file())


def test_public_distribution_uses_consequencebench_identity() -> None:
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "consequencebench"
    assert metadata["project"]["scripts"]["consequencebench"].endswith(":main")
    assert metadata["project"]["scripts"]["ycb100"] == (
        metadata["project"]["scripts"]["consequencebench"]
    )
    assert metadata["project"]["urls"]["Repository"] == (
        "https://github.com/yuvin-labs/consequencebench"
    )


def test_public_repository_excludes_generated_package_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "build_public_repository.py"
    spec = importlib.util.spec_from_file_location("build_public_repository", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    generated = root / "src" / "example.egg-info" / "PKG-INFO"
    assert module._is_public_file(generated) is False
    exported = {
        path.relative_to(root).as_posix()
        for path in module._source_files()
    }
    assert not any(".egg-info/" in path for path in exported)


@pytest.mark.parametrize(
    "secret",
    (
        "postgresql://" + "demo:ThisIsARealPassword123@localhost/db",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "eyJhbGciOiJIUzI1NiJ9"
        + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "Authorization: Bearer " + "abcdefghijklmnopqrstuvwxyz0123456789",
        "aws_secret_access_key=" + "abcdefghijklmnopqrstuvwxyz0123456789ABCD",
    ),
)
def test_public_export_rejects_unknown_credential_classes(
    tmp_path: Path,
    secret: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "build_public_repository.py"
    spec = importlib.util.spec_from_file_location("build_public_repository", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = tmp_path / "probe.txt"
    probe.write_text(secret, encoding="utf-8")
    module.ROOT = tmp_path

    with pytest.raises(ValueError, match="credential-like marker"):
        module._scan_file(probe)


def test_public_archive_bytes_do_not_depend_on_output_directory_name(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "build_public_repository.py"
    spec = importlib.util.spec_from_file_location("build_public_repository", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    left = tmp_path / "left-name"
    right = tmp_path / "right-name"
    left.mkdir()
    right.mkdir()
    for directory in (left, right):
        (directory / "README.md").write_text("same bytes\n", encoding="utf-8")
    left_zip = tmp_path / "left.zip"
    right_zip = tmp_path / "right.zip"

    module._write_deterministic_zip(left, left_zip)
    module._write_deterministic_zip(right, right_zip)

    assert left_zip.read_bytes() == right_zip.read_bytes()
    with zipfile.ZipFile(left_zip) as archive:
        assert archive.namelist() == ["ConsequenceBench-0.1.0/README.md"]


def test_public_markdown_local_links_resolve() -> None:
    root = Path(__file__).resolve().parents[1]
    markdown_files = [
        root / "README.md",
        *sorted((root / "docs").glob("*.md")),
    ]
    failures: list[str] = []
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for markdown in markdown_files:
        for raw_target in pattern.findall(markdown.read_text(encoding="utf-8")):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if (
                not target
                or target.startswith(("#", "http://", "https://", "mailto:"))
            ):
                continue
            path_text = unquote(target.split("#", 1)[0])
            resolved = (markdown.parent / path_text).resolve()
            if not resolved.exists():
                failures.append(
                    f"{markdown.relative_to(root).as_posix()} -> {target}"
                )
    assert not failures
