from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_development_leaderboard.py"
ASSET_SCRIPT = ROOT / "scripts" / "render_leaderboard_assets.py"


def _module(path: Path = SCRIPT):
    spec = importlib.util.spec_from_file_location(
        path.stem,
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_leaderboard_is_hash_bound_and_internally_consistent() -> None:
    module = _module()
    path = ROOT / "results" / "development_leaderboard.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == module.LEADERBOARD_SCHEMA
    assert payload["status"] == module.RELEASE_STATUS
    assert payload["qualification_eligible"] is False
    assert payload["ranking_status"] == "UNRANKED"
    assert payload["leaderboard_hash"] == module._canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "leaderboard_hash"
        }
    )
    assert len(payload["experiments"]) == 3
    assert len(payload["entries"]) == 6
    assert {
        (entry["system"], entry["configuration"])
        for entry in payload["entries"]
    } == {
        ("Gemini 3.6 Flash", "direct"),
        ("Gemini 3.6 Flash", "governed"),
        ("GPT-5.6 Sol (xhigh)", "direct"),
        ("GPT-5.6 Sol (xhigh)", "governed"),
        ("Gemma4 e4b", "direct"),
        ("Gemma4 e4b", "governed"),
    }
    assert all(
        entry["official_rank_eligible"] is False
        for entry in payload["entries"]
    )
    assert all(
        entry["unsafe_effect_count"] == 0
        for entry in payload["entries"]
        if entry["configuration"] == "governed"
    )
    assert all(
        entry["unsafe_effect_count"] > 0
        for entry in payload["entries"]
        if entry["configuration"] == "direct"
    )


def test_committed_leaderboard_markdown_is_generated_from_receipt() -> None:
    module = _module()
    payload = json.loads(
        (ROOT / "results" / "development_leaderboard.v1.json").read_text(
            encoding="utf-8"
        )
    )
    expected = module.render_markdown(payload)
    actual = (ROOT / "docs" / "LEADERBOARD.md").read_text(encoding="utf-8")

    assert actual == expected
    assert "SELF_REPORTED_LOCAL_DEVELOPMENT_EVIDENCE" not in actual
    assert "## Without Yuvin" in actual
    assert "## With Yuvin" in actual
    assert actual.count("| 1 | GPT-5.6 Sol (xhigh)") == 2


def test_readme_leaderboard_is_generated_from_receipt() -> None:
    module = _module()
    payload = json.loads(
        (ROOT / "results" / "development_leaderboard.v1.json").read_text(
            encoding="utf-8"
        )
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    expected = module.update_readme(
        readme,
        module.render_readme_section(payload),
    )

    assert readme == expected
    assert "SELF_REPORTED_LOCAL_DEVELOPMENT_EVIDENCE" not in readme
    assert "### Without Yuvin" in readme
    assert "### With Yuvin" in readme
    assert "| 2 | Gemini 3.6 Flash | 32/100 (32%) | 41/100 (41%) | 59/70 |" in readme
    assert "| 2 | Gemini 3.6 Flash | 58/100 (58%) | 100/100 (100%) | 0/70 |" in readme
    assert "development-leaderboard-ranked.svg" in readme


def test_committed_leaderboard_assets_are_generated_from_receipt() -> None:
    module = _module(ASSET_SCRIPT)
    payload = json.loads(
        (ROOT / "results" / "development_leaderboard.v1.json").read_text(
            encoding="utf-8"
        )
    )

    for name, expected in module.render_assets(payload).items():
        path = ROOT / "docs" / "assets" / name
        assert path.read_text(encoding="utf-8") == expected
        assert 'role="img"' in expected
        assert "<title" in expected
        assert "without yuvin" in expected.casefold()
        assert "with yuvin" in expected.casefold()

    ranking = module.render_assets(payload)[
        "development-leaderboard-ranked.svg"
    ]
    assert "Rankings by execution path" in ranking
    assert "0 / 3 PASSED SAFETY GATE" in ranking
    assert "3 / 3 PASSED SAFETY GATE" in ranking


def test_leaderboard_rejects_summary_forgery(tmp_path: Path) -> None:
    module = _module()
    payload = json.loads(
        (ROOT / "results" / "development_leaderboard.v1.json").read_text(
            encoding="utf-8"
        )
    )
    experiment = payload["experiments"][0]
    forged = {
        "schema_version": module.REPORT_SCHEMA,
        "status": module.RELEASE_STATUS,
        "qualification_eligible": False,
        "claim_boundary": module.CLAIM_BOUNDARY,
        "campaign_id": experiment["campaign_id"],
        "model": experiment["model"],
        "agent_manifest_hash": experiment["agent_manifest_hash"],
        "invocation_hash": experiment["invocation_hash"],
        "source_binding": experiment["source_binding"],
        "summary": {
            "world_count": 100,
            "proposal_attempt_count_per_arm": 200,
        },
        "rows": [],
    }
    forged["report_hash"] = module._canonical_hash(forged)
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly 100 rows"):
        module._validate_report(path)
