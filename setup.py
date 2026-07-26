"""Build hardening for the standalone ConsequenceBench distribution.

Setuptools can retain unrelated modules under ``build/lib/benchmarks`` from a
previous invocation.  This project deliberately ships only the adaptive-causal namespace,
so the generated namespace staging directory is cleared before each build.
"""
from __future__ import annotations

from pathlib import Path
from shutil import rmtree

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


PUBLIC_PACKAGES = [
    "benchmarks.yuvin_consequencebench_100",
    "benchmarks.yuvin_consequencebench_100.adaptive_causal",
    "benchmarks.yuvin_consequencebench_100.adaptive_causal.agents",
    "benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle",
    "benchmarks.yuvin_consequencebench_100.adaptive_causal.reports",
    "benchmarks.yuvin_consequencebench_100.adaptive_causal.runner",
    "benchmarks.yuvin_consequencebench_100.adaptive_causal.world",
]


class IsolatedYcb100BuildPy(_build_py):
    """Remove stale generated namespace contents before copying ConsequenceBench sources."""

    def run(self) -> None:
        build_root = Path(self.build_lib).resolve()
        namespace_root = build_root / "benchmarks"
        try:
            namespace_root.relative_to(build_root)
        except ValueError as exc:  # Defensive; this path must remain generated output.
            raise RuntimeError("refusing to clear a build path outside build_lib") from exc
        if namespace_root.exists():
            rmtree(namespace_root)
        super().run()


setup(
    cmdclass={"build_py": IsolatedYcb100BuildPy},
    include_package_data=False,
    package_dir={"": "src"},
    packages=PUBLIC_PACKAGES,
)
