"""Bind one completed pressure report to an evaluator-assigned trial."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_trial_binding import (
    bind_pressure_trial_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-source-hash", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--trial-index", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.resolve() == args.out.resolve():
        raise ValueError("bound report output must differ from the immutable source report")
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    bound = bind_pressure_trial_report(
        report,
        model_id=args.model_id,
        seed=args.seed,
        trial_index=args.trial_index,
        expected_source_report_hash=args.expected_source_hash,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(bound, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
