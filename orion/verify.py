"""Answer verification, the critic, and confidence.

Verification is code the model cannot argue with:
  * every claim cites at least one evidence id, and every id exists in the ledger with a valid signature;
  * every value quoted in backticks in a claim appears in one of its cited records;
  * the root cause cites code evidence *and* runtime evidence (logs or database).

The critic then tries to refute the root cause with checks that encode common RCA failure modes
(stopping at the system that only reports the error, fixating on the loudest signal, no baseline).
"""
from __future__ import annotations

import re

from .answer import Answer
from .harness import Harness

RUNTIME = {"logs", "sql"}


def verify(answer: Answer, h: Harness) -> list[str]:
    problems: list[str] = []
    for n, claim in enumerate(answer.claims()):
        label = "root cause" if n == 0 else f"claim {n}"
        if claim.status == "not_established":
            continue
        if not claim.evidence:
            problems.append(f"{label}: no evidence cited")
            continue
        records = [h.ledger.get(e) for e in claim.evidence]
        if any(r is None for r in records):
            problems.append(f"{label}: cites unknown or tampered evidence {claim.evidence}")
            continue
        corpus = "\n".join(r.content + "\n" + r.summary for r in records)
        for quoted in re.findall(r"`([^`]+)`", claim.statement):
            if quoted not in corpus:
                problems.append(f"{label}: `{quoted}` is not in the cited evidence")
    rc = answer.root_cause
    if rc.status != "not_established":
        systems = {h.ledger.get(e).system for e in rc.evidence if h.ledger.get(e)}
        if "code" not in systems:
            problems.append("root cause: no code evidence")
        if not systems & RUNTIME:
            problems.append("root cause: no runtime evidence (logs or database)")
    return problems


def critic(answer: Answer, h: Harness) -> dict:
    objections: list[str] = []
    rc = answer.root_cause
    if rc.status == "not_established":
        return {"verdict": "uncertain", "objections": ["no root cause established"]}
    svc = h.catalog.services.get(rc.service or "", {})
    if svc and not svc.get("repo"):
        objections.append(f"{rc.service} is a system of record that rejects bad input; look upstream for who built it")
    tools_used = [e.data["tool"] for e in h.events if e.kind == "tool_start"]
    if "logs_trace" not in tools_used:
        objections.append("no single failing request was traced end to end; the cause may be a correlation only")
    if "logs_compare_windows" not in tools_used:
        objections.append("no baseline: is this error new, or always there?")
    loud = [e.data for e in h.events if e.kind == "tool_end" and e.data["tool"] == "logs_count_by_service"]
    if loud and rc.service and rc.service in loud[-1]["summary"] and "trace" not in rc.statement:
        objections.append("root cause matches the loudest service rather than the failing request")
    if not answer.fix:
        objections.append("no fix proposed")
    verdict = "agree" if not objections else ("disagree" if len(objections) >= 2 else "uncertain")
    return {"verdict": verdict, "objections": objections}


def confidence(answer: Answer, problems: list[str], review: dict, h: Harness) -> int:
    if answer.root_cause.status == "not_established":
        return 1
    score = 5
    score -= min(2, len(problems))
    score -= {"agree": 0, "uncertain": 1, "disagree": 2}[review["verdict"]]
    trend = [e.data for e in h.events if e.kind == "tool_end" and e.data["tool"] == "logs_compare_windows"]
    if trend and "steady" in trend[-1]["summary"]:
        score -= 1  # a routine error explains less
    return max(1, min(5, score))


def finalize(answer: Answer, h: Harness) -> Answer:
    problems = verify(answer, h)
    review = critic(answer, h)
    if not problems and review["verdict"] == "agree" and answer.root_cause.status == "likely":
        answer.root_cause.status = "observed"
    answer.verdict = "verified" if not problems else "sent_back"
    answer.critic = review | {"verification_problems": problems}
    answer.confidence = confidence(answer, problems, review, h)
    h.emit("verified", problems=problems, verdict=review["verdict"], confidence=answer.confidence)
    return answer
