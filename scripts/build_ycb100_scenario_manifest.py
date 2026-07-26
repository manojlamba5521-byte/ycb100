"""Build the canonical ConsequenceBench catalog-to-world binding manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "ycb100.scenario_manifest.v1"
BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = BENCHMARK_ROOT / "docs" / "CATALOG.md"
FAMILY_IDS = {
    "authority_policy": "authority_and_policy",
    "evidence_provenance": "evidence_and_provenance",
    "execution_recovery": "execution_and_recovery",
    "delayed_consequence": "delayed_consequence",
}
CATALOG_DOMAIN_IDS = {
    "FIN": "banking",
    "CYB": "cybersecurity",
    "ENR": "energy",
    "HLT": "healthcare",
    "COD": "software_delivery",
}
CATALOG_LENSES = {
    "A": "authority_policy",
    "B": "evidence_provenance",
    "C": "execution_recovery",
    "D": "delayed_consequence",
}
HEADER = re.compile(
    r"^### ((?:FIN|CYB|ENR|HLT|COD)-([A-D])\d{2}) - (.+)$",
    re.MULTILINE,
)


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _field(block: str, name: str) -> str:
    match = re.search(
        rf"^- \*\*{re.escape(name)}:\*\* (.*?)(?=^- \*\*|\Z)",
        block,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ValueError(f"scenario block missing {name}")
    return " ".join(match.group(1).strip().split())


def _catalog_rows() -> list[dict[str, str]]:
    text = CATALOG_PATH.read_text(encoding="utf-8")
    matches = list(HEADER.finditer(text))
    rows: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else text.index("## Corpus Balance Receipt")
        )
        block = text[match.start():end]
        scenario_id = match.group(1)
        prefix, suffix = scenario_id.split("-", 1)
        class_match = re.fullmatch(
            r"[^;]+;\s*(critical|high|medium|low);\s*"
            r"`(VERIFIED|DENIED|RECOVERED_VERIFIED|OBLIGATION_OPEN|COMPENSATED)`\.",
            _field(block, "Class"),
        )
        if class_match is None:
            raise ValueError(f"{scenario_id} has an invalid Class field")
        rows.append(
            {
                "scenario_id": scenario_id,
                "title": match.group(3).strip(),
                "domain_id": CATALOG_DOMAIN_IDS[prefix],
                "governance_lens": CATALOG_LENSES[suffix[0]],
                "severity": class_match.group(1),
                "catalog_baseline_outcome": class_match.group(2),
                "catalog_source_hash": _digest({"scenario_block": block.strip()}),
            }
        )
    if len(rows) != 100:
        raise ValueError(f"catalog must contain exactly 100 scenarios, got {len(rows)}")
    return rows


def build_manifest() -> dict[str, Any]:
    """Map every catalog archetype to one deterministic executable family."""
    domain_offsets: dict[str, int] = defaultdict(int)
    entries: list[dict[str, Any]] = []
    for scenario in _catalog_rows():
        domain_id = scenario["domain_id"]
        family_index = domain_offsets[domain_id]
        domain_offsets[domain_id] += 1
        governance_lens = scenario["governance_lens"]
        entries.append(
            {
                "scenario_id": scenario["scenario_id"],
                "title": scenario["title"],
                "domain_id": domain_id,
                "governance_lens": governance_lens,
                "causal_family": FAMILY_IDS[governance_lens],
                "severity": scenario["severity"],
                "catalog_baseline_outcome": scenario["catalog_baseline_outcome"],
                "catalog_source_hash": scenario["catalog_source_hash"],
                "executable_binding": {
                    "suite_id": "pressure_worlds",
                    "generator": (
                        "benchmarks.yuvin_consequencebench_100.adaptive_causal."
                        "world.pressure_episode:build_public_pressure_specs"
                    ),
                    "spec_schema_version": "ycb100.acc.pressure_world_spec.v1",
                    "domain_id": domain_id,
                    "family_index": family_index,
                    "variant_id": "base",
                    "seed_policy": "evaluator_supplied_nonnegative_integer",
                },
                "oracle_binding": {
                    "oracle": (
                        "benchmarks.yuvin_consequencebench_100.adaptive_causal."
                        "world.pressure_episode:PressureCausalEpisodeV1"
                    ),
                    "decision_space": [
                        "execute",
                        "deny",
                        "defer",
                        "escalate",
                        "compensate",
                    ],
                    "variant_outcome_rule": (
                        "derived_from_bound_world_state_not_catalog_baseline"
                    ),
                },
            }
        )
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": "ConsequenceBench",
        "release_tier": "DEVELOPMENT_PREVIEW_NOT_QUALIFIED",
        "catalog_entry_count": len(entries),
        "generator_suite": "pressure_worlds",
        "entries": entries,
    }
    body["manifest_hash"] = _digest(body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_manifest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
