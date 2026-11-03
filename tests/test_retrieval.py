from orion.estate.builder import KB_DIR
from orion.retrieval import BM25, KnowledgeBase, chunk_markdown, rrf, tokenize


def test_bm25_prefers_rare_terms():
    docs = [tokenize("billing error code"), tokenize("billing billing billing"), tokenize("idempotency key retry")]
    s = BM25(docs).scores(tokenize("idempotency"))
    assert s.index(max(s)) == 2


def test_rrf_rewards_agreement():
    fused = rrf([[0, 1, 2], [1, 0, 2]], [1.0, 1.0])
    assert fused[0] == fused[1] > fused[2]


def test_chunking_keeps_headings():
    ps = chunk_markdown("p.md", "# Title\nintro\n## Part\nbody text")
    assert [p.heading for p in ps] == ["Title", "Part"]


def test_kb_finds_error_code_page():
    kb = KnowledgeBase(KB_DIR)
    assert kb.pages("what does BILL-4004 mean", k=3)[0] in {"error-codes.md", "flows/upgrade.md"}
