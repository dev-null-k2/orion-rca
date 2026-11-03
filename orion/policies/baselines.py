"""Two common shortcuts, kept as baselines so the evals can show what Orion's method buys.

* LoudestError: blame the service with the most warnings and errors in the window, then lint its code.
* ErrorOwner: blame whichever service owns the error code in the ticket (no tracing, no walk-back).
"""
from __future__ import annotations

import re

from ..answer import Answer, RootCause
from ..harness import Harness


def _lint_repo(h: Harness, svc: str):
    repo = h.catalog.services.get(svc, {}).get("repo")
    if not repo:
        return None
    for path in h.call("code_files", repo=repo)["files"]:
        lint = h.call("code_lint", path=path)
        if lint["findings"]:
            f = lint["findings"][0]
            code = h.call("code_read", path=path, start=max(1, f["line"] - 3), end=f["line"] + 3)
            return path, f, [lint["evidence_id"], code["evidence_id"]]
    return None


def _answer(h: Harness, svc: str, why: str, ev: list[str]) -> Answer:
    hit = _lint_repo(h, svc)
    if hit is None:
        return Answer(ticket=h.estate.ticket.key, summary=f"Root cause: {svc} ({why}).",
                      root_cause=RootCause(statement=f"{svc} is the root cause: {why}.", service=svc, evidence=ev))
    path, f, evs = hit
    return Answer(ticket=h.estate.ticket.key, summary=f"Root cause: {svc} ({why}).",
                  root_cause=RootCause(statement=f"{svc}: {f['message']} ({why}).", service=svc, file=path,
                                       line=f["line"], evidence=ev + evs))


class LoudestError:
    name = "loudest-error"

    def run(self, h: Harness) -> Answer:
        h.call("ticket_read")
        counts = h.call("logs_count_by_service", level="WARN")
        errors = h.call("logs_count_by_service", level="ERROR")
        total: dict[str, int] = {}
        for c in (counts["counts"], errors["counts"]):
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
        svc = max(total, key=total.get)
        return _answer(h, svc, f"most warnings and errors in the window ({total[svc]})",
                       [counts["evidence_id"], errors["evidence_id"]])


class ErrorOwner:
    name = "error-owner"

    def run(self, h: Harness) -> Answer:
        t = h.call("ticket_read")
        codes = re.findall(r"\b[A-Z]{2,4}-\d{4}\b", t["content"])
        for code in codes:
            r = h.call("logs_count_by_service", query=code)
            if r["counts"]:
                svc = next(iter(r["counts"]))
                return _answer(h, svc, f"it logs {code} most", [t["evidence_id"], r["evidence_id"]])
        r = h.call("logs_count_by_service", level="ERROR")
        svc = next(iter(r["counts"]))
        return _answer(h, svc, "most errors (no error code in the ticket)", [t["evidence_id"], r["evidence_id"]])
