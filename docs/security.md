# Security model

See [SECURITY.md](../SECURITY.md) for the summary. Details:

- `guard_sql` strips comments, allows one statement, requires `SELECT`/`WITH`, and rejects
  `insert|update|delete|drop|alter|attach|detach|pragma|create|replace|vacuum|reindex`. The connection itself is opened
  with `mode=ro`, so a guard bypass still cannot write (tested).
- `code_read` resolves the path and refuses anything outside the repository root (tested with `../../../etc/passwd`).
- The web server binds to 127.0.0.1. Put it behind your SSO proxy before exposing it.
- Model providers receive tool results. Point Orion at systems whose data you are allowed to send to your model provider,
  or use a local OpenAI-compatible model (`ORION_PROVIDER=openai OPENAI_BASE_URL=http://localhost:11434/v1`).
