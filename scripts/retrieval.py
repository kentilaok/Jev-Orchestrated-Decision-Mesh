"""Arsenal V1 Phase D: hybrid retrieval bound to source IDs and hashes.

Local tier (required, stdlib): SQLite FTS5/BM25 over bounded chunks, with
namespace and access-group payload filters. Optional dense tier: FastEmbed/ONNX
CPU embeddings cached by content hash. Rankings fuse with reciprocal-rank
fusion, then an optional reranker: local cross-encoder first, hosted fallback
(Cohere or Voyage) only when explicitly configured. Managed Qdrant is an
optional durable backend reached over its REST API.

Every result carries chunk ID, document ID, and content hash, and converts to a
bounded CIDM source (<= 1200 characters). Scores are ranking evidence only;
they never authorize an action. Retrieved text is evidence, not instructions.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import math
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib import request as urlrequest

from capability_permits import PermitAuthority, canonical, digest, require

CHUNK_LIMIT = 1100
SOURCE_LIMIT = 1200
DEFAULT_PATTERNS = ("*.md", "*.txt", "*.rst", "*.py", "*.json", "*.yaml", "*.yml", "*.toml", "*.lua", "*.luau")


def chunk_text(text: str, *, max_chars: int = CHUNK_LIMIT, overlap: int = 120) -> list[str]:
    """Paragraph-aware chunks no longer than max_chars, with a small overlap."""
    require(isinstance(text, str) and 200 <= max_chars <= SOURCE_LIMIT and 0 <= overlap < max_chars // 2,
            "invalid_chunking")
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        while len(paragraph) > max_chars:
            cut = paragraph.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            pieces.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if paragraph:
            pieces.append(paragraph)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = (current + "\n\n" + piece).strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        chunks.append(current)
        tail = current[-overlap:] if overlap else ""
        current = (tail + "\n\n" + piece).strip() if tail and len(tail) + len(piece) + 2 <= max_chars else piece
    if current:
        chunks.append(current)
    return chunks


def rrf(rankings: dict[str, list[str]], *, k: int = 60) -> list[tuple[str, float, dict]]:
    scores: dict[str, float] = {}
    ranks: dict[str, dict] = {}
    for name, ids in rankings.items():
        for rank, item in enumerate(ids, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(item, {})[name] = rank
    return sorted(((i, round(s, 8), ranks[i]) for i, s in scores.items()), key=lambda x: -x[1])


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    nl, nr = math.sqrt(sum(a * a for a in left)), math.sqrt(sum(b * b for b in right))
    return dot / (nl * nr) if nl and nr else 0.0


def fastembed_embedder(model_id: str) -> Callable[[list[str], str], list[list[float]]]:
    """Lazy FastEmbed CPU embedder; `kind` is 'passage' or 'query'."""
    try:
        from fastembed import TextEmbedding
    except ImportError as error:
        raise RuntimeError("fastembed_not_installed; pip install -r requirements-arsenal-semantic.txt") from error
    model = TextEmbedding(model_name=model_id, lazy_load=True)

    def embed(texts: list[str], kind: str) -> list[list[float]]:
        vectors = model.query_embed(texts) if kind == "query" else model.passage_embed(texts)
        return [[float(x) for x in vector] for vector in vectors]
    return embed


class LocalHybridIndex:
    def __init__(self, db_path: Path):
        self.path = Path(db_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS chunks(chunk_id TEXT PRIMARY KEY, namespace TEXT NOT NULL,
          doc_id TEXT NOT NULL, ordinal INTEGER NOT NULL, title TEXT, text TEXT NOT NULL,
          content_hash TEXT NOT NULL, doc_hash TEXT NOT NULL, metadata TEXT, access TEXT);
        CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(namespace, doc_id);
        CREATE TABLE IF NOT EXISTS vectors(chunk_id TEXT, model_id TEXT, content_hash TEXT,
          vector TEXT, PRIMARY KEY(chunk_id, model_id));
        """)
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING "
                            "fts5(chunk_id UNINDEXED, namespace UNINDEXED, title, text)")
            self.fts5 = True
        except sqlite3.OperationalError:
            self.fts5 = False
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def add_document(self, namespace: str, doc_id: str, text: str, *, title: str = "",
                     metadata: dict | None = None, access: list[str] | None = None) -> list[str]:
        require(isinstance(namespace, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", namespace), "invalid_namespace")
        require(isinstance(doc_id, str) and 0 < len(doc_id) <= 512, "invalid_doc_id")
        require(access is None or (isinstance(access, list) and all(isinstance(a, str) for a in access)),
                "invalid_access_groups")
        doc_hash = digest(text)
        existing = self.db.execute("SELECT doc_hash FROM chunks WHERE namespace=? AND doc_id=? LIMIT 1",
                                   (namespace, doc_id)).fetchone()
        if existing and existing["doc_hash"] == doc_hash:
            return [r["chunk_id"] for r in self.db.execute(
                "SELECT chunk_id FROM chunks WHERE namespace=? AND doc_id=? ORDER BY ordinal", (namespace, doc_id))]
        chunks = chunk_text(text)
        ids = []
        with self.db:
            old = [r["chunk_id"] for r in self.db.execute(
                "SELECT chunk_id FROM chunks WHERE namespace=? AND doc_id=?", (namespace, doc_id))]
            for chunk_id in old:
                self.db.execute("DELETE FROM vectors WHERE chunk_id=?", (chunk_id,))
                if self.fts5:
                    self.db.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (chunk_id,))
            self.db.execute("DELETE FROM chunks WHERE namespace=? AND doc_id=?", (namespace, doc_id))
            for ordinal, chunk in enumerate(chunks):
                chunk_id = "kb-" + digest([namespace, doc_id, ordinal, digest(chunk)])[:16]
                ids.append(chunk_id)
                self.db.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (chunk_id, namespace, doc_id, ordinal, title[:120], chunk, digest(chunk),
                                 doc_hash, canonical(metadata or {}), canonical(access or [])))
                if self.fts5:
                    self.db.execute("INSERT INTO chunks_fts VALUES(?,?,?,?)", (chunk_id, namespace, title, chunk))
        return ids

    def ingest_path(self, namespace: str, root: Path, *, patterns=DEFAULT_PATTERNS, max_files: int = 500,
                    max_file_bytes: int = 1_000_000, access: list[str] | None = None) -> dict:
        root = Path(root).expanduser().resolve()
        require(root.is_dir(), "ingest_root_not_found")
        skipped = {"node_modules", ".git", "__pycache__", ".venv", "venv", "runs"}
        files, added, errors = [], 0, []
        for path in sorted(root.rglob("*")):
            if any(part in skipped for part in path.relative_to(root).parts) or not path.is_file():
                continue
            if not any(fnmatch.fnmatch(path.name, p) for p in patterns):
                continue
            if path.is_symlink() or path.stat().st_size > max_file_bytes:
                errors.append({"path": str(path), "error": "skipped_symlink_or_size"})
                continue
            files.append(path)
            if len(files) > max_files:
                raise ValueError("ingest_file_limit_exceeded")
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError) as error:
                errors.append({"path": str(path), "error": type(error).__name__})
                continue
            rel = path.relative_to(root).as_posix()
            added += len(self.add_document(namespace, rel, text, title=rel,
                                           metadata={"path": rel}, access=access))
        return {"namespace": namespace, "files": len(files), "chunks": added, "errors": errors}

    def _visible(self, row, access_groups) -> bool:
        groups = json.loads(row["access"] or "[]")
        return not groups or bool(access_groups and set(groups) & set(access_groups))

    def lexical(self, namespace: str, query: str, *, k: int = 30, access_groups=None) -> list[str]:
        terms = list(dict.fromkeys(t.lower() for t in re.findall(r"[A-Za-z0-9_]{2,}", query)))[:24]
        if not terms:
            return []
        if self.fts5:
            match = " OR ".join('"' + t + '"' for t in terms)
            try:
                rows = self.db.execute(
                    "SELECT c.* FROM chunks_fts f JOIN chunks c ON c.chunk_id=f.chunk_id "
                    "WHERE chunks_fts MATCH ? AND f.namespace=? ORDER BY bm25(chunks_fts) LIMIT ?",
                    (match, namespace, k * 3)).fetchall()
            except sqlite3.OperationalError:
                rows = []
        else:
            count = self.db.execute("SELECT COUNT(*) FROM chunks WHERE namespace=?", (namespace,)).fetchone()[0]
            require(count <= 5000, "fts5_required_for_large_lexical_index")
            rows = [r for r in self.db.execute("SELECT * FROM chunks WHERE namespace=?", (namespace,))
                    if any(t in r["text"].lower() for t in terms)]
        return [r["chunk_id"] for r in rows if self._visible(r, access_groups)][:k]

    def build_vectors(self, model_id: str, embedder: Callable, *, namespace: str | None = None,
                      batch: int = 32) -> dict:
        rows = self.db.execute(
            "SELECT c.chunk_id, c.text, c.content_hash, v.content_hash AS vhash FROM chunks c "
            "LEFT JOIN vectors v ON v.chunk_id=c.chunk_id AND v.model_id=? "
            + ("WHERE c.namespace=?" if namespace else ""),
            (model_id, namespace) if namespace else (model_id,)).fetchall()
        stale = [r for r in rows if r["vhash"] != r["content_hash"]]
        for start in range(0, len(stale), batch):
            part = stale[start:start + batch]
            vectors = embedder([r["text"] for r in part], "passage")
            require(len(vectors) == len(part), "embedding_count_mismatch")
            with self.db:
                for row, vector in zip(part, vectors):
                    self.db.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)",
                                    (row["chunk_id"], model_id, row["content_hash"], json.dumps(vector)))
        return {"model_id": model_id, "chunks": len(rows), "embedded": len(stale), "cached": len(rows) - len(stale)}

    def dense(self, namespace: str, query: str, *, model_id: str, embedder: Callable, k: int = 30,
              access_groups=None) -> list[str]:
        vector = embedder([query], "query")[0]
        rows = self.db.execute(
            "SELECT c.*, v.vector FROM chunks c JOIN vectors v ON v.chunk_id=c.chunk_id "
            "WHERE c.namespace=? AND v.model_id=? AND v.content_hash=c.content_hash",
            (namespace, model_id)).fetchall()
        scored = sorted(((_cosine(vector, json.loads(r["vector"])), r) for r in rows
                         if self._visible(r, access_groups)), key=lambda x: -x[0])
        return [r["chunk_id"] for _, r in scored[:k]]

    def dense_shortlist(self, namespace: str, query: str, ids: list[str], *,
                        model_id: str, embedder: Callable, k: int = 30, access_groups=None) -> list[str]:
        """Score only a bounded indexed FTS candidate set, never all vectors.

        Accuracy tradeoff: semantic-only material absent from lexical shortlist
        cannot be recalled. Use a separately indexed ANN/Qdrant search when the
        recall benchmark shows this is inadequate.
        """
        require(isinstance(ids, list) and len(ids) <= 120, "dense_shortlist_limit")
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        vector = embedder([query], "query")[0]
        rows = self.db.execute(
            "SELECT c.*, v.vector FROM chunks c JOIN vectors v ON v.chunk_id=c.chunk_id "
            "WHERE c.namespace=? AND v.model_id=? AND v.content_hash=c.content_hash "
            "AND c.chunk_id IN (" + marks + ")",
            (namespace, model_id, *ids)).fetchall()
        scored = sorted(((_cosine(vector, json.loads(r["vector"])), r) for r in rows
                         if self._visible(r, access_groups)), key=lambda x: -x[0])
        return [r["chunk_id"] for _, r in scored[:k]]

    def get(self, chunk_id: str) -> dict:
        row = self.db.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
        require(row is not None, "unknown_chunk")
        return {"chunk_id": row["chunk_id"], "namespace": row["namespace"], "doc_id": row["doc_id"],
                "ordinal": row["ordinal"], "title": row["title"], "text": row["text"],
                "content_hash": row["content_hash"], "metadata": json.loads(row["metadata"] or "{}")}

    def search(self, namespace: str, query: str, *, k: int = 8, dense_model: str | None = None,
               embedder: Callable | None = None, reranker=None, access_groups=None,
               candidates: int = 30, bounded_dense: bool = True) -> dict:
        require(isinstance(query, str) and query.strip() and 1 <= k <= 50, "invalid_retrieval_query")
        rankings = {"lexical": self.lexical(namespace, query, k=candidates, access_groups=access_groups)}
        if dense_model and embedder:
            rankings["dense"] = (self.dense_shortlist(
                namespace, query, rankings["lexical"], model_id=dense_model,
                embedder=embedder, k=candidates, access_groups=access_groups)
                if bounded_dense else self.dense(
                    namespace, query, model_id=dense_model, embedder=embedder,
                    k=candidates, access_groups=access_groups))
        fused = rrf(rankings)[:candidates]
        results = []
        for chunk_id, score, ranks in fused:
            item = self.get(chunk_id)
            item["scores"] = {"rrf": score, "ranks": ranks}
            results.append(item)
        rerank_info = None
        if reranker is not None and results:
            ranked = reranker.rerank(query, [r["text"] for r in results])
            rerank_info = {"provider": ranked["provider"], "fallback_used": ranked.get("fallback_used", False)}
            order = ranked["order"]
            for position, (index, relevance) in enumerate(order):
                results[index]["scores"]["rerank"] = relevance
                results[index]["scores"]["rerank_position"] = position
            results = [results[index] for index, _ in order]
        return {"namespace": namespace, "query_hash": digest(query), "rankings_used": sorted(rankings),
                "dense_strategy": "bounded_lexical_shortlist" if bounded_dense else "full_namespace_legacy",
                "reranker": rerank_info, "results": results[:k],
                "authority": "ranking_evidence_only"}


