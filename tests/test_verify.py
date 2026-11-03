from orion.answer import Answer, Claim, RootCause
from orion.estate.builder import build_estate
from orion.harness import Harness
from orion.verify import verify


def _h():
    h = Harness(build_estate("gateway-misroute"))
    log = h.call("logs_search", query="GW-0502", limit=1)
    code = h.call("code_read", path="api-gateway/routes/routes.yaml")
    return h, log["evidence_id"], code["evidence_id"]


def test_valid_answer_passes():
    h, log, code = _h()
    a = Answer(ticket="T", summary="s", root_cause=RootCause(statement="route points at `order-service-v1`",
                                                             service="api-gateway", evidence=[log, code]))
    assert verify(a, h) == []


def test_invented_evidence_and_quotes_are_caught():
    h, log, code = _h()
    a = Answer(ticket="T", summary="s",
               root_cause=RootCause(statement="caused by `DROP TABLE`", service="api-gateway", evidence=[log, code]),
               causal_chain=[Claim(statement="made up", evidence=["E999"]), Claim(statement="no evidence")])
    problems = verify(a, h)
    assert any("DROP TABLE" in p for p in problems)
    assert any("E999" in p for p in problems)
    assert any("no evidence" in p for p in problems)


def test_root_cause_needs_code_and_runtime_evidence():
    h, log, _code = _h()
    a = Answer(ticket="T", summary="s", root_cause=RootCause(statement="x", service="api-gateway", evidence=[log]))
    assert "root cause: no code evidence" in verify(a, h)
