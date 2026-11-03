"""The structured RCA answer. Every claim carries evidence ids from the signed ledger."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Claim(BaseModel):
    statement: str
    service: str | None = None
    evidence: list[str] = Field(default_factory=list)
    status: str = "observed"  # observed | likely | not_established


class RootCause(Claim):
    file: str | None = None
    line: int | None = None


class Fix(BaseModel):
    file: str
    change: str
    evidence: list[str] = Field(default_factory=list)


class Answer(BaseModel):
    ticket: str
    summary: str
    flow: str | None = None
    failure_point: str | None = None
    root_cause: RootCause
    causal_chain: list[Claim] = Field(default_factory=list)
    ruled_out: list[Claim] = Field(default_factory=list)
    fix: Fix | None = None
    open_questions: list[str] = Field(default_factory=list)
    confidence: int = 3  # 1-5, set by the harness, not the policy
    verdict: str = "unverified"  # verified | sent_back | unverified
    critic: dict = Field(default_factory=dict)

    def claims(self) -> list[Claim]:
        return [self.root_cause, *self.causal_chain, *self.ruled_out]

    def text(self) -> str:
        parts = [self.summary, self.root_cause.statement, self.root_cause.file or ""]
        parts += [c.statement for c in self.causal_chain + self.ruled_out]
        if self.fix:
            parts += [self.fix.file, self.fix.change]
        parts += self.open_questions
        return "\n".join(parts)
