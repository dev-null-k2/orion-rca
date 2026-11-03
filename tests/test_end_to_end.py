import pytest

from orion.estate.builder import list_scenarios
from orion.evals.run import score_case
from orion.report import to_markdown
from orion.runner import investigate


@pytest.mark.parametrize("scenario", list_scenarios())
def test_reference_policy_finds_the_root_cause(scenario):
    r = investigate(scenario, "reference", seed=3, noise=2.0)
    s = score_case(scenario, r.answer)
    assert s["passed"], (scenario, s, r.answer.root_cause)
    assert r.answer.verdict == "verified"
    assert "## Evidence" in to_markdown(r)


def test_loudest_error_baseline_is_fooled_by_noise():
    r = investigate("upgrade-missing-login", "loudest-error")
    assert r.answer.root_cause.service == "carrier-gateway"


def test_engineer_can_override_the_flow():
    asked = []
    r = investigate("duplicate-charge", "reference", ask=lambda k, p: asked.append(p) or "refill")
    assert asked and r.answer.flow == "refill"
