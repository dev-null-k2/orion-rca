# Notes for coding agents

- Run `pytest -q` and `orion eval` before proposing a change; the eval gate must pass.
- Never add write paths to tools. Every new tool needs a guard and a refusal test.
- Never special-case a scenario id, ticket key or answer in policy code; add a scenario instead.
- The reference policy and the LLM policy must keep using the same harness, ledger and verifier.
- Keep README numbers in sync with `results/eval-report.json` (`python scripts/make_charts.py` redraws the chart).
