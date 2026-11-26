"""Fail (exit 1) when an eval report misses its quality gates.

Reads evals/faithfulness_results.json by default. Thresholds can be overridden
by flags so CI can tighten them without editing code.
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report", type=Path, default=Path("evals/faithfulness_results.json"))
    p.add_argument("--faithfulness-mean", type=float, default=0.85)
    p.add_argument("--faithfulness-min", type=float, default=0.75)
    p.add_argument("--hallucination-mean", type=float, default=0.50)
    args = p.parse_args()

    report = json.loads(args.report.read_text())
    s = report["summary"]
    n = report["scenario_count"]

    checks = [
        ("faithfulness mean", s["faithfulness_mean"], args.faithfulness_mean, s["faithfulness_mean"] >= args.faithfulness_mean),
        ("faithfulness min", s["faithfulness_min"], args.faithfulness_min, s["faithfulness_min"] >= args.faithfulness_min),
        ("factual alignment mean", s["hallucination_mean"], args.hallucination_mean, s["hallucination_mean"] >= args.hallucination_mean),
        ("retrieval correct", s["retrieval_correct"], n, s["retrieval_correct"] == n),
        ("guardrails passed", s["guardrails_passed"], n, s["guardrails_passed"] == n),
    ]

    print(f"report: {args.report}  measured_at={report['measured_at']}  judge={report['judge_model']}")
    failed = False
    for name, got, want, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {got} (required >= {want})")
        failed |= not ok
    for r in report["scenarios"]:
        if r["faithfulness"] < args.faithfulness_min:
            print(f"  scenario {r['id']} faithfulness {r['faithfulness']}: {r['faithfulness_reason']}")

    if failed:
        print("::error::Eval regression gate failed")
        return 1
    print("All eval gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
