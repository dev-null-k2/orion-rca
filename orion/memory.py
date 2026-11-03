"""Case memory: resolved RCAs stored in SQLite FTS5 and recalled as *leads* (never as proof) for new tickets."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SEED_CASES = [
    {"id": "INC-0412", "summary": "Refill failed with BILL-2100 after a duplicate balance update",
     "root_cause": "billing-adapter retried a balance update without an idempotency key",
     "services": ["billing-adapter", "billing-core"], "flows": ["refill", "payment"],
     "signals": ["BILL-2100", "twice", "idempotency"]},
    {"id": "INC-0377", "summary": "Activations stuck in PENDING_ACTIVATION after a carrier outage",
     "root_cause": "carrier-gateway outage; activations stayed pending until retried",
     "services": ["carrier-gateway", "activation-service"], "flows": ["activation"],
     "signals": ["PENDING_ACTIVATION", "stuck", "carrier outage"]},
]


class CaseStore:
    def __init__(self, path: Path | str = ":memory:", seed: bool = True):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS cases USING fts5(id, summary, root_cause, body)")
        if seed and not self.db.execute("SELECT count(*) FROM cases").fetchone()[0]:
            for case in SEED_CASES:
                self.add(case)

    def add(self, case: dict) -> None:
        self.db.execute("INSERT INTO cases VALUES (?, ?, ?, ?)",
                        (case["id"], case["summary"], case["root_cause"], json.dumps(case)))
        self.db.commit()

    def all(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT body FROM cases")]

    def recall(self, text: str, k: int = 2) -> list[dict]:
        terms = [t for t in "".join(c if c.isalnum() or c == "-" else " " for c in text).split() if len(t) > 3]
        if not terms:
            return []
        query = " OR ".join(f'"{t}"' for t in terms[:40])
        rows = self.db.execute("SELECT body FROM cases WHERE cases MATCH ? ORDER BY rank LIMIT ?", (query, k))
        return [json.loads(r[0]) for r in rows]
