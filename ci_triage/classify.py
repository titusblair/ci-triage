"""What kind of failure is this?

Category first, because the category decides who owns it. A dependency
resolution failure is not the same work as a failing assertion, and routing it
to the wrong person is most of what makes triage slow.

Rules, not a model. They are auditable, free, instant, and — measured on the
golden set in evals/ — good enough that an LLM's job is explaining the failure
rather than identifying it.
"""

from __future__ import annotations

import re

# (category, who it belongs to, ordered patterns). First match wins, so the
# specific categories are listed before the general ones.
RULES: list[tuple[str, str, list[str]]] = [
    ("oom", "infrastructure", [
        r"\bout of memory\b", r"\bOOMKilled\b", r"Killed\s*$", r"\bENOMEM\b",
        r"JavaScript heap out of memory", r"exit code 137",
    ]),
    ("timeout", "infrastructure", [
        r"The job running on runner .* has exceeded the maximum execution time",
        r"exceeded the maximum execution time",
        r"##\[error\]The operation was canceled",
        r"\bETIMEDOUT\b", r"Cancelling since a higher priority",
        r"\btimed out after\b", r"step timed out",
    ]),
    ("network", "infrastructure", [
        r"Error during upload", r"\bupload failed\b", r"Retry with the --verbose",
        r"failed to upload", r"\bECONNREFUSED\b",
        r"\bECONNRESET\b", r"\bENOTFOUND\b", r"\bEAI_AGAIN\b", r"Connection refused",
        r"Temporary failure in name resolution", r"502 Bad Gateway",
        r"503 Service Unavailable", r"Could not resolve host", r"TLS handshake",
    ]),
    ("config", "whoever owns the workflow", [
        r"length must be less than or equal to", r"Invalid workflow file",
        r"Unexpected value '", r"\bis not a valid\b.*\binput\b",
        r"##\[error\]\s*\"[\w.-]+\" (length|input|value)",
        r"required and not supplied", r"workflow is not valid",
    ]),
    ("permissions", "repo admin", [
        r"\bPermission denied\b", r"\b403 Forbidden\b", r"Resource not accessible by integration",
        r"authentication failed", r"\bEACCES\b", r"invalid token", r"bad credentials",
    ]),
    ("dependency", "whoever bumped the lockfile", [
        r"\bdependabot\b", r"^updater \|", r"<job_\d+> Job definition",
        r"ResolutionImpossible", r"No matching distribution found",
        r"Could not find a version that satisfies",
        r"npm ERR! (code )?ERESOLVE", r"peer dep(endency)? ", r"ModuleNotFoundError",
        r"\bImportError\b", r"cannot find module", r"unable to resolve dependency tree",
        r"error: failed to select a version",
    ]),
    ("typecheck", "the author", [
        r"^\S+\.(py|pyi|ts|tsx|go|rb):\d+: error:",     # mypy / tsc style
        r"\berror TS\d+", r"^mypy\b", r"\bmypy\b.*\berror\b",
        r"Incompatible types", r"Returning Any from function",
        r"has incompatible type", r"Argument \d+ .* has incompatible type",
        r"\bFound \d+ errors? in \d+ files?\b",
    ]),
    ("lint", "the author", [
        r"^@@ -\d+,?\d* \+\d+,?\d* @@",              # a unified diff hunk header
        r"files were modified by this hook", r"^- hook id:",
        r"\breformatted\b", r"^\+\+\+ b/",
        r"\bruff\b.*\berror\b", r"\bflake8\b", r"\bE\d{3}\b .*\n?", r"\beslint\b",
        r"\bblack\b.*would reformat", r"would reformat", r"\bmypy\b.*error:",
        r"Process completed with exit code 1.*lint", r"\bprettier\b",
    ]),
    ("compile", "the author", [
        r"^#\d+ [\d.]+ .*\berror\b",                  # buildkit step output
        r"update-alternatives: error", r"failed to solve",
        r"returned a non-zero code", r"\bdocker build\b.*\bfailed\b",
        r"error\[E\d+\]", r"\bSyntaxError\b", r"\bcompilation (failed|error)",
        r"error TS\d+", r"cannot borrow", r"undefined reference to",
        r"\bsegmentation fault\b",
    ]),
    ("test_failure", "the author", [
        r"\b\d+ failed\b", r"\bFAILED .*::", r"AssertionError", r"\bFAIL\b .*\btest",
        r"Tests? failed", r"\bassert .* ==", r"expected .* (but )?(got|received)",
        r"\d+ (test|example)s?, \d+ failures?",
        r"^\s*E\s{2,}\w*(Error|Warning|Exception)\b",   # pytest error line
        r"\bFAIL code \d+", r"\berrors? during collection\b",
        r"\b\d+ error(s)? in [\d.]+s\b",
    ]),
    ("flaky_candidate", "nobody yet", [
        r"\bretr(y|ied|ying)\b", r"\bintermittent\b", r"\bflaky\b",
    ]),
]

# The part of a log line most worth showing a human, per category.
_GENERIC_LINE = re.compile(
    r"^(```|#{1,3}\s|\[m|##\[error\]\s*Process completed|Process completed)", re.I)

_EVIDENCE = re.compile(r"(##\[error\]|\bERROR\b|\bFAILED\b|AssertionError|error\[E|"
                       r"npm ERR!|ModuleNotFoundError|would reformat)", re.I)


def classify(lines: list[str]) -> dict:
    """Return the best category, who owns it, and the lines that decided it."""
    blob = "\n".join(lines)
    scores: list[tuple[str, str, int, list[str]]] = []

    for category, owner, patterns in RULES:
        hits, matched = 0, []
        for pat in patterns:
            found = re.findall(pat, blob, re.I | re.M)
            if found:
                hits += len(found)
                for line in lines:
                    if re.search(pat, line, re.I) and line not in matched:
                        matched.append(line)
        if hits:
            scores.append((category, owner, hits, matched[:3]))

    if not scores:
        # "The job failed and printed nothing useful" is a real, actionable
        # finding: the fix is to make the workflow say why it failed.
        informative = [l for l in lines
                       if len(l.strip()) > 12 and not _GENERIC_LINE.match(l.strip())]
        if not informative:
            return {
                "category": "no_diagnostic",
                "owner": "whoever owns the workflow",
                "confidence": 0.8,
                "evidence": lines[-2:],
                "runner_up": None,
                "note": "The job failed without emitting a diagnostic. Nothing here "
                        "identifies a cause; the workflow itself needs to log more.",
            }
        return {
            "category": "unknown",
            "owner": "needs a human",
            "confidence": 0.0,
            "evidence": [l for l in lines if _EVIDENCE.search(l)][:3] or lines[-3:],
            "runner_up": None,
        }

    # Rule order is priority: infrastructure causes masquerade as test failures,
    # so an OOM that also printed "1 failed" is an OOM.
    order = {c: i for i, (c, _, _) in enumerate(RULES)}
    scores.sort(key=lambda s: (order[s[0]], -s[2]))
    category, owner, hits, evidence = scores[0]

    total = sum(s[2] for s in scores)
    return {
        "category": category,
        "owner": owner,
        "confidence": round(min(0.95, 0.55 + 0.1 * hits) if len(scores) == 1
                            else min(0.9, hits / total + 0.25), 2),
        "evidence": evidence,
        "runner_up": scores[1][0] if len(scores) > 1 else None,
    }
