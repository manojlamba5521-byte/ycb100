from __future__ import annotations

import json
import sys

from benchmarks.yuvin_consequencebench_100.adaptive_causal.cli import main, run_public_controls
from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import AgentManifestV1, sha256_payload


def test_public_controls_are_pure_control_evidence_and_have_no_agent_view_leakage(tmp_path) -> None:
    report = run_public_controls()

    assert report["status"] == "CONTROL_ONLY"
    assert report["qualification_eligible"] is False
    assert report["family_count"] == 100
    assert report["failure_count"] == 0
    assert report["agent_view_leakage"] == []
    assert report["report_hash"].startswith("sha256:")

    output = tmp_path / "public-controls.json"
    assert main(["public-controls", "--out", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["report_hash"] == report["report_hash"]


def test_portable_pressure_controls_fail_closed_and_remain_non_qualifying(tmp_path) -> None:
    output = tmp_path / "pressure-controls.json"

    assert main(["pressure-controls", "--seed", "0", "--out", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "CONTROL_ONLY"
    assert report["qualification_eligible"] is False
    assert report["difficulty_claim_eligible"] is False
    assert report["world_count"] == 100
    assert report["unsafe_execute_opportunity_count"] == 70
    assert report["legitimate_effect_opportunity_count"] == 30
    assert report["admission_passed"] is True
    assert report["failure_count"] == 0


def test_portable_pressure_redteam_controls_do_not_serialize_the_key(tmp_path) -> None:
    key_value = "portable-development-evaluator-key"
    key_file = tmp_path / "evaluator.key"
    key_file.write_text(key_value, encoding="utf-8")
    output = tmp_path / "pressure-redteam-controls.json"

    assert (
        main(
            [
                "pressure-redteam-controls",
                "--seed",
                "0",
                "--evaluator-key-file",
                str(key_file),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    rendered = output.read_text(encoding="utf-8")
    report = json.loads(rendered)
    assert report["admission_passed"] is True
    assert report["qualification_eligible"] is False
    assert report["failure_count"] == 0
    assert key_value not in rendered


def test_portable_pressure_agent_command_runs_direct_track(tmp_path) -> None:
    digest = lambda label: sha256_payload({"label": label})
    manifest = AgentManifestV1(
        system_id="portable-pressure-agent",
        execution_tier="CONTAINMENT_ONLY",
        entrypoint="portable-jsonl-agent",
        source_tree_hash=digest("source"),
        model_id="portable-test-model",
        model_config_hash=digest("model"),
        prompt_root_hash=digest("prompt"),
        tool_policy_hash=digest("tools"),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8-sig")
    agent_path = tmp_path / "agent.py"
    agent_path.write_text(
        "import json,sys\n"
        "start=json.loads(sys.stdin.readline())\n"
        "record_id=start['episode']['records'][0]['record_id']\n"
        "print(json.dumps({'type':'decision.submit','sequence':1,'payload':"
        "{'decision':'execute','rationale_record_ids':[record_id],'confidence_basis_points':5000}}),flush=True)\n"
        "print(json.dumps({'type':'episode.finish','sequence':2,'payload':{}}),flush=True)\n",
        encoding="utf-8",
    )
    output = tmp_path / "agent-report.json"
    command_path = tmp_path / "agent-command.json"
    command_path.write_text(
        json.dumps([sys.executable, "-u", str(agent_path)]),
        encoding="utf-8-sig",
    )

    assert (
        main(
            [
                "pressure-agent",
                "--agent-manifest",
                str(manifest_path),
                "--agent-command-file",
                str(command_path),
                "--campaign-id",
                "portable-pressure-test",
                "--limit",
                "1",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["track"] == "direct_agent_capability"
    assert report["summary"]["attempt_count"] == 1
    assert report["summary"]["decision_exact_count"] == 1
    assert report["qualification_eligible"] is False


def test_portable_pressure_trial_binding_preserves_raw_receipt(tmp_path) -> None:
    source = {
        "schema_version": "ycb100.acc.pressure_ab_study.v2",
        "status": "DEVELOPMENT_ONLY",
        "qualification_eligible": False,
        "difficulty_claim_eligible": False,
        "campaign_id": "portable-bind-source",
        "agent_manifest": {"model_id": "portable-test-model"},
        "summary": {},
        "rows": [
            {
                "conditions": {
                    "spec": {
                        "schema_version": "ycb100.acc.pressure_world_spec.v1",
                        "domain_id": "banking",
                        "family_index": 0,
                        "seed": 3,
                        "variant_id": "base",
                    }
                }
            }
        ],
    }
    source["report_hash"] = sha256_payload(source)
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    output = tmp_path / "bound.json"

    assert (
        main(
            [
                "pressure-bind-trial",
                "--report",
                str(source_path),
                "--expected-source-hash",
                source["report_hash"],
                "--model-id",
                "portable-test-model",
                "--seed",
                "3",
                "--trial-index",
                "2",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    bound = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(source_path.read_text(encoding="utf-8")) == source
    assert bound["unbound_report_hash"] == source["report_hash"]
    assert bound["qualification_binding"]["trial_index"] == 2
