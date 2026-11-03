"""Render an answer and its evidence as a Markdown RCA."""
from __future__ import annotations

from .runner import RunResult


def to_markdown(r: RunResult) -> str:
    a, h = r.answer, r.harness
    t = h.estate.ticket
    stars = "●" * a.confidence + "○" * (5 - a.confidence)
    out = [f"# {t.key}: {t.summary}", "",
           (f"**Confidence** {stars} {a.confidence}/5 · **Verification** {a.verdict} · "
           f"**Critic** {a.critic.get('verdict', 'n/a')} · **Flow** {a.flow or 'n/a'} · "
           f"**Failure shows in** {a.failure_point or 'n/a'}"), "",
           "## Summary", "", a.summary, "",
           "## Root cause", "", f"{a.root_cause.statement} {_refs(a.root_cause.evidence)}", ""]
    if a.root_cause.file:
        out += [f"*{a.root_cause.status}* · `{a.root_cause.file}:{a.root_cause.line}`", ""]
    out += ["## How it fails", ""]
    out += [f"{i}. {c.statement} {_refs(c.evidence)}" for i, c in enumerate(a.causal_chain, 1)]
    if a.ruled_out:
        out += ["", "## Ruled out", ""] + [f"- {c.statement} {_refs(c.evidence)}" for c in a.ruled_out]
    if a.fix:
        out += ["", "## Fix", "", f"`{a.fix.file}`: {a.fix.change} {_refs(a.fix.evidence)}"]
    if a.critic.get("objections") or a.critic.get("verification_problems"):
        out += ["", "## Critic and verification", ""]
        out += [f"- {o}" for o in a.critic.get("objections", []) + a.critic.get("verification_problems", [])]
    if a.open_questions:
        out += ["", "## Open questions", ""] + [f"- {q}" for q in a.open_questions]
    out += ["", "## Evidence", "", "| Id | System | Tool | What it showed |", "|---|---|---|---|"]
    for e in h.ledger.records.values():
        out.append(f"| {e.id} | {e.system} | `{e.tool}` | {e.summary.replace('|', '/')[:110]} |")
    out += ["", f"*{r.tool_calls} tool calls · {len(h.ledger.records)} signed evidence records · {r.seconds:.2f}s*"]
    return "\n".join(out) + "\n"


def _refs(ids: list[str]) -> str:
    return "[" + ", ".join(ids) + "]" if ids else ""
