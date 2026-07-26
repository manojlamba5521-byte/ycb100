from __future__ import annotations

from collections import Counter

from benchmarks.yuvin_consequencebench_100.adaptive_causal.lifecycle.reference import (
    run_reference_campaign,
)


def test_reference_campaign_reaches_all_100_base_worlds_without_hard_failure() -> None:
    report = run_reference_campaign(seed=23, variant_id="base").to_dict()

    assert report["world_count"] == 100
    assert report["hard_safe_count"] == 100
    assert report["semantic_match_count"] == 100
    assert report["failure_count"] == 0
    assert Counter(row["required_disposition"] for row in report["rows"]) == {
        "execute": 30,
        "deny": 25,
        "recover": 20,
        "obligation_open": 15,
        "compensate": 10,
    }
