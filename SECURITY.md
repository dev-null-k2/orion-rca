# Security

Orion is designed to point at production systems, so its safety model is part of the product.

- **Read-only by construction.** SQL passes a SELECT/WITH-only guard *and* runs on a read-only connection.
  Log, code and ticket tools have no write path. File reads cannot leave the repository root.
- **Budgets.** Every run has limits on tool calls, wall time and tokens, plus a repeat limit per identical call.
- **Evidence integrity.** Ledger records are HMAC-SHA256 signed with a per-process key (or `ORION_LEDGER_KEY`);
  a modified record is rejected by the verifier.
- **No secrets in prompts.** Connectors read credentials from the environment; tool results never include them.
- **Local by default.** The web server binds to 127.0.0.1.

Found a problem? Please open a private security advisory on GitHub rather than a public issue.
