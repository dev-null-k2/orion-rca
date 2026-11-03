"""The reference investigator: a deterministic policy that follows Orion's method with the same tools an LLM
gets. It is the offline baseline the evals run in CI, and the yardstick an LLM policy has to beat.

Method:
  1. Read the ticket; pull out identifiers, error codes and stack frames.
  2. Database check: read the customer's records before any log or code search.
  3. Rank business flows (past incidents first, then the KB) and confirm the flow with the engineer.
  4. Find the failure point and walk the flow's services backwards from it, nearest first.
  5. Anchor on one failing request that matches the ticket, then trace its request id across services.
  6. The earliest anomaly in that trace is where the problem starts; read and lint that service's code.
  7. Check recent changes and compare the error rate with the day before.
  8. Write claims that each cite signed evidence; the harness verifies them and a critic reviews them.
"""
from __future__ import annotations

import re

from ..answer import Answer, Claim, Fix, RootCause
from ..harness import Harness, ToolRefused

ID_PATTERNS = {
    "account": r"\bACC-\d{4}\b",
    "order": r"\bORD-\d{5}\b",
    "device": r"\bD-\d{5}\b",
    "msisdn": r"\b555\d{7}\b",
}
FRAME = re.compile(r"at ([\w.]+)\.(\w+)\((\w+)\.(?:java|py|ts):(\d+)\)")
EXCEPTION = re.compile(r"\b(\w+(?:Exception|Error))\b")

# Which lint rules can explain which runtime symptom.
SYMPTOM_RULES = [
    (re.compile(r"=null\b"), ["partial-fallback", "null-on-failure"]),
    (re.compile(r"NullPointerException|UNIQUE_CONSTRAINT"), ["unchecked-deref", "null-on-failure"]),
    (re.compile(r"retry|attempt=2", re.IGNORECASE), ["non-idempotent-retry"]),
    (re.compile(r"timeout", re.IGNORECASE), ["timeout-budget", "non-idempotent-retry"]),
    (re.compile(r"ends_at|expired|rejected now=", re.IGNORECASE), ["naive-timezone"]),
    (re.compile(r"upstream|host not found", re.IGNORECASE), ["unknown-upstream"]),
    (re.compile(r"failed account=|failed\b", re.IGNORECASE), ["swallowed-exception", "validation-limit"]),
]

FIXES = {
    "partial-fallback": "Resolve the value for every item category (look it up from the device or line registry) and "
                        "reject the order before calling downstream if it is still empty.",
    "null-on-failure": "Return or raise the real error status instead of null, and log the code and message.",
    "unchecked-deref": "Null-check the result and fail with a diagnosable exception; make the insert idempotent on retry.",
    "non-idempotent-retry": "Generate the idempotency key once per order, before the retry loop, and reuse it on every attempt.",
    "timeout-budget": "Raise the timeout above the dependency's documented p99 (with a retry that reuses the same message id).",
    "naive-timezone": "Store promotion windows as timezone-aware datetimes (America/New_York) and compare in UTC.",
    "unknown-upstream": "Point the route back at an existing upstream and add a CI check that every upstream resolves.",
    "swallowed-exception": "Log the caught exception and map validation failures to their own error codes.",
    "validation-limit": "Return a field-level validation error for long inputs instead of the generic failure code.",
}


def is_anomaly(rec: dict) -> bool:
    return rec["level"] in ("WARN", "ERROR") or bool(re.search(r"=null\b", rec["msg"]))


