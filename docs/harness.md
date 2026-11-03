# The harness

The harness is the part that makes an agent trustworthy enough to point at production. It is the same for the
deterministic reference policy and for an LLM.

## Tool gate (`Harness.call`)

- Unknown tools are refused.
- Budgets: tool calls (default 60), wall time (300 s), tokens (400k for LLM runs).
- Repeat limit: the same tool with the same arguments at most twice (stops loops).
- Every call emits events; refusals are events too, so a policy can recover.

## Evidence ledger

Each tool result becomes `Evidence(id, tool, args, system, summary, content, ts, sig)`. The signature is
HMAC-SHA256 over the record. `Ledger.get` returns nothing for a tampered record, and the verifier treats that as a
missing citation.

## Verifier (`verify.verify`)

- Every claim cites at least one evidence id that exists and verifies.
- Every value quoted in backticks appears in one of the cited records.
- The root cause cites **code** evidence and **runtime** evidence (logs or database).

## Critic (`verify.critic`)

Objections, each from a real investigation failure mode:

| Objection | Failure mode |
|---|---|
| Root cause is a system of record without code | Stopping where the error is *reported* |
| No request traced end to end | Correlation mistaken for causation |
| No baseline comparison | Blaming an error that was always there |
| Root cause matches the loudest service | Fixating on the noisiest signal |
| No fix proposed | Unactionable RCA |

## Confidence

Starts at 5; minus verification problems (up to 2); minus 1 for an uncertain critic, 2 for a disagreeing one; minus 1
when the key error is steady versus the day before. In the evals it is 4.6 on correct answers and 1.8-2.9 on wrong ones.

## Human in the loop

`Harness.ask` puts a question to the engineer (the business flow, with ranked options and reasons). With no engineer
attached (batch, CI) the default is taken and logged as an event. `Harness.steer` queues a message the LLM sees on its next turn.

## LLM-specific pieces

- **Sub-agents**: `delegate(agent, task)` runs a short loop with only that specialist's tools (logs, sql, code, kb).
- **Compaction**: past 80% of the context window, older tool results become one-line stubs that keep their evidence id.
- **Send-back**: a `submit_answer` that fails verification is returned with the problems, once.
- **Gateway**: retries with backoff and `Retry-After`, a circuit breaker per model, fallback to the next model,
  prompt caching on the system prompt and tool list, token accounting.
