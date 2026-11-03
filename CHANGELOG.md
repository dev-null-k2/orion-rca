# Changelog

## 0.4.0
- LLM investigator with specialist sub-agents (logs, sql, code, kb), context compaction and one send-back on failed verification.
- Model gateway: Anthropic and OpenAI-compatible providers, retries with Retry-After, circuit breaker, fallback, prompt caching.
- MCP server (`orion mcp`).
- Web UI with live timeline, flow question and clickable evidence.

## 0.3.0
- Critic and 1-5 confidence; evals report confidence when right vs wrong.
- Release gate in CI; ablation (no walk-back) and two baselines.

## 0.2.0
- Flow catalog with three explicit cases; failure point and walk-back order.
- Hybrid KB retrieval (BM25 + dense + RRF) with a retrieval eval.

## 0.1.0
- Harness: tool gate, signed evidence ledger, budgets, read-only guards.
- Synthetic estate "Northwind Mobile" with seven incidents and ground truth.