def as_sources(results: list[dict], *, exclude: set[str] = frozenset()) -> dict[str, dict]:
    """Convert retrieval results into bounded CIDM sources keyed by chunk ID."""
    packet = {}
    for item in results:
        if item["chunk_id"] in exclude:
            continue
        text = item["text"] if len(item["text"]) <= SOURCE_LIMIT else item["text"][:SOURCE_LIMIT - 1] + "…"
        title = (item.get("title") or item["doc_id"])[:110] + " #" + str(item["ordinal"])
        packet[item["chunk_id"]] = {"title": title[:120], "text": text}
    return packet


# ---------------------------------------------------------------- rerankers

class LocalCrossEncoder:
    def __init__(self, model_id: str, *, encoder=None):
        if encoder is None:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
            except ImportError as error:
                raise RuntimeError("fastembed_not_installed") from error
            encoder = TextCrossEncoder(model_name=model_id)
        self.model_id, self.encoder = model_id, encoder

    def rerank(self, query: str, documents: list[str]) -> dict:
        scores = [float(s) for s in self.encoder.rerank(query, documents)]
        order = sorted(enumerate(scores), key=lambda x: -x[1])
        return {"provider": "local:" + self.model_id, "order": order}


class HostedReranker:
    """Cohere (v2/rerank) or Voyage (v1/rerank). The key is read from the environment."""

    ENDPOINTS = {"cohere": "https://api.cohere.com/v2/rerank", "voyage": "https://api.voyageai.com/v1/rerank"}

    def __init__(self, provider: str, model: str, api_key: str, *, opener=None, timeout: float = 20):
        require(provider in self.ENDPOINTS, "unknown_rerank_provider")
        require(isinstance(model, str) and model and isinstance(api_key, str) and api_key, "rerank_config_required")
        self.provider, self.model, self.api_key = provider, model, api_key
        self.opener, self.timeout = opener or urlrequest.urlopen, timeout

    def rerank(self, query: str, documents: list[str]) -> dict:
        body = {"model": self.model, "query": query, "documents": documents}
        body["top_n" if self.provider == "cohere" else "top_k"] = len(documents)
        req = urlrequest.Request(self.ENDPOINTS[self.provider], data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + self.api_key}, method="POST")
        with self.opener(req, timeout=self.timeout) as response:
            data = json.loads(response.read(2_000_000).decode("utf-8"))
        rows = data.get("results") if self.provider == "cohere" else data.get("data")
        require(isinstance(rows, list), "invalid_rerank_response")
        order = [(int(r["index"]), float(r["relevance_score"])) for r in rows]
        require(sorted(i for i, _ in order) == list(range(len(documents))), "rerank_index_mismatch")
        return {"provider": self.provider + ":" + self.model, "order": sorted(order, key=lambda x: -x[1])}


