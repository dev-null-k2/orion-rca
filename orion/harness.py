"""The agent harness: tool gate, signed evidence ledger, budgets, events and human-in-the-loop hooks.

Policies (the reference investigator, or an LLM) never touch a system directly. Every action goes through
`Harness.call`, which checks the tool exists, enforces the run's budgets and repeat limits, runs the
read-only tool, records the result as signed evidence with an id (E1, E2, ...) and emits an event.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .estate.builder import Estate
from .flows import Catalog
from .memory import CaseStore
from .retrieval import KnowledgeBase


class BudgetExceeded(RuntimeError):
    pass


class ToolRefused(RuntimeError):
    pass


@dataclass
class Budget:
    max_tool_calls: int = 60
    max_seconds: float = 300.0
    max_tokens: int = 400_000
    max_same_call: int = 2
    tool_calls: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.monotonic)

    def check(self) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"tool-call budget of {self.max_tool_calls} used")
        if time.monotonic() - self.started > self.max_seconds:
            raise BudgetExceeded(f"time budget of {self.max_seconds:.0f}s used")
        if self.tokens > self.max_tokens:
            raise BudgetExceeded(f"token budget of {self.max_tokens} used")

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started


@dataclass
class Evidence:
    id: str
    tool: str
    args: dict
    system: str
    summary: str
    content: str
    ts: float
    sig: str = ""

    def payload(self) -> bytes:
        body = {k: v for k, v in self.__dict__.items() if k != "sig"}
        return json.dumps(body, sort_keys=True).encode()


class Ledger:
    """Append-only evidence store. Each record is HMAC-SHA256 signed; a tampered record fails `verify`."""

    def __init__(self, key: bytes | None = None):
        self._key = key or os.environ.get("ORION_LEDGER_KEY", "").encode() or secrets.token_bytes(32)
        self.records: dict[str, Evidence] = {}

    def add(self, tool: str, args: dict, system: str, summary: str, content: str) -> Evidence:
        ev = Evidence(f"E{len(self.records) + 1}", tool, args, system, summary, content[:6000], time.time())
        ev.sig = hmac.new(self._key, ev.payload(), hashlib.sha256).hexdigest()
        self.records[ev.id] = ev
        return ev

    def verify(self, ev: Evidence) -> bool:
        return hmac.compare_digest(ev.sig, hmac.new(self._key, ev.payload(), hashlib.sha256).hexdigest())

    def get(self, eid: str) -> Evidence | None:
        ev = self.records.get(eid)
        return ev if ev and self.verify(ev) else None

    def export_jsonl(self) -> str:
        return "\n".join(json.dumps(e.__dict__) for e in self.records.values())


@dataclass
class Event:
    kind: str
    data: dict
    t: float = field(default_factory=time.monotonic)


AskHandler = Callable[[str, dict], Any]


class Harness:
    def __init__(self, estate: Estate, *, budget: Budget | None = None, ask: AskHandler | None = None,
                 memory: CaseStore | None = None, kb: KnowledgeBase | None = None):
        from .tools import build_tools  # local import to avoid a cycle

        self.estate = estate
        self.budget = budget or Budget()
        self.ledger = Ledger()
        self.catalog = Catalog()
        self.kb = kb or KnowledgeBase(estate.kb_dir)
        self.memory = memory or CaseStore()
        self.tools = build_tools(self)
        self.events: list[Event] = []
        self.listeners: list[Callable[[Event], None]] = []
        self.steering: list[str] = []
        self._ask = ask
        self._calls: dict[str, int] = {}

    # ---- events -------------------------------------------------------------------------------------------
    def emit(self, kind: str, **data) -> None:
        ev = Event(kind, data)
        self.events.append(ev)
        for listener in self.listeners:
            listener(ev)

    # ---- human in the loop ---------------------------------------------------------------------------------
    def ask(self, kind: str, payload: dict, default: Any = None) -> Any:
        """Ask the engineer. With no handler (batch, evals) the default is taken and logged."""
        self.emit("ask", question=kind, **payload)
        if self._ask is None:
            self.emit("ask_default", question=kind, answer=default)
            return default
        answer = self._ask(kind, payload)
        self.emit("ask_answer", question=kind, answer=answer)
        return default if answer in (None, "") else answer

    def steer(self, message: str) -> None:
        self.steering.append(message)
        self.emit("steer", message=message)

    # ---- the tool gate -------------------------------------------------------------------------------------
    def call(self, tool: str, **args) -> dict:
        if tool not in self.tools:
            raise ToolRefused(f"unknown tool {tool!r}")
        key = tool + json.dumps(args, sort_keys=True, default=str)
        if self._calls.get(key, 0) >= self.budget.max_same_call:
            raise ToolRefused(f"{tool} already called {self.budget.max_same_call}x with the same arguments")
        self.budget.check()
        self._calls[key] = self._calls.get(key, 0) + 1
        self.budget.tool_calls += 1
        spec = self.tools[tool]
        self.emit("tool_start", tool=tool, args=args)
        t0 = time.monotonic()
        try:
            result = spec.fn(**args)
        except ToolRefused as exc:
            self.emit("tool_refused", tool=tool, reason=str(exc))
            raise
        ms = round((time.monotonic() - t0) * 1000, 1)
        if spec.records_evidence:
            ev = self.ledger.add(tool, args, spec.system, result["summary"], result.get("content", ""))
            result["evidence_id"] = ev.id
        self.emit("tool_end", tool=tool, ms=ms, summary=result["summary"], evidence_id=result.get("evidence_id"))
        return result
