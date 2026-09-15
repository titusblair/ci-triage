#!/usr/bin/env python3
"""ci-triage — work out why CI failed, and whether it has failed this way before.

    ci-triage run   psf/requests 34145371878     # one failed run
    ci-triage watch pallets/flask --runs 25      # cluster recent failures
    ci-triage run   psf/requests --explain       # add a Claude narrative
"""
from __future__ import annotations

import argparse
import json
import sys

from .github import GitHubError, failed_runs
from .triage import history, triage_run


def _p(s=""):
    print(s)


def cmd_run(args) -> int:
    run_id = args.run_id
    if not run_id:
        runs = failed_runs(args.repo, limit=1)
        if not runs:
            _p(f"  {args.repo} has no recent failed runs.")
            return 0
        run_id = runs[0]["id"]
        _p(f"  no run given, using the most recent failure: {run_id}")

    result = triage_run(args.repo, run_id)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    _p(f"\n  {result['repo']}  run {result['run_id']}")
    for job in result["failed_jobs"]:
        _p(f"\n  job: {job['name']}")
        if job.get("error"):
            _p(f"    log unavailable: {job['error'][:100]}")
            continue
        v = job["verdict"]
        _p(f"    failed step: {job.get('failed_step') or 'unknown'}")
        _p(f"    category:    {v['category']}  (confidence {v['confidence']})")
        _p(f"    owner:       {v['owner']}")
        _p(f"    signature:   {job['signature']}")
        if v.get("runner_up"):
            _p(f"    also matched: {v['runner_up']}")
        if v.get("note"):
            _p(f"    note:        {v['note']}")
        _p("    evidence:")
        for line in v["evidence"]:
            _p(f"      {line[:150]}")
        if args.explain:
            from .llm import explain
            _p("\n    ---")
            for line in explain(v, job["signature_lines"], repo=args.repo,
                                job=job["name"]).splitlines():
                _p(f"    {line}")
    _p()
    return 0


def cmd_watch(args) -> int:
    result = history(args.repo, runs=args.runs)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    _p(f"\n  {result['repo']}: {result['failed_jobs_scanned']} failed jobs -> "
       f"{result['distinct_failures']} distinct failures "
       f"({result['recurring_failures']} recurring)")
    if result["jobs_unreadable"]:
        _p(f"  {result['jobs_unreadable']} job logs could not be read (expired or private)")
    _p()
    for c in result["clusters"]:
        flag = "RECURRING" if c["status"] == "RECURRING" else "         "
        _p(f"  {flag}  x{c['occurrences']:<3} {c['category']:<15} {c['signature']}")
        _p(f"             jobs: {', '.join(c['jobs'])[:70]}")
        _p(f"             seen: {c['first_seen'][:10]} to {c['last_seen'][:10]}   owner: {c['owner']}")
        for line in c["evidence"][:1]:
            _p(f"             {line[:120]}")
        _p()

    recurring = [c for c in result["clusters"] if c["status"] == "RECURRING"]
    if recurring:
        top = recurring[0]
        _p(f"  Worst offender: {top['category']} x{top['occurrences']}, "
           f"owned by {top['owner']}")
        _p(f"  {top['example_run']}")
    _p()
    return 1 if args.fail_on_recurring and recurring else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="ci-triage", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="triage one failed run")
    r.add_argument("repo")
    r.add_argument("run_id", nargs="?")
    r.add_argument("--explain", action="store_true", help="add a Claude narrative")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_run)

    w = sub.add_parser("watch", help="cluster recent failures")
    w.add_argument("repo")
    w.add_argument("--runs", type=int, default=20)
    w.add_argument("--json", action="store_true")
    w.add_argument("--fail-on-recurring", action="store_true",
                   help="exit 1 if any failure has recurred (for use in CI)")
    w.set_defaults(func=cmd_watch)

    args = ap.parse_args()
    try:
        return args.func(args)
    except GitHubError as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
