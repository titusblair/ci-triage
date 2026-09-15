#!/usr/bin/env python3
"""Unit tests that need no network. Run offline, run fast, run in CI.

The live GitHub path is exercised by evals/run_eval.py against saved fixtures;
these cover the invariants that must hold regardless of what a log contains.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci_triage.classify import classify           # noqa: E402
from ci_triage.signature import (                 # noqa: E402
    error_lines, normalize, signature, strip_timestamps,
)

FIXTURES = Path(__file__).resolve().parent.parent / "evals" / "fixtures"
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed, failed = passed + bool(ok), failed + (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


LOG = """2026-09-07T16:54:48.5293587Z ##[group]Run tests
2026-09-07T16:54:49.1000000Z Requirement already satisfied: pytest
2026-09-07T16:54:52.0000000Z E   AssertionError: assert 1 == 2
2026-09-07T16:54:52.1000000Z = 1 failed, 200 passed in 12.34s =
2026-09-07T16:54:52.2000000Z ##[error]Process completed with exit code 1.
2026-09-07T16:54:53.0000000Z Post job cleanup.
2026-09-07T16:54:53.1000000Z git version 2.55.0
"""

check("timestamps are stripped", "2026-09-07T16" not in strip_timestamps(LOG))

lines = error_lines(LOG)
check("teardown after 'Post job cleanup' is dropped",
      not any("git version" in l for l in lines))
check("install noise is dropped",
      not any("Requirement already satisfied" in l for l in lines))
check("the actual error survives", any("AssertionError" in l for l in lines))

# The invariant the whole tool rests on.
a = LOG.replace("12.34s", "44.02s").replace("16:54:52", "18:10:03")
check("same failure, different durations -> same signature",
      signature(LOG)[0] == signature(a)[0],
      f"{signature(LOG)[0]} vs {signature(a)[0]}")

b = LOG.replace("AssertionError: assert 1 == 2", "ModuleNotFoundError: no module named x")
check("different failure -> different signature",
      signature(LOG)[0] != signature(b)[0])

check("signature is deterministic", signature(LOG)[0] == signature(LOG)[0])

check("ANSI colour codes do not change the signature",
      signature(LOG)[0] == signature(LOG.replace("E   Assertion", "E   \x1b[31mAssertion\x1b[0m"))[0])

check("normalize scrubs paths and numbers",
      "<PATH>" in normalize("/home/runner/work/x/y failed") and
      "<N>" in normalize("exit 137"))

v = classify(error_lines(LOG))
check("a failing assertion classifies as test_failure",
      v["category"] == "test_failure", v["category"])
check("verdict carries evidence", bool(v["evidence"]))

check("a log with no diagnostic says so, rather than guessing",
      classify(["##[error]Process completed with exit code 1."])["category"]
      in ("no_diagnostic", "unknown"))

# Every fixture must stay parseable; a crash here is a regression.
crashed = []
for f in sorted(FIXTURES.glob("*.log")):
    try:
        classify(f.read_text().splitlines())
        signature(f.read_text())
    except Exception as exc:                       # noqa: BLE001
        crashed.append(f"{f.stem}: {exc}")
check(f"all {len(list(FIXTURES.glob('*.log')))} real fixtures parse without crashing",
      not crashed, "; ".join(crashed[:2]))

print(f"\n  {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
