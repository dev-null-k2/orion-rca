# Contributing

Thanks for helping. Orion values evidence over opinions, in code reviews too.

## Setup

```bash
pip install -e ".[dev]"
pytest -q
orion eval
```

## Ground rules

- **Read-only, always.** No tool may write to a system it investigates. New tools need a guard and a test that the guard refuses writes.
- **Every claim cites evidence.** If you change how answers are built, `orion/verify.py` must still pass.
- **Numbers move only with the report.** If a change moves an eval number, include the before/after table in the PR.
- **Add incidents, not special cases.** To teach Orion something new, add a scenario under `orion/estate/scenarios/`
  with ground truth and decoys. Never put scenario names, ids or answers in the policy code.

## Adding an incident

1. Copy a file in `orion/estate/scenarios/`.
2. Write the ticket the way a customer-support agent would.
3. Add events: one failing request (with a `corr` id), ideally one that worked, and decoys.
4. Seed the defect in `orion/estate/repos/` and the rows in `db:`.
5. Fill `truth`: root service, root files, facts the RCA must contain, forbidden claims.
6. Run `orion investigate <id>` and `orion eval`.

## Style

`ruff check orion tests`. Small functions, type hints, docstrings that say *why*.
