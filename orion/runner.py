"""One entry point for an investigation: build the estate, run a policy inside the harness, verify, remember."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .answer import Answer
from .estate.builder import Estate, build_estate
from .harness import Budget, BudgetExceeded, Harness
from .memory import CaseStore
from .verify import finalize


@dataclass
class RunResult:
    answer: Answer
    harness: Harness
    seconds: float

    @property
    def tool_calls(self) -> int:
        return self.harness.budget.tool_calls


def get_policy(name: str):
    if name == "reference":
        from .policies.reference import ReferenceInvestigator
        return ReferenceInvestigator()
    if name == "no-walk-back":
        from .policies.reference import ReferenceInvestigator
        return ReferenceInvestigator(walk_back=False, trace=False)
    if name == "loudest-error":
        from .policies.baselines import LoudestError
        return LoudestError()
    if name == "error-owner":
        from .policies.baselines import ErrorOwner
        return ErrorOwner()
    if name.startswith("llm"):
        from .policies.llm import LLMInvestigator
        return LLMInvestigator.from_env(name)
    raise ValueError(f"unknown policy {name!r}")


def investigate(scenario: str | Estate, policy="reference", *, ask=None, seed: int = 7, noise: float = 1.0,
                budget: Budget | None = None, memory: CaseStore | None = None, listeners=()) -> RunResult:
    estate = scenario if isinstance(scenario, Estate) else build_estate(scenario, seed=seed, noise_level=noise)
    h = Harness(estate, budget=budget, ask=ask, memory=memory)
    h.listeners.extend(listeners)
    pol = get_policy(policy) if isinstance(policy, str) else policy
    h.emit("start", ticket=estate.ticket.key, policy=getattr(pol, "name", str(pol)))
    t0 = time.monotonic()
    try:
        answer = pol.run(h)
    except BudgetExceeded as exc:
        from .answer import RootCause
        answer = Answer(ticket=estate.ticket.key, summary=f"Stopped: {exc}",
                        root_cause=RootCause(statement=f"Not established: {exc}", status="not_established"))
    answer = finalize(answer, h)
    if answer.verdict == "verified" and answer.root_cause.service:
        h.memory.add({"id": estate.ticket.key, "summary": estate.ticket.summary, "root_cause": answer.root_cause.statement,
                      "services": [answer.root_cause.service], "flows": [answer.flow] if answer.flow else [],
                      "signals": []})
    h.emit("done", confidence=answer.confidence, verdict=answer.verdict)
    return RunResult(answer, h, time.monotonic() - t0)
