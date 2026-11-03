# Roadmap

**Now**
- Score the LLM policy in the eval table: Claude, GPT and a local model, 3 trials each, same incidents and baselines.
- Held-out incidents written by contributors other than the author, so the reference policy is tested on cases it never saw.

**Next**
- Connectors behind the same tool gate: OpenSearch/Elasticsearch, Postgres, GitHub/GitLab, Jira.
- A world model: store the service hops Orion observes in traces and use them to check causal direction.
- Pass^k with an LLM critic as a second opinion, and calibration plots for the confidence score.

**Later**
- Multi-user server mode (auth, per-user budgets, shared case memory).
- Auto-drafted postmortems and KB pages from verified RCAs, approved by a human before they land.
