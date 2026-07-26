"""Executable YUVIN ConsequenceBench-100 evaluation package.

The YCB-100 public-development contracts are portable and must not pull legacy
runner dependencies merely because an evaluator imports this package. Legacy
entry points remain available through lazy compatibility wrappers.
"""

from pathlib import Path


# In the monorepo, retain access to repository-only scripts while the portable
# YCB-100 implementation itself is resolved from this source tree. Installed
# artifacts have no sibling package and therefore remain self-contained.
_REPOSITORY_PACKAGE = Path(__file__).resolve().parents[3]
if (_REPOSITORY_PACKAGE / "scripts").is_dir():
    __path__.append(str(_REPOSITORY_PACKAGE))


def load_catalog(*args: object, **kwargs: object) -> object:
    """Load the historical catalog only when a legacy caller requests it."""
    from benchmarks.yuvin_consequencebench_100.catalog import load_catalog as implementation

    return implementation(*args, **kwargs)


def run_consequencebench(*args: object, **kwargs: object) -> object:
    """Run the historical harness only when a legacy caller requests it."""
    from benchmarks.yuvin_consequencebench_100.runner import run_consequencebench as implementation

    return implementation(*args, **kwargs)


__all__ = ["load_catalog", "run_consequencebench"]
