"""Turning a wall of log output into a stable, comparable failure signature.

This is the part that makes triage more than reading. Two runs that failed the
same way must produce the same signature even though their logs share almost no
literal text: different timestamps, temp paths, container IDs, durations, ports,
memory addresses, and run numbers.

With a stable signature you can answer the question that actually decides
priority, and that almost no CI tool answers: is this new, or has it been failing
quietly for a month?
"""

from __future__ import annotations

import hashlib
import re

# Order matters: the broadest patterns run last.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\[\d{1,2}m")

_SCRUB = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*"), ""),          # actions timestamps
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ][\d:,.]+"), "<TS>"),
    (re.compile(r"\b[0-9a-f]{40}\b"), "<SHA>"),
    (re.compile(r"\b[0-9a-f]{7,12}\b"), "<HASH>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<UUID>"),
    (re.compile(r"/tmp/[^\s:'\"]+"), "<TMP>"),
    (re.compile(r"(/home|/Users|/github/workspace|C:\\\\Users)[^\s:'\"]*"), "<PATH>"),
    (re.compile(r":\d+:\d+\b"), ":<LINE>:<COL>"),
    (re.compile(r":\d+\b"), ":<LINE>"),
    (re.compile(r"\b\d+(\.\d+)?\s*(ms|s|m|h|sec|secs|second|seconds|minute|minutes)\b"), "<DUR>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<ADDR>"),
    # Every remaining number goes. Test durations are the reason: a tox summary
    # like "FAIL code 4 (4.68=setup[0.61]+cmd[3.21,0.86] seconds)" differs on
    # every run, which gave four identical Flask failures four different
    # signatures and defeated clustering entirely.
    (re.compile(r"\b\d+\.\d+\b"), "<NUM>"),
    (re.compile(r"\b\d+\b"), "<N>"),
]

# Lines that are noise in every log, regardless of what failed.
_BORING = re.compile(
    r"^(##\[(group|endgroup|debug)\]|Requirement already satisfied|"
    r"Collecting |Downloading |Installing collected|Successfully installed|"
    r"Receiving objects|Resolving deltas|remote: |\s*\|\s*$)",
    re.I,
)

# Everything after these markers is teardown: git config, cache save, orphan
# process cleanup. It is the literal tail of every log and says nothing about
# why the job failed, so the search stops here.
_POST_JOB = re.compile(r"^(Post job cleanup|Cleaning up orphan processes|"
                       r"Post Run actions/|##\[group\]Post )", re.I)

# Generic enough to appear in every failure; useless as a fingerprint.
_GENERIC = re.compile(
    r"^(##\[error\])?\s*(Process completed with exit code|The process .* failed with|"
    r"evaluation failed|Error: Process completed)", re.I)

_ERROR_MARK = re.compile(
    r"(##\[error\]|^E\s|\bERROR\b|\bFAILED\b|\bFAIL:|Traceback \(most recent|"
    r"\bexception\b|\bfatal\b|\bassert(ion)?\s|\bpanic:|error\[E\d+\]|"
    r"npm ERR!|\bSyntaxError\b|\bTypeError\b|exit code [1-9])",
    re.I,
)


def strip_timestamps(log: str) -> str:
    return "\n".join(
        re.sub(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?", "", line) for line in log.splitlines()
    )


def normalize(line: str) -> str:
    out = _ANSI.sub("", line).strip()
    for rx, rep in _SCRUB:
        out = rx.sub(rep, out)
    return re.sub(r"\s+", " ", out).strip()


def error_lines(log: str, context: int = 3, limit: int = 40) -> list[str]:
    """The lines that look like the failure, plus a little context around them."""
    lines = [_ANSI.sub("", l) for l in strip_timestamps(log).splitlines()]
    for i, line in enumerate(lines):          # drop teardown before searching
        if _POST_JOB.match(line.strip()):
            lines = lines[:i]
            break
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if _ERROR_MARK.search(line) and not _BORING.match(line.strip()):
            for j in range(max(0, i - context), min(len(lines), i + context + 1)):
                keep.add(j)
    picked = [lines[i] for i in sorted(keep) if lines[i].strip()
              and not _BORING.match(lines[i].strip())]
    if not picked:
        # Nothing matched: the tail of a log is where a failure usually lands.
        picked = [l for l in lines[-limit:] if l.strip()]
    return picked[-limit:]


def signature(log: str, *, lines: int = 5) -> tuple[str, list[str]]:
    """A stable id for 'this kind of failure', plus the lines it came from.

    Generic trailers are excluded from the fingerprint. "Process completed with
    exit code 1" is true of every failure, so including it would collapse
    unrelated failures into one cluster.
    """
    picked = [normalize(l) for l in error_lines(log)]
    picked = [l for l in picked if len(l) > 8 and not _GENERIC.match(l)]
    core = picked[-lines:] if picked else ["<no error lines found>"]
    digest = hashlib.sha256("\n".join(core).encode()).hexdigest()[:12]
    return digest, core
