from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_excludes_a_poisoned_stale_namespace_stage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source_root = Path(__file__).resolve().parents[1]
    shutil.copytree(source_root / "src", project / "src")
    for name in ("README.md", "pyproject.toml", "setup.py"):
        shutil.copy2(source_root / name, project / name)
    poisoned = project / "build" / "lib" / "benchmarks" / "unrelated_poison.py"
    poisoned.parent.mkdir(parents=True)
    poisoned.write_text("raise RuntimeError('must not ship')\n", encoding="ascii")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    result = subprocess.run(
        [sys.executable, "setup.py", "bdist_wheel", "--dist-dir", str(artifacts)],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    wheel = next(artifacts.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        python_sources = {
            name: archive.read(name).decode("utf-8")
            for name in names
            if name.endswith(".py")
        }

    assert "benchmarks/unrelated_poison.py" not in names
    assert "benchmarks/yuvin_consequencebench_100/adaptive_causal/world/compositional_episode.py" in names
    assert "benchmarks/yuvin_consequencebench_100/adaptive_causal/metric_derivation.py" in names
    assert "benchmarks/yuvin_consequencebench_100/adaptive_causal/data/archetypes.v1.json" in names
    for governed_package in ("arms", "oracle", "scoring", "studies"):
        assert not any(
            f"/adaptive_causal/{governed_package}/" in name
            for name in names
        )
    for source in python_sources.values():
        assert "from core." not in source
        assert "from yuvin." not in source
