"""Triaging one failure, and — the part that decides priority — many of them.

Reading a single failed run tells you what broke. It does not tell you whether
this is new, whether it is worth waking someone for, or whether it has been
failing quietly for a month while everyone re-ran it. That question is answered
by clustering failures on their signature, which is what `history` does.
"""

from __future__ import annotations

from collections import defaultdict

from .classify import classify
from .github import failed_jobs, failed_runs, job_log, GitHubError
from .signature import error_lines, signature


def triage_run(repo: str, run_id: int | str) -> dict:
    """One failed run: what broke, who owns it, and the evidence."""
    jobs = failed_jobs(repo, run_id)
    results = []
    for job in jobs:
        try:
            log = job_log(repo, job["id"])
        except GitHubError as exc:
            results.append({**job, "error": str(exc)})
            continue
        sig, core = signature(log)
        lines = error_lines(log)
        results.append({
            **job,
            "signature": sig,
            "verdict": classify(lines),
            "signature_lines": core,
        })
    return {"repo": repo, "run_id": str(run_id), "failed_jobs": results}


def history(repo: str, *, runs: int = 25, quiet: bool = True) -> dict:
    """Cluster recent failures so recurring ones stop hiding as one-offs."""
    clusters: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "runs": [], "jobs": set(), "first": None, "last": None}
    )
    scanned = skipped = 0

    for run in failed_runs(repo, limit=runs):
        try:
            jobs = failed_jobs(repo, run["id"])
        except GitHubError:
            skipped += 1
            continue
        for job in jobs:
            try:
                log = job_log(repo, job["id"])
            except GitHubError:
                skipped += 1
                continue
            scanned += 1
            sig, core = signature(log)
            c = clusters[sig]
            c["count"] += 1
            c["runs"].append(run["url"])
            c["jobs"].add(job["name"])
            c["last"] = c["last"] or run["created"]
            c["first"] = run["created"]
            c.setdefault("verdict", classify(error_lines(log)))
            c.setdefault("lines", core)
            if not quiet:
                print(f"  {run['created'][:10]}  {sig}  {job['name'][:30]}")

    ranked = sorted(clusters.items(), key=lambda kv: -kv[1]["count"])
    out = []
    for sig, c in ranked:
        out.append({
            "signature": sig,
            "occurrences": c["count"],
            "category": c["verdict"]["category"],
            "owner": c["verdict"]["owner"],
            "jobs": sorted(c["jobs"]),
            "first_seen": c["first"],
            "last_seen": c["last"],
            "evidence": c["verdict"]["evidence"][:2],
            "example_run": c["runs"][0],
            "status": "RECURRING" if c["count"] > 1 else "one-off",
        })

    recurring = [c for c in out if c["occurrences"] > 1]
    return {
        "repo": repo,
        "failed_jobs_scanned": scanned,
        "jobs_unreadable": skipped,
        "distinct_failures": len(out),
        "recurring_failures": len(recurring),
        "noise_ratio": round(1 - len(out) / scanned, 2) if scanned else 0.0,
        "clusters": out,
    }
