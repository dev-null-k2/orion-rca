"""The LLM loop, driven by a scripted fake model (no network)."""
from orion.models import Gateway, ModelError, Provider, ToolCall, Turn
from orion.policies.llm import LLMInvestigator
from orion.runner import investigate


class Scripted(Provider):
    def __init__(self, turns):
        self.turns, self.seen = list(turns), []

    def complete(self, system, messages, tools, model, max_tokens):
        self.seen.append(messages)
        nxt = self.turns.pop(0)
        return nxt(messages) if callable(nxt) else nxt


def _answer(messages):
    import re
    blob = str(messages)
    ids = re.findall(r"\bE\d+\b", blob)
    return Turn("", [ToolCall("s1", "submit_answer", {
        "ticket": "x", "summary": "gateway route points at a host that does not exist",
        "root_cause": {"statement": "route /v2/refills points at `order-service-v1`", "service": "api-gateway",
                       "file": "api-gateway/routes/routes.yaml", "line": 9, "evidence": ids[:2]}})])


def test_llm_loop_calls_tools_and_submits():
    script = [
        Turn("", [ToolCall("t1", "logs_search", {"query": "GW-0502", "limit": 2})]),
        Turn("", [ToolCall("t2", "code_read", {"path": "api-gateway/routes/routes.yaml"})]),
        _answer,
    ]
    pol = LLMInvestigator(Gateway(Scripted(script), ["fake"], sleep=lambda s: None))
    r = investigate("gateway-misroute", pol)
    assert r.answer.root_cause.service == "api-gateway"
    assert r.answer.verdict == "verified"


def test_bad_answer_is_sent_back_once():
    bad = Turn("", [ToolCall("s0", "submit_answer", {"ticket": "x", "summary": "s",
                                                      "root_cause": {"statement": "guess", "evidence": []}})])
    script = [bad, Turn("", [ToolCall("t1", "logs_search", {"query": "GW-0502", "limit": 2})]),
              Turn("", [ToolCall("t2", "code_read", {"path": "api-gateway/routes/routes.yaml"})]), _answer]
    pol = LLMInvestigator(Gateway(Scripted(script), ["fake"], sleep=lambda s: None))
    r = investigate("gateway-misroute", pol)
    assert any(e.kind == "sent_back" for e in r.harness.events)
    assert r.answer.verdict == "verified"


def test_gateway_falls_back_to_the_next_model():
    class Flaky(Provider):
        def complete(self, system, messages, tools, model, max_tokens):
            if model == "primary":
                raise ModelError("500")
            return Turn("ok", [], {"input_tokens": 10, "output_tokens": 2}, model)

    gw = Gateway(Flaky(), ["primary", "backup"], max_retries=3, sleep=lambda s: None)
    t = gw.complete("s", [{"role": "user", "content": "hi"}], [])
    assert t.model == "backup" and gw.usage["input_tokens"] == 10


def test_compaction_stubs_old_results():
    pol = LLMInvestigator(Gateway(Scripted([]), ["fake"]), context_tokens=100)
    msgs = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(i), "content": "E1 x\n" + "y" * 400}]}
            for i in range(10)]
    pol.compact(msgs, keep_recent=2)
    assert sum(m["content"][0]["content"].startswith("[compacted]") for m in msgs) == 8
