"""Build and verify an Adaptive Causal Gate 5 public-development release bundle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from benchmarks.yuvin_consequencebench_100.adaptive_causal.public_release import (
    PublicReleaseManifestV1,
    build_public_release_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Adaptive Causal public-development bundle")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        manifest = PublicReleaseManifestV1.from_dict(json.loads(args.manifest.read_text(encoding="utf-8")))
        result = build_public_release_bundle(manifest, source_root=args.source_root, destination=args.out)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "schema_version": "ycb100.acc.public_release.build_report.v1",
                    "valid": False,
                    "qualification_eligible": False,
                    "failures": ["release_build_input_invalid:" + type(error).__name__],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 3

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if result.valid else 3


if __name__ == "__main__":
    raise SystemExit(main())