class FallbackReranker:
    """Local first; hosted only when local is unavailable or its top score is below the bar."""

    def __init__(self, local, hosted=None, *, min_top_score: float | None = None):
        self.local, self.hosted, self.min_top_score = local, hosted, min_top_score

    def rerank(self, query: str, documents: list[str]) -> dict:
        try:
            ranked = self.local.rerank(query, documents)
            weak = (self.min_top_score is not None and ranked["order"]
                    and ranked["order"][0][1] < self.min_top_score)
            if not weak or self.hosted is None:
                return {**ranked, "fallback_used": False}
            reason = "local_low_confidence"
        except Exception as error:
            if self.hosted is None:
                raise
            reason = "local_unavailable:" + type(error).__name__
        ranked = self.hosted.rerank(query, documents)
        return {**ranked, "fallback_used": True, "fallback_reason": reason}


# ---------------------------------------------------------------- Qdrant

class QdrantRetriever:
    """Managed Qdrant over REST. Dense or dense+sparse (RRF) queries with payload filters."""

    def __init__(self, url: str, collection: str, *, api_key: str | None = None, opener=None, timeout: float = 20):
        require(isinstance(url, str) and url.startswith(("https://", "http://localhost", "http://127.0.0.1")),
                "qdrant_url_must_be_https_or_local")
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", collection or ""), "invalid_qdrant_collection")
        self.url, self.collection, self.api_key = url.rstrip("/"), collection, api_key
        self.opener, self.timeout = opener or urlrequest.urlopen, timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        req = urlrequest.Request(self.url + path, method=method, headers=headers,
                                 data=json.dumps(body).encode("utf-8") if body is not None else None)
        with self.opener(req, timeout=self.timeout) as response:
            data = json.loads(response.read(8_000_000).decode("utf-8") or "{}")
        require(data.get("status") in (None, "ok"), "qdrant_error")
        return data.get("result", data)

    def ensure_collection(self, dense_size: int, *, sparse: bool = False) -> dict:
        body = {"vectors": {"dense": {"size": dense_size, "distance": "Cosine"}}}
        if sparse:
            body["sparse_vectors"] = {"sparse": {}}
        return self._call("PUT", "/collections/" + self.collection, body)

    def upsert(self, chunks: list[dict], dense: list[list[float]], sparse: list[dict] | None = None) -> dict:
        require(len(chunks) == len(dense) and (sparse is None or len(sparse) == len(chunks)), "qdrant_vector_count")
        points = []
        for index, chunk in enumerate(chunks):
            vector = {"dense": dense[index]}
            if sparse is not None:
                vector["sparse"] = sparse[index]
            points.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["chunk_id"])), "vector": vector,
                           "payload": {k: chunk.get(k) for k in ("chunk_id", "namespace", "doc_id", "ordinal",
                                                                 "title", "text", "content_hash")}
                           | {"access": chunk.get("access", [])}})
        return self._call("PUT", "/collections/" + self.collection + "/points?wait=true", {"points": points})

    def search(self, namespace: str, dense: list[float], *, sparse: dict | None = None, k: int = 8,
               access_groups: list[str] | None = None) -> dict:
        must = [{"key": "namespace", "match": {"value": namespace}}]
        access = [{"is_empty": {"key": "access"}}]
        if access_groups:
            access.append({"key": "access", "match": {"any": list(access_groups)}})
        flt = {"must": must + [{"should": access}]}
        if sparse is None:
            body = {"query": dense, "using": "dense", "limit": k, "filter": flt, "with_payload": True}
        else:
            body = {"prefetch": [{"query": dense, "using": "dense", "limit": k * 4, "filter": flt},
                                 {"query": sparse, "using": "sparse", "limit": k * 4, "filter": flt}],
                    "query": {"fusion": "rrf"}, "limit": k, "with_payload": True}
        result = self._call("POST", "/collections/" + self.collection + "/points/query", body)
        points = result.get("points", result) if isinstance(result, dict) else result
        results = []
        for point in points or []:
            payload = point.get("payload") or {}
            if payload.get("content_hash") != digest(payload.get("text", "")):
                continue  # a payload whose text no longer matches its hash is not evidence
            results.append({**{k2: payload.get(k2) for k2 in ("chunk_id", "namespace", "doc_id", "ordinal",
                                                               "title", "text", "content_hash")},
                            "metadata": {}, "scores": {"qdrant": point.get("score")}})
        return {"namespace": namespace, "results": results, "authority": "ranking_evidence_only"}


