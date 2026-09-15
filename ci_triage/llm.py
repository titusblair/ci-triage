"""Optional: have Claude write the narrative once the rules have done the work.

Deliberately the thin layer. Identifying the category, isolating the evidence
and clustering the history are deterministic, auditable and free. The model is
asked only to explain and suggest, on evidence already selected — which is the
part it is actually good at, and the part that cannot be unit tested.

Requires `pip install anthropic` and credentials. Everything else works without.
"""

from __future__ import annotations

MODEL = "claude-opus-5"

SYSTEM = """You explain CI failures to the engineer who has to fix one.

You are given a category already determined by rules, the evidence lines, and how
often this exact failure has occurred. Trust the category. Your job is the why
and the what-next.

Answer in three short parts, no preamble:
WHAT BROKE: one sentence, concrete.
WHY: one or two sentences. If the evidence does not support a cause, say that
instead of inventing one.
NEXT: the single most useful action.

Never invent a file, line number, or error string that is not in the evidence."""


def explain(verdict: dict, evidence: list[str], *, occurrences: int = 1,
            repo: str = "", job: str = "") -> str:
    try:
        import anthropic
    except ImportError:
        return "(narrative unavailable: pip install anthropic)"

    history = (f"This exact failure has occurred {occurrences} times recently, so it "
               "is not a one-off." if occurrences > 1 else
               "This signature appears once in the recent history.")

    prompt = (
        f"Repository: {repo}\nJob: {job}\n"
        f"Category determined by rules: {verdict['category']} "
        f"(confidence {verdict['confidence']}, owner: {verdict['owner']})\n"
        f"{history}\n\nEvidence lines:\n" + "\n".join(evidence[:25])
    )

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        return f"(narrative unavailable: {exc})"

    return "\n".join(b.text for b in resp.content if b.type == "text").strip()
