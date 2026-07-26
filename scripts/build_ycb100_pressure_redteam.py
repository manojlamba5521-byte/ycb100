"""Build a development-only Pressure Worlds adaptive red-team admission receipt."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_redteam import (
    build_pressure_redteam_admission_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    evaluator_key = os.environ.get("YCB100_PRESSURE_EVALUATOR_KEY", "")
    if len(evaluator_key.encode("utf-8")) < 16:
        raise ValueError(
            "YCB100_PRESSURE_EVALUATOR_KEY must be supplied through the environment"
        )
    report = build_pressure_redteam_admission_report(
        seed=args.seed,
        evaluator_key=evaluator_key,
    ).to_dict()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if report["admission_passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
