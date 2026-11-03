"""Read-only tools over the estate. Each has a JSON schema (for LLM tool calling) and a guard.

Systems: logs (an ELK-style search over JSON log records), sql (the subscriber database, read-only),
code (source repos), changes (merged changes), kb (hybrid search), ticket. Nothing here can write.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .estate.builder import fmt_ts, parse_ts

MAX_ROWS = 200
FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|drop|alter|attach|detach|pragma|create|replace|vacuum|reindex)\b", re.IGNORECASE)


@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict
    fn: Callable[..., dict]
    system: str
    records_evidence: bool = True


def guard_sql(sql: str) -> str:
    from .harness import ToolRefused

    body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip().rstrip(";").strip()
    if ";" in body:
        raise ToolRefused("one statement per query")
    if not re.match(r"^(select|with)\b", body, re.IGNORECASE):
        raise ToolRefused("only SELECT or WITH queries are allowed")
    if FORBIDDEN_SQL.search(body):
        raise ToolRefused("query contains a write or admin keyword")
    return body


def _p(type_: str, desc: str, required: bool = False, **extra) -> dict:
    d = {"type": type_, "description": desc, **extra}
    if required:
        d["x-required"] = True
    return d


def build_tools(h) -> dict[str, ToolSpec]:  # h: Harness
    est = h.estate
    win_start, win_end = est.window
    repo_root: Path = est.repo_dir
    all_files = sorted(p for p in repo_root.rglob("*") if p.is_file() and p.name != "CHANGES.yaml")

    def _window(start, end):
        return (start or fmt_ts(win_start), end or fmt_ts(win_end))

    def _match(rec, query, service, level):
        if service and rec.service != service:
            return False
        if level and rec.level != level.upper():
            return False
        if query:
            text = rec.text().lower()
            return all(term in text for term in query.lower().split())
        return True

    # ---- ticket ---------------------------------------------------------------------------------------------
    def ticket_read() -> dict:
        t = est.ticket
        return {"summary": f"ticket {t.key}: {t.summary}", "content": t.text(), "created": t.created}

    # ---- logs -----------------------------------------------------------------------------------------------
    def logs_search(query: str = "", service: str | None = None, level: str | None = None,
                    start: str | None = None, end: str | None = None, limit: int = 15) -> dict:
        s, e = _window(start, end)
        hits = [r for r in est.logs if s <= r.ts <= e and _match(r, query, service, level)]
        shown = hits[: max(1, min(limit, 50))]
        return {"summary": f"{len(hits)} log line(s) for '{query or '*'}'"
                           + (f" in {service}" if service else "") + f" [{s} .. {e}]",
                "count": len(hits), "hits": [r.__dict__ for r in shown],
                "content": "\n".join(r.text() + f" corr={r.corr}" for r in shown)}

    def logs_count_by_service(query: str = "", level: str | None = None,
                              start: str | None = None, end: str | None = None) -> dict:
        s, e = _window(start, end)
        counts: dict[str, int] = {}
        for r in est.logs:
            if s <= r.ts <= e and _match(r, query, None, level):
                counts[r.service] = counts.get(r.service, 0) + 1
        ordered = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
        return {"summary": f"counts by service for '{query or level or 'all'}'", "counts": ordered,
                "content": ", ".join(f"{k}={v}" for k, v in ordered.items())}

    def logs_trace(corr_id: str) -> dict:
        hits = [r for r in est.logs if r.corr == corr_id]
        return {"summary": f"{len(hits)} line(s) for request {corr_id} across "
                           f"{len({r.service for r in hits})} service(s)",
                "hits": [r.__dict__ for r in hits], "content": "\n".join(r.text() for r in hits)}

    def logs_compare_windows(query: str, service: str | None = None) -> dict:
        s, e = win_start, win_end
        now = sum(1 for r in est.logs if fmt_ts(s) <= r.ts <= fmt_ts(e) and _match(r, query, service, None))
        before = sum(1 for r in est.logs if fmt_ts(s - timedelta(days=1)) <= r.ts <= fmt_ts(e - timedelta(days=1))
                     and _match(r, query, service, None))
        trend = "new" if before == 0 and now > 0 else ("rising" if now > 1.5 * before else "steady")
        return {"summary": f"'{query}': {now} in the incident window vs {before} the day before ({trend})",
                "now": now, "before": before, "trend": trend,
                "content": f"incident={now} previous_day={before} trend={trend}"}

    # ---- sql ------------------------------------------------------------------------------------------------
    def sql_query(sql: str) -> dict:
        body = guard_sql(sql)
        conn = est.connect_readonly()
        try:
            rows = [dict(r) for r in conn.execute(body).fetchmany(MAX_ROWS + 1)]
        finally:
            conn.close()
        cut = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        content = "\n".join(str(r) for r in rows) or "(no rows)"
        return {"summary": f"{len(rows)} row(s){' (cut at 200)' if cut else ''}: {body[:90]}", "rows": rows,
                "content": content}

    def sql_schema() -> dict:
        conn = est.connect_readonly()
        try:
            tables = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")]
        finally:
            conn.close()
        return {"summary": f"{len(tables)} table/index definitions", "content": "\n".join(tables)}

    # ---- code -----------------------------------------------------------------------------------------------
    def code_search(query: str, repo: str | None = None) -> dict:
        q = query.lower()
        hits = []
        for p in all_files:
            rel = str(p.relative_to(repo_root))
            if repo and not rel.startswith(repo + "/"):
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if q in line.lower():
                    hits.append({"path": rel, "line": i, "text": line.strip()})
        return {"summary": f"{len(hits)} match(es) for '{query}'" + (f" in {repo}" if repo else ""),
                "hits": hits[:30], "content": "\n".join(f"{x['path']}:{x['line']}: {x['text']}" for x in hits[:30])}

    def code_files(repo: str) -> dict:
        files = [str(p.relative_to(repo_root)) for p in all_files if str(p.relative_to(repo_root)).startswith(repo + "/")]
        return {"summary": f"{len(files)} file(s) in {repo}", "files": files, "content": "\n".join(files)}

    def code_read(path: str, start: int = 1, end: int = 400) -> dict:
        p = (repo_root / path).resolve()
        if repo_root.resolve() not in p.parents or not p.is_file():
            from .harness import ToolRefused

            raise ToolRefused(f"no such file in the repos: {path}")
        lines = p.read_text().splitlines()
        sel = lines[max(start, 1) - 1: end]
        whole = start <= 1 and end >= len(lines)
        content = "\n".join(f"{i:4d}  {line}" for i, line in enumerate(sel, max(start, 1)))
        return {"summary": f"{path} lines {max(start, 1)}-{min(end, len(lines))} of {len(lines)}"
                           + (" (whole file)" if whole else ""), "content": content, "path": path}

    def code_lint(path: str) -> dict:
        from .lint import lint_file

        p = repo_root / path
        findings = lint_file(path, p.read_text(), h.catalog)
        return {"summary": f"{len(findings)} finding(s) in {path}", "findings": findings,
                "content": "\n".join(f"{path}:{f['line']}: [{f['rule']}] {f['message']}" for f in findings)}

    # ---- changes ----------------------------------------------------------------------------------------------
    def changes_recent(repo: str | None = None, days: int = 45) -> dict:
        created = parse_ts(est.ticket.created)
        out = [c for c in est.changes if (not repo or c["repo"] == repo)
               and created - timedelta(days=days) <= parse_ts(c["date"]) <= created]
        return {"summary": f"{len(out)} merged change(s)" + (f" in {repo}" if repo else "") + f" in the {days} days before the ticket",
                "changes": out,
                "content": "\n".join(f"{c['sha']} {c['date']} {c['repo']}: {c['title']} {c['files']}" for c in out)}

    # ---- kb ---------------------------------------------------------------------------------------------------
    def kb_search(query: str, k: int = 4) -> dict:
        res = h.kb.search(query, k=k)
        return {"summary": f"{len(res)} KB passage(s) for '{query}'", "passages": [p.ref for p, _ in res],
                "content": "\n\n".join(f"[{p.ref}] {p.text}" for p, _ in res)}

    S, P = ToolSpec, _p
    specs = [
        S("ticket_read", "Read the ticket under investigation.", {}, ticket_read, "ticket"),
        S("logs_search", "Search log lines (all terms must match). Defaults to the incident window.",
          {"query": P("string", "space-separated terms"), "service": P("string", "service name"),
           "level": P("string", "INFO|WARN|ERROR"), "start": P("string", "ISO start"), "end": P("string", "ISO end"),
           "limit": P("integer", "max lines shown")}, logs_search, "logs"),
        S("logs_count_by_service", "Count matching log lines per service.",
          {"query": P("string", "terms"), "level": P("string", "level")}, logs_count_by_service, "logs"),
        S("logs_trace", "Every log line for one request id (corr), across services, in time order.",
          {"corr_id": P("string", "request id", True)}, logs_trace, "logs"),
        S("logs_compare_windows", "Compare a query's count in the incident window with the same window a day before.",
          {"query": P("string", "terms", True), "service": P("string", "service")}, logs_compare_windows, "logs"),
        S("sql_query", "Run one read-only SELECT on the subscriber database (max 200 rows).",
          {"sql": P("string", "a single SELECT or WITH statement", True)}, sql_query, "sql"),
        S("sql_schema", "Show table definitions.", {}, sql_schema, "sql"),
        S("code_search", "Search source code (literal, case-insensitive).",
          {"query": P("string", "text to find", True), "repo": P("string", "repo name")}, code_search, "code"),
        S("code_files", "List the files of one repo.", {"repo": P("string", "repo name", True)}, code_files, "code"),
        S("code_read", "Read a file from the repos.",
          {"path": P("string", "path relative to the repos root", True), "start": P("integer", "first line"),
           "end": P("integer", "last line")}, code_read, "code"),
        S("code_lint", "Static checks for common incident-causing defects in one file.",
          {"path": P("string", "file path", True)}, code_lint, "code"),
        S("changes_recent", "Merged changes before the ticket, optionally for one repo.",
          {"repo": P("string", "repo"), "days": P("integer", "look-back days")}, changes_recent, "changes"),
        S("kb_search", "Hybrid search over the team knowledge base.",
          {"query": P("string", "question", True), "k": P("integer", "passages")}, kb_search, "kb"),
    ]
    return {s.name: s for s in specs}


def tool_schemas(tools: dict[str, ToolSpec]) -> list[dict]:
    out = []
    for s in tools.values():
        props = {k: {kk: vv for kk, vv in v.items() if kk != "x-required"} for k, v in s.params.items()}
        out.append({"name": s.name, "description": s.description,
                    "input_schema": {"type": "object", "properties": props,
                                     "required": [k for k, v in s.params.items() if v.get("x-required")]}})
    return out
