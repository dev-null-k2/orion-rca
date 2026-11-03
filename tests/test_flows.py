from orion.estate.builder import KB_DIR
from orion.flows import Catalog
from orion.retrieval import KnowledgeBase


def test_walk_goes_upstream_from_the_failure_point():
    order = [s for s, _ in Catalog().walk("upgrade", "billing-core")]
    assert order[:3] == ["billing-core", "billing-adapter", "order-service"]


def test_frontend_failures_walk_forward():
    order = [s for s, _ in Catalog().walk("profile", "web-storefront")]
    assert order[:3] == ["web-storefront", "api-gateway", "profile-service"]


def test_error_code_owner_beats_keywords():
    svc, why = Catalog().failure_point("the billing page shows BILL-4004", {"BILL-4004": "billing-core"})
    assert svc == "billing-core" and "BILL-4004" in why


def test_three_cases_are_reported():
    cat, kb = Catalog(), KnowledgeBase(KB_DIR)
    past = cat.rank_flows("activations stuck in PENDING_ACTIVATION", kb, incidents=[{"id": "INC-0377", "flows": ["activation"],
                                                                         "signals": ["PENDING_ACTIVATION"]}])
    assert past.case == "past_incident" and past.ranked[0].flow_id == "activation"
    thin = cat.rank_flows("zzz qqq", kb)
    assert thin.case == "kb_thin"
