"""LLM investigator: a tool-calling loop over the same harness, tools, ledger and verification as the
reference policy.

* Specialist sub-agents (logs, sql, code, kb) run their own short loops with only their tools.
* Old tool results are compacted to one-line stubs (with their evidence ids) as the context fills up.
* Steering messages from the engineer are injected between turns.
* `submit_answer` is checked by the verifier; a failing answer is sent back once with the problems listed.
"""
from __future__ import annotations

import json

from ..answer import Answer
from ..harness import BudgetExceeded, Harness, ToolRefused
from ..models import Gateway
from ..tools import tool_schemas
from ..verify import verify

SYSTEM = """You are Orion, an incident investigator for a production estate. You find the root cause of the ticket.
Method:
1. Read the ticket. Check the customer's records in the database before searching logs.
2. Find where the failure shows (the failure point). Work backwards from it: its adapters, then their callers.
3. Anchor on ONE failing request that matches the ticket, then trace its corr_id across services.
   The loudest error is rarely the cause.
4. The earliest anomaly in that request is where the problem starts. Read and lint that service's code.
5. Check recent changes and compare the error rate with the day before.
6. Submit with submit_answer. Every claim cites evidence ids (E1, E2, ...) returned by tools. Quote exact values in
   backticks only if they appear in the cited evidence. The root cause must cite code AND logs or database evidence.
Never invent evidence ids. If you cannot establish the cause, say so with status "not_established"."""

SUBAGENTS = {
    "logs": ["logs_search", "logs_count_by_service", "logs_trace", "logs_compare_windows"],
    "sql": ["sql_query", "sql_schema"],
    "code": ["code_files", "code_search", "code_read", "code_lint", "changes_recent"],
    "kb": ["kb_search"],
}

SUBMIT = {"name": "submit_answer", "description": "Submit the final RCA.",
          "input_schema": Answer.model_json_schema()}
DELEGATE = {"name": "delegate", "description": "Hand a focused question to a specialist sub-agent "
            "(logs, sql, code or kb). It returns findings with evidence ids.",
            "input_schema": {"type": "object", "required": ["agent", "task"],
                             "properties": {"agent": {"type": "string", "enum": list(SUBAGENTS)},
                                            "task": {"type": "string"}}}}


def _est_tokens(messages: list[dict]) -> int:
    return len(json.dumps(messages)) // 4


class LLMInvestigator:
    name = "llm"

    def __init__(self, gateway: Gateway, max_turns: int = 40, context_tokens: int = 120_000):
        self.gw, self.max_turns, self.context_tokens = gateway, max_turns, context_tokens

    @classmethod
    def from_env(cls, name: str = "llm") -> LLMInvestigator:
        return cls(Gateway.from_env(name))

    # ---- context management ---------------------------------------------------------------------------------
    def compact(self, messages: list[dict], keep_recent: int = 6) -> None:
        """Replace older tool results with stubs once the context passes 80% of the window."""
        if _est_tokens(messages) < 0.8 * self.context_tokens:
            return
        results = [(i, j) for i, m in enumerate(messages) if isinstance(m["content"], list)
                   for j, b in enumerate(m["content"]) if b.get("type") == "tool_result"]
        for i, j in results[:-keep_recent]:
            block = messages[i]["content"][j]
            if not block["content"].startswith("[compacted]"):
                first = block["content"].splitlines()[0][:200]
                block["content"] = f"[compacted] {first} (re-read the evidence id if you need the detail)"

    def _run_tool(self, h: Harness, call) -> str:
        try:
            r = h.call(call.name, **call.args)
        except (ToolRefused, TypeError) as exc:
            return f"REFUSED: {exc}"
        head = f"{r.get('evidence_id', '')} {r['summary']}".strip()
        return head + "\n" + r.get("content", "")[:3500]

    # ---- sub-agent ------------------------------------------------------------------------------------------
    def delegate(self, h: Harness, agent: str, task: str, turns: int = 8) -> str:
        tools = [t for t in tool_schemas(h.tools) if t["name"] in SUBAGENTS.get(agent, [])]
        msgs = [{"role": "user", "content": f"Ticket:\n{h.estate.ticket.text()}\n\nTask: {task}\n"
                                            "Reply with findings, each followed by its evidence ids."}]
        h.emit("subagent_start", agent=agent, task=task)
        for _ in range(turns):
            turn = self.gw.complete(f"You are Orion's {agent} specialist. Use only your tools.", msgs, tools, 2048)
            msgs.append({"role": "assistant", "content": self._blocks(turn)})
            if not turn.tool_calls:
                h.emit("subagent_end", agent=agent)
                return turn.text
            msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": c.id,
                                                      "content": self._run_tool(h, c)} for c in turn.tool_calls]})
        return "sub-agent stopped at its turn limit"

    @staticmethod
    def _blocks(turn) -> list[dict]:
        blocks = [{"type": "text", "text": turn.text}] if turn.text else []
        return blocks + [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in turn.tool_calls]

    # ---- main loop ------------------------------------------------------------------------------------------
    def run(self, h: Harness) -> Answer:
        tools = tool_schemas(h.tools) + [DELEGATE, SUBMIT]
        leads = h.memory.recall(h.estate.ticket.text())
        assess = h.catalog.rank_flows(h.estate.ticket.text(), h.kb, incidents=h.memory.all())
        flow = h.ask("flow", {"case": assess.case, "message": assess.message,
                              "options": [{"id": r.flow_id, "name": r.name, "why": r.reasons} for r in assess.ranked]},
                     default=assess.pick or (assess.ranked[0].flow_id if assess.ranked else None))
        start = f"Investigate ticket {h.estate.ticket.key}. Business flow confirmed by the engineer: {flow}."
        if leads:
            start += " Past cases (leads, not proof): " + "; ".join(f"{c['id']}: {c['root_cause']}" for c in leads)
        messages: list[dict] = [{"role": "user", "content": start}]
        sent_back = False
        for _ in range(self.max_turns):
            while h.steering:
                messages.append({"role": "user", "content": f"Engineer steering: {h.steering.pop(0)}"})
            self.compact(messages)
            turn = self.gw.complete(SYSTEM, messages, tools)
            h.budget.tokens = self.gw.usage["input_tokens"] + self.gw.usage["output_tokens"]
            messages.append({"role": "assistant", "content": self._blocks(turn)})
            if not turn.tool_calls:
                messages.append({"role": "user", "content": "Continue, or call submit_answer."})
                continue
            results = []
            for call in turn.tool_calls:
                if call.name == "submit_answer":
                    answer = Answer.model_validate({**call.args, "ticket": h.estate.ticket.key})
                    problems = verify(answer, h)
                    if problems and not sent_back:
                        sent_back = True
                        h.emit("sent_back", problems=problems)
                        results.append({"type": "tool_result", "tool_use_id": call.id,
                                        "content": "Answer rejected by verification:\n- " + "\n- ".join(problems)})
                        continue
                    return answer
                content = (self.delegate(h, call.args.get("agent", ""), call.args.get("task", ""))
                           if call.name == "delegate" else self._run_tool(h, call))
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": content})
            messages.append({"role": "user", "content": results})
        raise BudgetExceeded(f"no answer after {self.max_turns} turns")