class ReferenceInvestigator:
    name = "reference"

    def __init__(self, walk_back: bool = True, trace: bool = True):
        self.walk_back = walk_back
        self.trace = trace

    # ---- small helpers ------------------------------------------------------------------------------------
    def _try(self, h: Harness, tool: str, **args) -> dict | None:
        try:
            return h.call(tool, **args)
        except ToolRefused:
            return None

    def run(self, h: Harness) -> Answer:
        t = h.call("ticket_read")
        text, ev_ticket = t["content"], t["evidence_id"]
        ids = {k: sorted(set(re.findall(p, text))) for k, p in ID_PATTERNS.items()}
        all_ids = [v for vs in ids.values() for v in vs]
        h.emit("step", name="understand", ids=all_ids)

        # 1. Database first ------------------------------------------------------------------------------------
        db_evs, db_rows = self.database_check(h, ids)

        # 2. Flow: past incidents, then the KB; the engineer confirms ------------------------------------------
        h.emit("step", name="flow")
        leads = h.memory.recall(text)
        assess = h.catalog.rank_flows(text, h.kb, incidents=h.memory.all())
        default_flow = assess.pick or (assess.ranked[0].flow_id if assess.ranked else None)
        flow = h.ask("flow", {"case": assess.case, "message": assess.message,
                              "options": [{"id": r.flow_id, "name": r.name, "why": r.reasons} for r in assess.ranked],
                              "leads": [c["id"] for c in leads]}, default=default_flow)

        # 3. Failure point and walk order ------------------------------------------------------------------------
        owners, ev_codes = self.error_code_owners(h)
        fp, fp_why = h.catalog.failure_point(text, owners)
        order = h.catalog.walk(flow, fp) if self.walk_back else [(s, 0) for s in h.catalog.services]
        h.emit("walk", failure_point=fp, reason=fp_why, order=[s for s, _ in order])

        # 4. Anchor on one failing request -----------------------------------------------------------------------
        mentioned = [c for c in owners if c in text] + EXCEPTION.findall(text)
        anchor, ev_anchor = self.find_anchor(h, order, all_ids, mentioned)
        if anchor is None:
            return self.give_up(h, t, flow, fp, "no failing request matching the ticket was found in the logs")

        # 5. Trace it and find where it starts ---------------------------------------------------------------------
        if self.trace:
            tr = h.call("logs_trace", corr_id=anchor["corr"])
            trace, ev_trace = tr["hits"], tr["evidence_id"]
        else:
            trace, ev_trace = [anchor], ev_anchor
        origin = next((r for r in trace if is_anomaly(r)), anchor)
        origin_svc = self.owning_service(h, trace, origin)
        symptoms = " ".join(r["msg"] + " " + r.get("code", "") for r in trace if is_anomaly(r))
        h.emit("step", name="origin", service=origin_svc, line=origin["msg"])

        # 6. Code: lint the origin repo, keep findings that explain the symptoms ------------------------------------
        finding, ev_lint, ev_code, path = self.find_defect(h, origin_svc, symptoms, origin)
        if finding is None:
            return self.give_up(h, t, flow, fp, f"no code defect in {origin_svc} explains '{origin['msg'][:80]}'")

        # 7. Context: working comparison, recent changes, new or routine -------------------------------------------
        ev_working = self.working_example(h, origin_svc, origin, trace)
        ch = h.call("changes_recent", repo=h.catalog.services[origin_svc]["repo"])
        related = [c for c in ch["changes"]]
        key_err = next((r for r in trace if r["level"] == "ERROR"), origin)
        cmp_q = key_err.get("code") or " ".join(key_err["msg"].split()[:2])
        cmp = h.call("logs_compare_windows", query=cmp_q, service=key_err["service"])
        kb_hit = h.call("kb_search", query=f"{origin_svc} {finding['rule'].replace('-', ' ')} {cmp_q}")
        loud = h.call("logs_count_by_service", level="WARN")

        # 8. Claims --------------------------------------------------------------------------------------------------
        validation_fact = self.validation_fact(finding, db_rows)
        rc_statement = (f"In `{path}` line {finding['line']} (`{finding['code']}`): {finding['message']}. "
                        f"This is where the request in `{anchor['corr']}` goes wrong: {origin['msg']}")
        if validation_fact:
            rc_statement += f" {validation_fact}"
        root = RootCause(statement=rc_statement, service=origin_svc, file=path, line=finding["line"],
                         evidence=[ev_code, ev_lint, ev_trace], status="likely")

        chain = [Claim(statement=f"{r['service']} {r['level']}: {(r.get('code') + ' ') if r.get('code') else ''}{r['msg']}",
                       service=r["service"], evidence=[ev_trace]) for r in trace]
        chain.append(Claim(statement=f"The failure shows in {fp} because {fp_why}.", service=fp, evidence=[ev_ticket, ev_codes]))
        if db_evs:
            rows = "; ".join(f"{k}: " + ", ".join(f"{a}={b}" for a, b in row.items() if b is not None)
                             for k, row in db_rows[:6])
            chain.append(Claim(statement=f"Database before the search: {rows}", evidence=db_evs))
        if ev_working:
            chain.append(Claim(statement=f"A comparable request in {origin_svc} worked: {ev_working[1]}", service=origin_svc,
                               evidence=[ev_working[0]]))
        if related:
            c = related[0]
            chain.append(Claim(statement=f"Change {c['sha']} \"{c['title']}\" merged {c['date'][:10]} in {c['repo']} "
                                         f"({', '.join(c['files'])}).", service=origin_svc, evidence=[ch["evidence_id"]]))
        chain.append(Claim(statement=f"{cmp['summary']}.", evidence=[cmp["evidence_id"]]))
        chain.append(Claim(statement=f"Knowledge base: {kb_hit['passages'][0]}" if kb_hit.get("passages") else "KB: no page",
                           evidence=[kb_hit["evidence_id"]]))

        ruled_out = []
        if fp != origin_svc:
            ruled_out.append(Claim(statement=f"{fp} is where the failure shows, not where it starts: in request "
                                             f"{anchor['corr']} the problem is already present upstream in {origin_svc}.",
                                   service=fp, evidence=[ev_trace]))
        loudest = next(iter(loud["counts"]), None)
        if loudest and loudest not in {r["service"] for r in trace}:
            ruled_out.append(Claim(statement=f"{loudest} is the loudest service ({loud['counts'][loudest]} warnings) but "
                                             f"logs nothing for the failing request.", service=loudest,
                                   evidence=[loud["evidence_id"], ev_trace]))

        summary = (f"{t['summary'].split(': ', 1)[-1]}. Root cause: {origin_svc} "
                   f"({finding['rule'].replace('-', ' ')}) in {path.split('/')[-1]}; the failure shows in {fp}.")
        answer = Answer(ticket=h.estate.ticket.key, summary=summary, flow=flow, failure_point=fp,
                        root_cause=root, causal_chain=chain, ruled_out=ruled_out,
                        fix=Fix(file=path, change=FIXES[finding["rule"]], evidence=[ev_code]),
                        open_questions=[] if related else [f"No recent change in {origin_svc}; why did this start now?"])
        return answer

    # ---- steps ----------------------------------------------------------------------------------------------
    def database_check(self, h: Harness, ids: dict) -> tuple[list[str], list[tuple[str, dict]]]:
        h.emit("step", name="database_check")
        queries = []
        for a in ids["account"]:
            queries.append(("account", f"SELECT * FROM accounts WHERE id = '{a}'"))
        for o in ids["order"]:
            queries.append(("order", f"SELECT * FROM orders WHERE id = '{o}'"))
            queries.append(("payment", f"SELECT * FROM payments WHERE order_id = '{o}'"))
        for d in ids["device"]:
            queries.append(("device", f"SELECT * FROM devices WHERE id = '{d}'"))
            queries.append(("service_event", f"SELECT * FROM service_events WHERE device_id = '{d}'"))
        for m in ids["msisdn"]:
            queries.append(("line", f"SELECT * FROM lines WHERE msisdn = '{m}'"))
        for code in re.findall(r"\b[A-Z]{3,}\d{2}\b", h.estate.ticket.text()):
            queries.append(("promotion", f"SELECT * FROM promotions WHERE code = '{code}'"))
        evs, rows = [], []
        for label, q in queries:
            r = self._try(h, "sql_query", sql=q)
            if r and r["rows"]:
                evs.append(r["evidence_id"])
                rows += [(label, row) for row in r["rows"]]
        return evs, rows

    def error_code_owners(self, h: Harness) -> tuple[dict[str, str], str]:
        r = h.call("kb_search", query="error codes table service meaning", k=2)
        owners = {}
        for line in r["content"].replace("|", "\n|").splitlines():
            m = re.search(r"([A-Z]{2,4}-\d{4})\s+\w+\s+\|\s+([a-z-]+)", line)
            if m:
                owners[m.group(1)] = m.group(2)
        if not owners:  # passages flatten tables; parse "CODE NAME | service |" runs
            for m in re.finditer(r"([A-Z]{2,4}-\d{4}) [A-Z_]+ \| ([a-z-]+) \|", r["content"]):
                owners[m.group(1)] = m.group(2)
        return owners, r["evidence_id"]

    def find_anchor(self, h: Harness, order, ids, mentioned) -> tuple[dict | None, str | None]:
        best, best_ev, best_score = None, None, 0
        for svc, _ in order:
            for level in ("ERROR", "WARN"):
                r = self._try(h, "logs_search", query="", service=svc, level=level, limit=50)
                if not r or not r["count"]:
                    continue
                for rec in r["hits"]:
                    text = rec["msg"] + " " + rec.get("code", "")
                    score = sum(2 for i in ids if i in text) + sum(1 for m in mentioned if m in text)
                    score += 1 if level == "ERROR" else 0
                    if score > best_score and any(i in text for i in ids):
                        best, best_ev, best_score = rec, r["evidence_id"], score
            if best is not None:
                return best, best_ev
        # Fall back to searching the ticket's identifiers anywhere.
        for i in ids:
            r = self._try(h, "logs_search", query=i, limit=20)
            if r and r["count"]:
                hits = sorted(r["hits"], key=lambda x: x["level"] != "ERROR")
                return hits[0], r["evidence_id"]
        return None, None

    def owning_service(self, h: Harness, trace: list[dict], origin: dict) -> str:
        """Systems of record without a repo (billing-core, the database) reject bad input; the cause is in the
        nearest earlier service in the same request that has code."""
        svc = origin["service"]
        if h.catalog.services[svc]["repo"]:
            return svc
        before = [r["service"] for r in trace if r["ts"] <= origin["ts"] and h.catalog.services[r["service"]]["repo"]]
        return before[-1] if before else svc

    def find_defect(self, h: Harness, svc: str, symptoms: str, origin: dict):
        repo = h.catalog.services[svc]["repo"]
        wanted = [rule for pat, rules in SYMPTOM_RULES if pat.search(symptoms) for rule in rules]
        paths = h.call("code_files", repo=repo)["files"]
        best = None
        for path in paths[:8]:
            lint = h.call("code_lint", path=path)
            for f in lint["findings"]:
                rank = wanted.index(f["rule"]) if f["rule"] in wanted else None
                if rank is not None and (best is None or rank < best[0]):
                    best = (rank, f, lint["evidence_id"], path)
        if best is None:
            return None, None, None, None
        _, finding, ev_lint, path = best
        code = h.call("code_read", path=path, start=max(1, finding["line"] - 8), end=finding["line"] + 4)
        m = re.search(r"(\w+)=null\b", origin["msg"])
        if m:  # cite the setter for the null field when the code names it
            self._try(h, "code_search", query=f"set{m.group(1).capitalize()}", repo=repo)
        return finding, ev_lint, code["evidence_id"], path

    def working_example(self, h: Harness, svc: str, origin: dict, trace: list[dict]):
        m = re.search(r"(\w+)=null\b", origin["msg"])
        if not m:
            return None
        prefix = " ".join(origin["msg"].split()[:2])
        r = self._try(h, "logs_search", query=prefix, service=svc, limit=30)
        for rec in (r or {}).get("hits", []):
            if rec["corr"] != origin["corr"] and f"{m.group(1)}=null" not in rec["msg"]:
                return r["evidence_id"], rec["msg"]
        return None

    @staticmethod
    def validation_fact(finding: dict, db_rows) -> str:
        if finding["rule"] != "validation-limit":
            return ""
        limit = int(re.search(r"= (\d+)", finding["message"]).group(1))
        for label, row in db_rows:
            for k, v in row.items():
                if isinstance(v, str) and len(v) > limit:
                    return f"The ticket's {label} has {k} of {len(v)} characters, above the limit of {limit}."
        return ""

    def give_up(self, h: Harness, t: dict, flow, fp, why: str) -> Answer:
        return Answer(ticket=h.estate.ticket.key, summary=f"Not established: {why}.", flow=flow, failure_point=fp,
                      root_cause=RootCause(statement=f"Not established: {why}.", status="not_established",
                                           evidence=[t["evidence_id"]]),
                      open_questions=[why])
