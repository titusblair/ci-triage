"""Reading failed GitHub Actions runs. Public repos need no special access.

Uses the `gh` CLI when it is available, because it already holds a token and
handles rate limits; falls back to a bare token from the environment.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import os
import urllib.request

API = "https://api.github.com"


class GitHubError(RuntimeError):
    """Raised with text a caller can act on."""


def _via_gh(path: str, raw: bool = False) -> str:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if out.returncode != 0:
        err = (out.stderr or "").strip()
        if "rate limit" in err.lower():
            raise GitHubError("GitHub rate limit reached. Wait, or set GITHUB_TOKEN.")
        raise GitHubError(f"gh api {path} failed: {err[:300]}")
    return out.stdout


def _via_urllib(path: str) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    req = urllib.request.Request(f"{API}/{path.lstrip('/')}")
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:
        raise GitHubError(
            f"Could not reach GitHub for {path}: {exc}. Job logs require a token: "
            "install the gh CLI and run `gh auth login`, or set GITHUB_TOKEN."
        ) from exc


def api(path: str, raw: bool = False):
    text = _via_gh(path) if shutil.which("gh") else _via_urllib(path)
    return text if raw else json.loads(text)


def failed_runs(repo: str, limit: int = 10) -> list[dict]:
    data = api(f"repos/{repo}/actions/runs?status=failure&per_page={limit}")
    return [
        {
            "id": r["id"],
            "name": r.get("name"),
            "branch": r.get("head_branch"),
            "created": (r.get("created_at") or "")[:19],
            "url": r.get("html_url"),
            "commit": (r.get("head_sha") or "")[:8],
        }
        for r in data.get("workflow_runs", [])
    ]


def failed_jobs(repo: str, run_id: int | str) -> list[dict]:
    data = api(f"repos/{repo}/actions/runs/{run_id}/jobs")
    jobs = [j for j in data.get("jobs", []) if j.get("conclusion") == "failure"]
    if not jobs:
        raise GitHubError(
            f"Run {run_id} in {repo} has no failed jobs. It may have been cancelled "
            "or timed out at the workflow level rather than failing a job."
        )
    out = []
    for j in jobs:
        failed_step = next(
            (s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"),
            None,
        )
        out.append({
            "id": j["id"],
            "name": j.get("name"),
            "failed_step": failed_step,
            "url": j.get("html_url"),
        })
    return out


def job_log(repo: str, job_id: int | str) -> str:
    return api(f"repos/{repo}/actions/jobs/{job_id}/logs", raw=True)
