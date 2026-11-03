# Adding a connector

A connector is a set of tool functions registered in `orion/tools.py:build_tools`. To point Orion at a real system:

1. Write a function that takes simple JSON arguments and returns `{"summary": str, "content": str, ...}`.
   `content` is what gets signed into the ledger, so include the raw lines or rows a reviewer needs.
2. Guard it: refuse anything that could write. Validate identifiers and limit result sizes.
3. Register it with `ToolSpec(name, description, params, fn, system)`, where `system` is one of
   `logs`, `sql`, `code`, `changes`, `kb`, `ticket` (the verifier uses it to check code + runtime evidence).
4. Add a refusal test and a happy-path test.

Example: an OpenSearch log search keeps the same arguments as `logs_search` (`query`, `service`, `level`, `start`,
`end`, `limit`) and maps them to a `bool` query with a time range; `logs_trace` becomes a term query on the
request-id field sorted by `@timestamp`.
