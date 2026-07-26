"""Build an integrity-bound aggregate from Pressure Worlds pressure child reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.pressure_campaign import (
    build_pressure_campaign_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Pressure Worlds repeated pressure campaign")
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--expected-model", action="append", required=True)
    parser.add_argument("--seed", type=int, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    reports = [
        json.loads(path.read_text(encoding="utf-8-sig"))
        for path in args.report
    ]
    payload = build_pressure_campaign_report(
        reports,
        campaign_id=args.campaign_id,
        expected_models=args.expected_model,
        expected_seeds=args.seed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if payload["failure_count"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
