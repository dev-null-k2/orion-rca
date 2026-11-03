"""Builds a self-contained, synthetic production estate for one incident scenario.

An estate is what Orion investigates: a log store, a read-only SQL database, source repos, a knowledge base,
a change history and a ticket. Everything is generated from the YAML scenario plus seeded background noise,
so every run (and every eval) is reproducible.
"""
from __future__ import annotations

import json
import random
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ESTATE_DIR = Path(__file__).parent
SCENARIO_DIR = ESTATE_DIR / "scenarios"
REPO_DIR = ESTATE_DIR / "repos"
KB_DIR = ESTATE_DIR / "kb"

SCHEMA = """
CREATE TABLE accounts (id TEXT PRIMARY KEY, brand TEXT, status TEXT, address_line1 TEXT);
CREATE TABLE lines (msisdn TEXT PRIMARY KEY, account_id TEXT, device_id TEXT, status TEXT, serial TEXT);
CREATE TABLE devices (id TEXT PRIMARY KEY, account_id TEXT, status TEXT, msisdn TEXT);
CREATE TABLE orders (id TEXT PRIMARY KEY, account_id TEXT, type TEXT, status TEXT, created TEXT);
CREATE TABLE service_events (tx_id INTEGER PRIMARY KEY, device_id TEXT, action TEXT, tx_date TEXT,
                                result TEXT, created TEXT);
CREATE UNIQUE INDEX ux_service_event ON service_events (device_id, action, tx_date);
CREATE TABLE payments (id TEXT PRIMARY KEY, order_id TEXT, amount_cents INTEGER, processor_ref TEXT,
                       status TEXT, created TEXT);
CREATE TABLE promotions (code TEXT PRIMARY KEY, starts_at TEXT, ends_at TEXT, note TEXT);
"""

# Background services that log all day. carrier-gateway is deliberately the loudest: its rate-limit warnings
# are harmless and exist to punish "count the errors" investigation.
HEARTBEAT_SERVICES = ["web-storefront", "api-gateway", "order-service", "billing-adapter", "activation-service",
                      "profile-service", "payment-service", "catalog-service", "notification-service"]


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def fmt_ts(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class LogRecord:
    ts: str
    service: str
    level: str
    msg: str
    corr: str = ""
    code: str = ""

    def text(self) -> str:
        return f"{self.ts} {self.level} [{self.service}] {self.code + ' ' if self.code else ''}{self.msg}"


@dataclass
class Ticket:
    key: str
    summary: str
    description: str
    created: str

    def text(self) -> str:
        return f"{self.key}: {self.summary}\n\n{self.description}"


@dataclass
class Estate:
    scenario: dict
    ticket: Ticket
    logs: list[LogRecord]
    db_path: Path
    repo_dir: Path = REPO_DIR
    kb_dir: Path = KB_DIR
    changes: list[dict] = field(default_factory=list)

    @property
    def window(self) -> tuple[datetime, datetime]:
        start, end = self.scenario["window"]
        return parse_ts(start), parse_ts(end)

    def connect_readonly(self) -> sqlite3.Connection:
        """SQLite opened in read-only URI mode: writes fail at the driver, not just in our guard."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def list_scenarios() -> list[str]:
    return sorted(yaml.safe_load(p.read_text())["id"] for p in SCENARIO_DIR.glob("*.yaml"))


def load_scenario(scenario_id: str) -> dict:
    for path in SCENARIO_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text())
        if data["id"] == scenario_id:
            return data
    raise KeyError(f"unknown scenario {scenario_id!r}; known: {', '.join(list_scenarios())}")


def _noise(scenario: dict, rng: random.Random, noise_level: float) -> list[LogRecord]:
    start, end = (parse_ts(x) for x in scenario["window"])
    start -= timedelta(days=1)  # the day before, for "is this new?" comparisons
    out: list[LogRecord] = []
    t = start
    n = 0
    while t < end:
        n += 1
        # Loud, harmless carrier throttling: several per minute.
        for _ in range(int(3 * noise_level) + 1):
            out.append(LogRecord(fmt_ts(t + timedelta(seconds=rng.uniform(0, 59))), "carrier-gateway", "WARN",
                                 f"RATE_LIMITED host network retry_after_ms={rng.randint(50, 900)}",
                                 corr=f"n-{rng.getrandbits(32):08x}", code="CAR-0429"))
        svc = HEARTBEAT_SERVICES[n % len(HEARTBEAT_SERVICES)]
        out.append(LogRecord(fmt_ts(t), svc, "INFO", f"health ok latency_ms={rng.randint(3, 40)}",
                             corr=f"n-{rng.getrandbits(32):08x}"))
        if n % 9 == 0:  # unrelated, intermittent errors elsewhere
            out.append(LogRecord(fmt_ts(t + timedelta(seconds=7)), "catalog-service", "ERROR",
                                 "cache refresh failed: price feed slow, serving stale prices",
                                 corr=f"n-{rng.getrandbits(32):08x}", code="CAT-9001"))
        t += timedelta(minutes=1)

    rep = scenario.get("repeat_errors")
    if rep:
        after = parse_ts(rep["after"]) if rep.get("after") else None
        every = timedelta(seconds=3600 / rep["per_hour"])
        t = start
        while t < end:
            if after is None or t >= after:
                out.append(LogRecord(fmt_ts(t + timedelta(seconds=rng.uniform(0, 5))), rep["svc"], "ERROR",
                                     rep["msg"], corr=f"r-{rng.getrandbits(32):08x}", code=rep["code"]))
            t += every
    return out


def build_estate(scenario_id: str, *, seed: int = 7, noise_level: float = 1.0, workdir: Path | None = None) -> Estate:
    scenario = load_scenario(scenario_id)
    rng = random.Random(f"{scenario_id}:{seed}")
    logs = [LogRecord(e["t"], e["svc"], e["lvl"], e["msg"], corr=e.get("corr", ""), code=e.get("code", ""))
            for e in scenario.get("events", [])]
    logs += _noise(scenario, rng, noise_level)
    logs.sort(key=lambda r: r.ts)

    workdir = workdir or Path(tempfile.mkdtemp(prefix=f"orion-{scenario_id}-"))
    db_path = workdir / "subscriber.db"
    db_path.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for table, rows in (scenario.get("db") or {}).items():
        for row in rows:
            cols = ", ".join(row)
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    conn.commit()
    conn.close()

    t = scenario["ticket"]
    ticket = Ticket(t["key"], t["summary"], t["description"].strip(), t["created"])
    changes = yaml.safe_load((REPO_DIR / "CHANGES.yaml").read_text())
    (workdir / "logs.jsonl").write_text("\n".join(json.dumps(r.__dict__) for r in logs))
    return Estate(scenario=scenario, ticket=ticket, logs=logs, db_path=db_path, changes=changes)
