"""Model gateway: one interface over Anthropic and any OpenAI-compatible endpoint (OpenAI, Gemini, vLLM, Ollama),
with retries, a circuit breaker, model fallback, prompt caching and token accounting.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    usage: dict = field(default_factory=dict)
    model: str = ""


class ModelError(RuntimeError):
    pass


class CircuitOpen(ModelError):
    pass


class Breaker:
    def __init__(self, trip_after: int = 3, cooldown: float = 30.0):
        self.trip_after, self.cooldown = trip_after, cooldown
        self.failures, self.opened_at = 0, 0.0

    def allow(self) -> bool:
        return self.failures < self.trip_after or time.monotonic() - self.opened_at > self.cooldown

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
        else:
            self.failures += 1
            if self.failures >= self.trip_after:
                self.opened_at = time.monotonic()


class Provider:
    def complete(self, system: str, messages: list[dict], tools: list[dict], model: str, max_tokens: int) -> Turn:
        raise NotImplementedError


class AnthropicProvider(Provider):
    """Messages API with tool use. The system prompt and tool list are marked for prompt caching."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.anthropic.com", client=None):
        self.key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = client or httpx.Client(base_url=base_url, timeout=120)

    def complete(self, system, messages, tools, model, max_tokens):
        tools = [dict(t) for t in tools]
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        body = {"model": model, "max_tokens": max_tokens, "messages": messages, "tools": tools,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
        r = self.client.post("/v1/messages", json=body,
                             headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        if r.status_code >= 400:
            raise ModelError(f"{r.status_code}: {r.text[:300]}") if r.status_code != 429 else _RateLimited(r)
        d = r.json()
        text = "".join(b.get("text", "") for b in d["content"] if b["type"] == "text")
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in d["content"] if b["type"] == "tool_use"]
        return Turn(text, calls, d.get("usage", {}), d.get("model", model))


class OpenAICompatProvider(Provider):
    def __init__(self, api_key: str | None = None, base_url: str | None = None, client=None):
        self.key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.client = client or httpx.Client(base_url=base_url or os.environ.get("OPENAI_BASE_URL",
                                                                                 "https://api.openai.com/v1"), timeout=120)

    def complete(self, system, messages, tools, model, max_tokens):
        oa_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                      "parameters": t["input_schema"]}} for t in tools]
        body = {"model": model, "max_tokens": max_tokens, "tools": oa_tools,
                "messages": [{"role": "system", "content": system}] + to_openai(messages)}
        r = self.client.post("/chat/completions", json=body, headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code >= 400:
            raise ModelError(f"{r.status_code}: {r.text[:300]}") if r.status_code != 429 else _RateLimited(r)
        d = r.json()
        msg = d["choices"][0]["message"]
        calls = [ToolCall(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
                 for c in msg.get("tool_calls") or []]
        return Turn(msg.get("content") or "", calls, d.get("usage", {}), d.get("model", model))


class _RateLimited(ModelError):
    def __init__(self, response):
        super().__init__(f"429: {response.text[:200]}")
        self.retry_after = float(response.headers.get("retry-after", "0") or 0)


def to_openai(messages: list[dict]) -> list[dict]:
    """Convert Anthropic-shaped history (content blocks) to OpenAI chat messages."""
    out = []
    for m in messages:
        if isinstance(m["content"], str):
            out.append(m)
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in m["content"] if b["type"] == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                     for b in m["content"] if b["type"] == "tool_use"]
            out.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
        else:
            for b in m["content"]:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                elif b["type"] == "text":
                    out.append({"role": "user", "content": b["text"]})
    return out


class Gateway:
    """Retries with exponential backoff and jitter (honouring Retry-After), a breaker per model,
    and fallback to the next model in the list when one keeps failing."""

    def __init__(self, provider: Provider, models: list[str], max_retries: int = 3, sleep=time.sleep):
        self.provider, self.models, self.max_retries, self.sleep = provider, models, max_retries, sleep
        self.breakers = {m: Breaker() for m in models}
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "calls": 0}

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 4096) -> Turn:
        last: Exception | None = None
        for model in self.models:
            breaker = self.breakers[model]
            if not breaker.allow():
                continue
            for attempt in range(self.max_retries + 1):
                try:
                    turn = self.provider.complete(system, messages, tools, model, max_tokens)
                    breaker.record(True)
                    self.usage["calls"] += 1
                    u = turn.usage
                    self.usage["input_tokens"] += int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
                    self.usage["output_tokens"] += int(u.get("output_tokens") or u.get("completion_tokens") or 0)
                    self.usage["cache_read_input_tokens"] += int(u.get("cache_read_input_tokens") or 0)
                    return turn
                except _RateLimited as exc:
                    last = exc
                    self.sleep(min(exc.retry_after or 2 ** attempt, 60))
                except (ModelError, httpx.HTTPError) as exc:
                    last = exc
                    breaker.record(False)
                    if not breaker.allow():
                        break
                    self.sleep(min(2 ** attempt + random.random(), 30))
        raise CircuitOpen(f"all models failed: {last}")

    @staticmethod
    def from_env(name: str = "llm") -> Gateway:
        provider = os.environ.get("ORION_PROVIDER", "anthropic")
        models = [m for m in os.environ.get("ORION_MODELS", "claude-sonnet-4-5").split(",") if m]
        if provider == "anthropic":
            return Gateway(AnthropicProvider(), models)
        return Gateway(OpenAICompatProvider(), models)
