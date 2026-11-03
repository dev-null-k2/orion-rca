"""Static checks for defect patterns that cause production incidents.

These are hints for the investigator, not verdicts: a finding only becomes part of a root cause when runtime
evidence (logs or database rows) shows the same mechanism happening.
"""
from __future__ import annotations

import re

import yaml


def lint_file(path: str, text: str, catalog=None) -> list[dict]:
    lines = text.splitlines()
    out: list[dict] = []

    def add(i: int, rule: str, msg: str):
        out.append({"line": i, "rule": rule, "message": msg, "code": lines[i - 1].strip() if 0 < i <= len(lines) else ""})

    for i, line in enumerate(lines, 1):
        s = line.strip()
        # A failure turned into a null return: callers that dereference it crash far from the cause.
        if s == "return null;":
            add(i, "null-on-failure", "returns null on failure; the real error is dropped and callers must null-check")
        # Dereference right after an assignment from a call, with no null check in between.
        m = re.match(r"(\w+) = \w+\.\w+\(\1\);", s)
        if m and i < len(lines) and f"{m.group(1)}.get" in lines[i] and "null" not in lines[i]:
            add(i + 1, "unchecked-deref", f"'{m.group(1)}' is dereferenced without a null check")
        # Catch-all that maps every failure to one generic code and does not log the exception.
        if re.match(r"\}?\s*catch \(Exception (\w+)\)", s):
            var = re.match(r"\}?\s*catch \(Exception (\w+)\)", s).group(1)
            block = " ".join(lines[i:i + 4])
            if not re.search(rf"\b{var}\b", block):
                add(i, "swallowed-exception", "catches every exception and drops it; the real reason is never logged")
        # Retry loop that makes a fresh idempotency/request id per attempt.
        if re.search(r"uuid\.uuid4\(\)|UUID\.randomUUID\(\)", s):
            loop = "\n".join(lines[max(0, i - 6):i])
            if re.search(r"for .* in range|while|attempt", loop):
                add(i, "non-idempotent-retry", "a new request id is generated on every retry, so the server cannot de-duplicate")
        # Timeout constants worth comparing with the documented latency of the dependency.
        m = re.match(r"([A-Z_]*TIMEOUT[A-Z_]*)\s*=\s*([\d.]+)", s)
        if m:
            add(i, "timeout-budget", f"{m.group(1)} = {m.group(2)}s; compare with the dependency's documented p99 latency")
        # Timezone-naive comparisons of times entered in a local zone.
        if "tzinfo=None" in s or ("fromisoformat" in s and "Z" not in s and "tz" not in s and "Eastern" in text):
            add(i, "naive-timezone", "compares or builds times without a timezone; local wall-clock values are read as UTC")
        # Request values trusted for some branches only.
        m = re.match(r"\w+\.set(\w+)\((\w+)\);", s)
        if m:
            var = m.group(2)
            assign = [j for j, ln in enumerate(lines[:i], 1) if re.search(rf"\b{var}\s*=", ln)]
            guarded = [j for j in assign if re.search(r"^\s*if\b", "\n".join(lines[max(0, j - 3):j - 1]), re.MULTILINE)]
            if len(assign) >= 2 and guarded:
                add(i, "partial-fallback", f"'{var}' is only resolved in one branch (line {guarded[0]}); "
                                           "other branches pass the request value through unchecked")
        # Validation limits added recently are a common trigger for generic errors.
        m = re.match(r"private static final int (MAX_\w+) = (\d+);", s)
        if m:
            add(i, "validation-limit", f"{m.group(1)} = {m.group(2)}; inputs above it are rejected")

    if path.endswith((".yaml", ".yml")) and catalog is not None:
        try:
            routes = yaml.safe_load(text) or []
        except yaml.YAMLError:
            routes = []
        for r in routes if isinstance(routes, list) else []:
            host = re.sub(r"^https?://", "", str(r.get("upstream", ""))).split(":")[0]
            if host and host not in catalog.services:
                i = next((n for n, ln in enumerate(lines, 1) if host in ln), 0)
                add(i, "unknown-upstream", f"route {r.get('path')} points at '{host}', which is not a known service")
    return out
