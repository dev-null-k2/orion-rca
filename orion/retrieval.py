"""Hybrid knowledge-base search: BM25 + dense vectors, fused with reciprocal rank fusion (RRF).

Dense vectors come from sentence-transformers (BAAI/bge-small-en-v1.5) when it is installed, otherwise from a
deterministic hashed character-n-gram embedder so the project runs offline and in CI with zero downloads.
Pages are chunked on Markdown headings into passages; search returns passages with their page and heading.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9][a-z0-9_\-\.]*")
STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "be", "it", "this", "that", "with", "as", "by", "at", "from", "not", "no", "do", "does"}


def tokenize(text: str) -> list[str]:
    return [t.strip(".-") for t in TOKEN.findall(text.lower()) if t not in STOP and len(t.strip(".-")) > 1]


@dataclass
class Passage:
    page: str
    heading: str
    text: str

    @property
    def ref(self) -> str:
        return f"{self.page}#{self.heading}"


def chunk_markdown(page: str, text: str, max_words: int = 160) -> list[Passage]:
    passages, heading, buf = [], page, []

    def flush():
        if buf:
            words = " ".join(buf).split()
            for i in range(0, len(words), max_words):
                passages.append(Passage(page, heading, " ".join(words[i:i + max_words])))
            buf.clear()

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
            buf.append(heading)
        elif line.strip():
            buf.append(line.strip())
    flush()
    return passages


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avgdl = sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, doc in zip(self.tf, self.docs, strict=False):
            s = 0.0
            for q in query:
                if q in tf:
                    f = tf[q]
                    s += self.idf[q] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl))
            out.append(s)
        return out


class HashEmbedder:
    """Character 3-5 gram feature hashing into 384 dims, L2-normalised. Offline stand-in for a real model."""

    name = "hash-ngram-384"
    dim = 384

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in tokenize(text):
                padded = f"#{tok}#"
                for n in (3, 4, 5):
                    for i in range(len(padded) - n + 1):
                        h = int(hashlib.blake2b(padded[i:i + n].encode(), digest_size=4).hexdigest(), 16)
                        v[h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vecs.append([x / norm for x in v])
        return vecs


def default_embedder():
    try:  # pragma: no cover - optional dependency
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("BAAI/bge-small-en-v1.5")

        class _ST:
            name, dim = "bge-small-en-v1.5", 384

            def encode(self, texts):
                return model.encode(texts, normalize_embeddings=True).tolist()

        return _ST()
    except Exception:
        return HashEmbedder()


def rrf(rankings: list[list[int]], weights: list[float], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking, w in zip(rankings, weights, strict=False):
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + w / (k + rank + 1)
    return fused


class KnowledgeBase:
    def __init__(self, kb_dir: Path, embedder=None, bm25_weight: float = 1.0, dense_weight: float = 1.0):
        self.passages: list[Passage] = []
        for path in sorted(kb_dir.rglob("*.md")):
            self.passages += chunk_markdown(str(path.relative_to(kb_dir)), path.read_text())
        self.bm25 = BM25([tokenize(p.text) for p in self.passages])
        self.embedder = embedder or HashEmbedder()
        self.vectors = self.embedder.encode([p.text for p in self.passages])
        self.weights = (bm25_weight, dense_weight)

    def search(self, query: str, k: int = 5) -> list[tuple[Passage, float]]:
        q_tokens = tokenize(query)
        bm = self.bm25.scores(q_tokens)
        bm_rank = [i for i in sorted(range(len(bm)), key=lambda i: -bm[i]) if bm[i] > 0]
        qv = self.embedder.encode([query])[0]
        dense = [sum(a * b for a, b in zip(qv, v, strict=False)) for v in self.vectors]
        dense_rank = sorted(range(len(dense)), key=lambda i: -dense[i])[:50]
        fused = rrf([bm_rank, dense_rank], list(self.weights))
        best = sorted(fused, key=lambda i: -fused[i])[:k]
        return [(self.passages[i], round(fused[i], 5)) for i in best]

    def pages(self, query: str, k: int = 5) -> list[str]:
        seen: list[str] = []
        for p, _ in self.search(query, k=k * 4):
            if p.page not in seen:
                seen.append(p.page)
        return seen[:k]