# ---------------------------------------------------------------- recovery

class RetrievalEvidenceRetriever:
    """RecoverySupervisor evidence callback over the local hybrid index."""

    def __init__(self, index: LocalHybridIndex, authority: PermitAuthority, *, namespace: str = "default",
                 k: int = 2, max_calls: int = 3, access_groups=None, **search_options):
        require(1 <= k <= 4 and 1 <= max_calls <= 8, "invalid_retrieval_bounds")
        self.index, self.authority, self.namespace, self.k = index, authority, namespace, k
        self.max_calls, self.access_groups, self.options = max_calls, access_groups, search_options
        self.receipts: list[dict] = []

    def __call__(self, packet: dict) -> dict | None:
        if len(self.receipts) >= self.max_calls:
            return None
        events = packet.get("events") or []
        missing = []
        for event in reversed(events):
            receipt = event.get("receipt") or {}
            result = receipt.get("result") if isinstance(receipt, dict) else None
            if isinstance(result, dict) and result.get("missing_evidence"):
                missing = list(result["missing_evidence"])
                break
        query = " ".join([packet.get("goal", ""), packet["unit"].get("objective", ""), *missing])[:2000]
        scope = {"namespace": self.namespace, "query_hash": digest(query), "k": self.k}
        decision = next((e for e in reversed(events) if e.get("kind") in ("post_worker_decision", "jev_decision")), {})
        basis = {"kind": "cidm_recovery_evidence", "unit_id": packet["unit"]["id"],
                 "decision_event_id": decision.get("id") or "unknown",
                 "mesh_version": (events[-1].get("version") if events else 0) or 0}
        permit = self.authority.issue("retrieval.query", scope, basis)
        self.authority.consume(permit, "retrieval.query", scope)
        found = self.index.search(self.namespace, query, k=self.k + 4, access_groups=self.access_groups,
                                  **self.options)
        sources = as_sources(found["results"], exclude=set(packet.get("source_manifest") or []))
        chosen = dict(list(sources.items())[:self.k])
        receipt = {"status": "ok" if chosen else "no_new_evidence", "query_hash": scope["query_hash"],
                   "chunk_ids": list(chosen), "content_hashes": [digest(s["text"]) for s in chosen.values()],
                   "permit_id": permit}
        self.receipts.append(receipt)
        self.authority.receipt(permit, receipt)
        return chosen or None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CIDM hybrid retrieval index")
    parser.add_argument("--db", type=Path, default=Path("~/.jev/retrieval/index.db").expanduser())
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--namespace", required=True)
    ingest.add_argument("--root", type=Path, required=True)
    ingest.add_argument("--access", action="append")
    vectors = sub.add_parser("embed", help="Optional dense vectors (requires fastembed)")
    vectors.add_argument("--model", required=True)
    vectors.add_argument("--namespace")
    search = sub.add_parser("search")
    search.add_argument("--namespace", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--k", type=int, default=5)
    search.add_argument("--dense-model")
    search.add_argument("--access", action="append")
    args = parser.parse_args(argv)
    with LocalHybridIndex(args.db) as index:
        if args.command == "ingest":
            output = index.ingest_path(args.namespace, args.root, access=args.access)
        elif args.command == "embed":
            output = index.build_vectors(args.model, fastembed_embedder(args.model), namespace=args.namespace)
        else:
            embedder = fastembed_embedder(args.dense_model) if args.dense_model else None
            output = index.search(args.namespace, args.query, k=args.k, dense_model=args.dense_model,
                                  embedder=embedder, access_groups=args.access)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
