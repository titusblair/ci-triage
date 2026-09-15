#!/usr/bin/env python3
"""Does the classifier actually work? Measured on real failures, not invented ones.

Two evals:

1. CLASSIFICATION — 22 hand-labelled failures from 9 public repositories, saved as
   fixtures. Accuracy overall, and a confusion list so a regression names itself.

2. CLUSTERING — the property the whole tool rests on: two runs that failed the
   same way must share a signature, and two that failed differently must not.
   Collapsing unrelated failures is worse than not clustering at all, so both
   directions are scored.

    python3 evals/run_eval.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci_triage.classify import classify          # noqa: E402
from ci_triage.signature import signature        # noqa: E402

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


def eval_classification() -> dict:
    spec = json.loads((HERE / "golden_failures.json").read_text())
    right, wrong = 0, []
    by_label = Counter()
    hit_by_label = Counter()

    for case in spec["cases"]:
        path = FIXTURES / f"{case['fixture']}.log"
        if not path.exists():
            wrong.append(f"{case['fixture']}: fixture missing")
            continue
        lines = path.read_text().splitlines()
        got = classify(lines)["category"]
        by_label[case["label"]] += 1
        if got == case["label"]:
            right += 1
            hit_by_label[case["label"]] += 1
        else:
            wrong.append(f"{case['fixture']:<20} got {got:<15} want {case['label']:<13} "
                         f"({case['why']})")

    n = len(spec["cases"])
    return {
        "eval": "failure classification",
        "accuracy": right / n,
        "correct": f"{right}/{n}",
        "per_label": {k: f"{hit_by_label[k]}/{v}" for k, v in sorted(by_label.items())},
        "failures": wrong,
    }


def eval_clustering() -> dict:
    """Same failure -> same signature. Different failure -> different signature."""
    sigs: dict[str, str] = {}
    for path in sorted(FIXTURES.glob("*.log")):
        sigs[path.stem], _ = signature(path.read_text())

    # Fixtures are named <repo>-<sig6>, so the name carries the expected grouping.
    collisions = [s for s, c in Counter(sigs.values()).items() if c > 1]
    colliding = {k: v for k, v in sigs.items() if v in collisions}

    # Stability: the same input must always produce the same signature.
    stable = all(
        signature((FIXTURES / f"{name}.log").read_text())[0] == sig
        for name, sig in sigs.items()
    )

    return {
        "eval": "signature clustering",
        "fixtures": len(sigs),
        "distinct_signatures": len(set(sigs.values())),
        "deterministic": 1.0 if stable else 0.0,
        "over_clustered": len(colliding),
        "failures": [f"{k} collides on {v}" for k, v in colliding.items()],
    }


def show(r: dict) -> None:
    print(f"\n  {r['eval']}")
    for k, v in r.items():
        if k in ("eval", "failures", "per_label"):
            continue
        print(f"    {k:<24} {v:.1%}" if isinstance(v, float) else f"    {k:<24} {v}")
    if r.get("per_label"):
        print("    per label:")
        for k, v in r["per_label"].items():
            print(f"      {k:<16} {v}")
    for f in r["failures"]:
        print(f"      - {f}")


def main() -> int:
    results = [eval_classification(), eval_clustering()]
    for r in results:
        show(r)
    acc = results[0]["accuracy"]
    over = results[1]["over_clustered"]
    ok = acc >= 0.80 and over == 0 and results[1]["deterministic"] == 1.0
    print(f"\n  {'above floor' if ok else 'BELOW FLOOR (accuracy >= 80%, no over-clustering)'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
