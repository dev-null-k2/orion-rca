"""Business flows, the service dependency graph, and the "work backwards from the failure" walk.

Orion does not search every service. It ranks the business flows a ticket could belong to, finds where the
failure shows (the failure point), then orders the flow's services by distance *upstream* from that point:
the failing system, its adapters, the services that call them, towards the front end. A front-end failure is
walked forward from the page instead.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .retrieval import KnowledgeBase, tokenize

CATALOG = Path(__file__).parent / "estate" / "flows.yaml"


@dataclass
class FlowRank:
    flow_id: str
    name: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class FlowAssessment:
    case: str  # "past_incident" | "kb_ranking" | "kb_thin"
    ranked: list[FlowRank]
    pick: str | None
    message: str


class Catalog:
    def __init__(self, path: Path = CATALOG):
        data = yaml.safe_load(path.read_text())
        self.services: dict[str, dict] = data["services"]
        self.calls: list[tuple[str, str]] = [tuple(c) for c in data["calls"]]
        self.flows: dict[str, dict] = data["flows"]
        self.failure_points: dict[str, list[str]] = data["failure_points"]
        self.callers: dict[str, set[str]] = {s: set() for s in self.services}
        self.callees: dict[str, set[str]] = {s: set() for s in self.services}
        for a, b in self.calls:
            self.callers[b].add(a)
            self.callees[a].add(b)

    # ---- flow ranking -------------------------------------------------------------------------------------
    def rank_flows(self, ticket_text: str, kb: KnowledgeBase, incidents: list[dict] | None = None) -> FlowAssessment:
        text = ticket_text.lower()
        tokens = set(tokenize(ticket_text))
        ranks: dict[str, FlowRank] = {fid: FlowRank(fid, f["name"], 0.0) for fid, f in self.flows.items()}

        matched_incident = None
        for inc in incidents or []:
            shared = [s for s in inc.get("signals", []) if s.lower() in text]
            if shared:
                matched_incident = inc
                for fid in inc["flows"]:
                    ranks[fid].score += 3.0
                    ranks[fid].reasons.append(f"similar past incident {inc['id']} ({', '.join(shared)})")

        for fid, f in self.flows.items():
            hits = [w for w in f["words"] if (w.lower() in text if " " in w else w.lower() in tokens)]
            if hits:
                ranks[fid].score += 1.0 * len(hits)
                ranks[fid].reasons.append("ticket says " + ", ".join(f'"{h}"' for h in hits[:3]))
        for page in kb.pages(ticket_text, k=3):
            for fid, f in self.flows.items():
                if page in f["kb"]:
                    ranks[fid].score += 1.5
                    ranks[fid].reasons.append(f"KB search returned {page}")

        ranked = sorted((r for r in ranks.values() if r.score > 0), key=lambda r: -r.score)
        if not ranked:
            return FlowAssessment("kb_thin", [], None, "The KB has nothing that matches; this may be new.")
        clear = len(ranked) == 1 or ranked[0].score >= 1.5 * ranked[1].score
        pick = ranked[0].flow_id if clear else None
        if matched_incident:
            case, msg = "past_incident", f"This looks like past incident {matched_incident['id']}."
        elif ranked[0].score >= 2:
            case, msg = "kb_ranking", "No similar past incident; this ranking comes from what the KB documents."
        else:
            case, msg = "kb_thin", "The KB has little that matches; these are the closest flows."
        return FlowAssessment(case, ranked[:3], pick, msg)

    # ---- failure point and walk ---------------------------------------------------------------------------
    def failure_point(self, ticket_text: str, owner_of_code: dict[str, str] | None = None) -> tuple[str, str]:
        """Return (service, reason). Error-code owners and stack frames beat keyword matches."""
        for code, svc in (owner_of_code or {}).items():
            if code in ticket_text:
                return svc, f"error {code} is raised by {svc}"
        frame = re.search(r"at ([\w.]+)\.(\w+)\((\w+)\.java:(\d+)\)", ticket_text)
        if frame:
            pkg = frame.group(1).lower()
            for svc in self.services:
                if svc.split("-")[0] in pkg:
                    return svc, f"stack frame {frame.group(3)}.java:{frame.group(4)} belongs to {svc}"
        text = ticket_text.lower()
        best = max(self.failure_points, key=lambda s: sum(t.lower() in text for t in self.failure_points[s]))
        return best, f"ticket mentions {', '.join(t for t in self.failure_points[best] if t.lower() in text) or 'nothing specific'}"

    def walk(self, flow_id: str | None, start: str, batch: int = 10) -> list[tuple[str, int]]:
        """Services in walk order with their hop distance from the failure point."""
        allowed = set(self.flows[flow_id]["services"]) | {start} if flow_id else set(self.services)
        forward = self.services[start]["tier"] == "frontend"
        nxt = self.callees if forward else self.callers
        seen, order, q = {start}, [(start, 0)], deque([(start, 0)])
        while q:
            svc, d = q.popleft()
            for other in sorted(nxt[svc]):
                if other not in seen and other in allowed:
                    seen.add(other)
                    order.append((other, d + 1))
                    q.append((other, d + 1))
        # Siblings the failing system calls (e.g. the DB under a service) go last, still in scope.
        for svc in sorted(allowed - seen):
            order.append((svc, 99))
        return order[:batch]
