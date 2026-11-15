"""Mini-RAG over kb/*.md with ChromaDB.

Used ONLY to attach one cited explanation to a reply (state["citation"]).
It never decides anything: no permissions, no amounts, no actions. KB text is
synthetic, curated, and treated as data.

Embeddings: a deterministic hashed bag-of-words (no model download, no network,
same results every run). Plenty for 8 short docs; swap for Sarvam embeddings later.
"""
import hashlib
import math
import re
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

KB_DIR = Path(__file__).resolve().parents[1] / "kb"
DIM = 256
_WORD = re.compile(r"[a-z_]{3,}")


def embed(text: str) -> list[float]:
    v = [0.0] * DIM
    for w in _WORD.findall(text.lower()):
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 8) % 2 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _load_docs() -> list[dict]:
    docs = []
    for p in sorted(KB_DIR.glob("*.md")):
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        title = lines[0].lstrip("# ").strip()
        tags = lines[1].removeprefix("tags:").strip() if lines[1].startswith("tags:") else ""
        body = " ".join(l.strip() for l in lines[2:] if l.strip())
        docs.append({"id": p.name, "title": title, "tags": tags, "body": body})
    return docs


@lru_cache
def _collection():
    client = chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False))
    col = client.get_or_create_collection("merchant_kb",embedding_function=None, metadata={"hnsw:space": "cosine"})
    docs = _load_docs()
    col.add(ids=[d["id"] for d in docs],
             embeddings=[embed(f"{d['title']} {d['tags']} {d['tags']} {d['body']}") for d in docs],
             documents=[d["body"] for d in docs],
             metadatas=[{"title": d["title"]} for d in docs])
    return col


def cite(query: str) -> dict | None:
    """Best matching doc as {"doc", "title", "text"} (first sentence), or None."""
    try:
        r = _collection().query(query_embeddings=[embed(query)], n_results=1)
        if not r["ids"] or not r["ids"][0]:
            return None
        body = r["documents"][0][0]
        first = re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0]
        return {"doc": f"kb/{r['ids'][0][0]}", "title": r["metadatas"][0][0]["title"], "text": first}
    except Exception:
        return None
