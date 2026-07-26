"""Produce an advisory, hash-bound LLM review of one public ConsequenceBench trace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.yuvin_consequencebench_100.adaptive_causal.review_judge import ReviewSubjectV1, run_advisory_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an advisory OpenAI, Gemini, or Anthropic trace review")
    parser.add_argument("--input", required=True, type=Path, help="public review subject JSON")
    parser.add_argument("--output", required=True, type=Path, help="advisory review JSON")
    parser.add_argument("--provider", required=True, choices=("openai", "gemini", "anthropic"))
    parser.add_argument("--model", required=True)
    arguments = parser.parse_args(argv)
    payload = json.loads(arguments.input.read_text(encoding="utf-8"))
    subject = ReviewSubjectV1.from_mapping(payload)
    result = run_advisory_review(subject=subject, provider=arguments.provider, model=arguments.model)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result.status, "subject_hash": result.subject_hash, "response_hash": result.response_hash}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
