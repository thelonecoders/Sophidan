"""Retrieval-Augmented Generation engine over the local paper corpus.

The :class:`RAGEngine` chunks papers, embeds the chunks, persists them to a
vector store, and answers user questions by retrieving the top-k chunks,
optionally reranking them, and synthesizing an answer with citations.

The vector store backend is :class:`database.vector_store.VectorStore` when
available, with a deterministic in-memory fallback used in tests or while the
database module is bootstrapping.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Protocol, Sequence, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper protocol (structural — works with any object exposing these attrs)
# ---------------------------------------------------------------------------
class Paper(Protocol):
    """Structural type for a paper object used by the RAG engine.

    Any object exposing ``title``, ``abstract``, ``authors`` (iterable of
    strings or objects with ``name``), and a stable ``id`` / ``doi`` field
    will satisfy this protocol.
    """

    title: str
    abstract: str
    authors: Any
    id: Any
    doi: Any
    year: Any
    full_text: str


def _paper_id(paper: Any) -> str:
    """Return a stable string identifier for a paper-like object."""
    for attr in ("id", "doi", "title"):
        val = getattr(paper, attr, None)
        if val:
            return str(val)
    return uuid.uuid4().hex


def _paper_text(paper: Any) -> str:
    """Concatenate the textual fields of a paper into a single string."""
    parts: List[str] = []
    title = getattr(paper, "title", None)
    if title:
        parts.append(f"Title: {title}")
    abstract = getattr(paper, "abstract", None)
    if abstract:
        parts.append(f"Abstract: {abstract}")
    full_text = getattr(paper, "full_text", None) or getattr(paper, "body", None)
    if full_text:
        parts.append(str(full_text))
    if not parts:
        parts.append(str(paper))
    return "\n\n".join(parts)


def _paper_authors_str(paper: Any) -> str:
    """Return a comma-separated string of author names."""
    authors = getattr(paper, "authors", None)
    if authors is None:
        return ""
    names: List[str] = []
    if isinstance(authors, str):
        return authors
    if isinstance(authors, Iterable):
        for a in authors:
            if isinstance(a, str):
                names.append(a)
            elif hasattr(a, "name"):
                names.append(str(a.name))
            else:
                names.append(str(a))
    return ", ".join(names)


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------
@dataclass
class RAGResponse:
    """Structured response from :meth:`RAGEngine.query`.

    Attributes:
        answer: Generated natural-language answer.
        sources: List of paper objects that contributed to the answer.
        chunks: List of chunk dicts (``id``, ``paper_id``, ``text``,
            ``score``) that were retrieved.
        confidence: Heuristic confidence in [0.0, 1.0] based on retrieval
            score margin and source count.
    """

    answer: str
    sources: List[Any] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the response to a plain dict (suitable for JSON)."""
        return {
            "answer": self.answer,
            "sources": [_paper_summary(s) for s in self.sources],
            "chunks": list(self.chunks),
            "confidence": float(self.confidence),
        }

    def to_markdown(self) -> str:
        """Render the response as a Markdown string with citations."""
        lines: List[str] = [self.answer.strip(), ""]
        if self.sources:
            lines.append("**Sources:**")
            for i, s in enumerate(self.sources, start=1):
                lines.append(f"{i}. {_paper_summary(s)}")
            lines.append("")
        if self.chunks:
            lines.append(f"_Retrieved chunks: {len(self.chunks)}_")
            lines.append(f"_Confidence: {self.confidence:.2f}_")
        return "\n".join(lines).strip()


def _paper_summary(paper: Any) -> str:
    """Return a short, human-readable one-line summary of a paper."""
    title = getattr(paper, "title", "") or ""
    year = getattr(paper, "year", "") or ""
    authors = _paper_authors_str(paper)
    doi = getattr(paper, "doi", "") or ""
    parts = [title]
    if authors:
        parts.append(authors)
    if year:
        parts.append(str(year))
    label = " — ".join(p for p in parts if p)
    if doi:
        label += f" (doi:{doi})"
    elif _paper_id(paper):
        pid = _paper_id(paper)
        if pid and pid != title:
            label += f" [{pid}]"
    return label or _paper_id(paper)


# ---------------------------------------------------------------------------
# In-memory VectorStore fallback
# ---------------------------------------------------------------------------
class _InMemoryVectorStore:
    """Minimal in-memory vector store used when the database module is absent.

    Supports the same minimal interface as ``database.vector_store.VectorStore``:
    ``add(docs_with_ids)``, ``search(query_vec, top_k)``, ``clear()``.
    """

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []
        self._vectors: List[np.ndarray] = []

    def add(self, docs_with_ids: Sequence[Any]) -> None:
        """Add ``[(id, dict), ...]`` or ``[dict, ...]`` records."""
        for entry in docs_with_ids:
            if isinstance(entry, tuple) and len(entry) == 2:
                doc_id, payload = entry
                payload = dict(payload)
                payload.setdefault("id", doc_id)
            elif isinstance(entry, dict):
                payload = dict(entry)
                payload.setdefault("id", uuid.uuid4().hex)
            else:
                payload = {"id": str(entry), "text": str(entry)}
            vec = payload.get("embedding")
            if vec is None:
                continue
            self._records.append(payload)
            self._vectors.append(np.asarray(vec, dtype=np.float32))

    def search(
        self, query_vec: Any, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Return the top-k records by cosine similarity to ``query_vec``."""
        if not self._records:
            return []
        q = np.asarray(query_vec, dtype=np.float32).ravel()
        matrix = np.stack(self._vectors)
        # Cosine similarity (vectors assumed pre-normalized; defensive norm).
        qn = q / (np.linalg.norm(q) + 1e-12)
        mn = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
        sims = mn @ qn
        idx = np.argsort(-sims)[: max(0, int(top_k))]
        results: List[Dict[str, Any]] = []
        for i in idx:
            rec = dict(self._records[i])
            rec["score"] = float(sims[i])
            results.append(rec)
        return results

    def clear(self) -> None:
        """Remove all stored records."""
        self._records.clear()
        self._vectors.clear()

    def count(self) -> int:
        """Return the number of stored records."""
        return len(self._records)


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"\S+")


def _chunk_text(
    text: str, chunk_size: int = 512, overlap: int = 64
) -> Iterator[str]:
    """Yield overlapping word-count chunks of ``text``.

    Args:
        text: Input text.
        chunk_size: Target chunk size in words.
        overlap: Overlap between consecutive chunks in words.
    """
    if not text:
        return
    words = _WORD_RE.findall(text)
    if not words:
        return
    step = max(1, chunk_size - overlap)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_size])
        if chunk.strip():
            yield chunk
        if start + chunk_size >= len(words):
            break


# ---------------------------------------------------------------------------
# RAG engine
# ---------------------------------------------------------------------------
class RAGEngine:
    """Retrieval-Augmented Generation engine over a paper corpus.

    The engine is intentionally lightweight: it accepts an :class:`LLMClient`,
    an embedder (defaults to the LLM client's ``embed`` method), and a vector
    store (defaults to :class:`database.vector_store.VectorStore` when
    importable, else an in-memory store).
    """

    DEFAULT_CHUNK_SIZE = 512
    DEFAULT_CHUNK_OVERLAP = 64
    DEFAULT_TOP_K = 5

    def __init__(
        self,
        llm_client: Any,
        embedder: Any = None,
        vector_store: Any = None,
    ) -> None:
        """Initialize the RAG engine.

        Args:
            llm_client: An :class:`LLMClient` (or compatible) used for query
                embedding when ``embedder`` is ``None`` and for final answer
                generation.
            embedder: Any object exposing ``embed(text) -> np.ndarray``. When
                ``None``, falls back to ``llm_client.embed``.
            vector_store: A vector store exposing ``add``, ``search``, and
                ``clear``. When ``None``, attempts to use
                :class:`database.vector_store.VectorStore`; otherwise falls back
                to an in-memory store.
        """
        self.llm_client = llm_client
        self.embedder = embedder if embedder is not None else llm_client
        self.vector_store = vector_store if vector_store is not None else self._default_vector_store()
        self._indexed_papers: Dict[str, Any] = {}
        self._chunk_count = 0
        logger.debug(
            "RAGEngine initialized with vector_store=%s", type(self.vector_store).__name__
        )

    # --- Defaults ----------------------------------------------------------
    @staticmethod
    def _default_vector_store() -> Any:
        """Return the default vector store (DB-backed if importable)."""
        try:
            from database.vector_store import VectorStore  # type: ignore[import]

            return VectorStore()
        except Exception:  # noqa: BLE001 - DB module optional at this layer
            logger.debug(
                "database.vector_store.VectorStore unavailable; using in-memory fallback."
            )
            return _InMemoryVectorStore()

    # --- Vector-store API adapters ----------------------------------------
    def _store_add(self, docs: List[Dict[str, Any]]) -> None:
        """Add chunk dicts to the vector store, adapting to its add() signature.

        Supports three known signatures:
        1. ``add(ids, embeddings, documents, metadatas=None)`` (ARS VectorStore).
        2. ``add(docs_with_ids: List[dict])`` (spec'd minimal interface).
        3. ``add([(id, dict), ...])`` (alternative tuple form).
        """
        ids = [d["id"] for d in docs]
        try:
            embeddings = np.stack(
                [np.asarray(d["embedding"], dtype=np.float32) for d in docs]
            )
        except (KeyError, TypeError, ValueError):
            embeddings = None
        documents = [d.get("text", "") for d in docs]
        metadatas = [
            {k: v for k, v in d.items() if k not in ("id", "text", "embedding")}
            for d in docs
        ]

        # Attempt #1: ARS VectorStore signature (ids, embeddings, documents, metadatas).
        if embeddings is not None:
            try:
                self.vector_store.add(ids, embeddings, documents, metadatas)
                return
            except TypeError:
                pass  # Fall through to attempt #2.

        # Attempt #2: dict-based signature.
        stripped = []
        for d in docs:
            s = dict(d)
            # Drop the numpy array (stores that take dicts usually don't want it).
            if isinstance(s.get("embedding"), np.ndarray):
                s["embedding"] = s["embedding"].tolist()
            stripped.append(s)
        try:
            self.vector_store.add(stripped)
            return
        except TypeError:
            pass

        # Attempt #3: tuple-based signature.
        try:
            self.vector_store.add([(i, d) for i, d in zip(ids, stripped)])
            return
        except TypeError:
            pass

        logger.error("Could not add %d chunks: incompatible VectorStore.add signature.", len(docs))

    def _store_search(
        self, query_vec: np.ndarray, top_k: int
    ) -> List[Dict[str, Any]]:
        """Search the vector store and normalize results to chunk dicts.

        Handles both SearchResult-object returns and dict-list returns, and
        tolerates the optional ``where`` kwarg.
        """
        hits: Any = []
        try:
            hits = self.vector_store.search(query_vec, top_k=top_k)
        except TypeError:
            try:
                hits = self.vector_store.search(query_vec, top_k=top_k, where=None)
            except Exception:  # noqa: BLE001
                logger.exception("Vector store search failed (with where= fallback).")
                hits = []
        except Exception:  # noqa: BLE001
            logger.exception("Vector store search failed.")
            hits = []

        return self._normalize_hits(hits)

    @staticmethod
    def _normalize_hits(hits: Any) -> List[Dict[str, Any]]:
        """Convert SearchResult objects or dicts to a uniform chunk-dict list."""
        out: List[Dict[str, Any]] = []
        for h in hits or []:
            if isinstance(h, dict):
                out.append(h)
                continue
            # SearchResult-like object with attribute access.
            meta = getattr(h, "metadata", {}) or {}
            out.append(
                {
                    "id": getattr(h, "id", None),
                    "paper_id": meta.get("paper_id"),
                    "text": getattr(h, "document", "") or meta.get("text", ""),
                    "score": float(getattr(h, "score", 0.0) or 0.0),
                    "title": meta.get("title", ""),
                    "authors": meta.get("authors", ""),
                    "year": meta.get("year"),
                    "metadata": dict(meta),
                }
            )
        return out

    # --- Indexing ---------------------------------------------------------
    def index_papers(
        self,
        papers: Sequence[Any],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> int:
        """Chunk, embed, and store each paper's text in the vector store.

        Args:
            papers: Iterable of paper-like objects (see :class:`Paper`).
            chunk_size: Target chunk size in words.
            overlap: Overlap between chunks in words.

        Returns:
            Number of chunks indexed.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be in [0, chunk_size)")

        docs: List[Dict[str, Any]] = []
        for paper in papers:
            paper_id = _paper_id(paper)
            self._indexed_papers[paper_id] = paper
            text = _paper_text(paper)
            for chunk in _chunk_text(text, chunk_size=chunk_size, overlap=overlap):
                chunk_id = f"{paper_id}#{uuid.uuid4().hex[:8]}"
                try:
                    emb = self.embedder.embed(chunk)
                except Exception:  # noqa: BLE001 - degraded embedding
                    logger.exception("Embedding failed for chunk %s", chunk_id)
                    continue
                vec = np.asarray(emb, dtype=np.float32).ravel()
                docs.append(
                    {
                        "id": chunk_id,
                        "paper_id": paper_id,
                        "text": chunk,
                        "embedding": vec,
                        "title": getattr(paper, "title", "") or "",
                        "authors": _paper_authors_str(paper),
                        "year": getattr(paper, "year", None),
                    }
                )

        if docs:
            self._store_add(docs)
        self._chunk_count += len(docs)
        n_papers = len(papers) if hasattr(papers, "__len__") else "?"
        logger.info("Indexed %d chunks from %s papers", len(docs), n_papers)
        return len(docs)

    def clear_index(self) -> None:
        """Remove all chunks and tracked papers from the index."""
        try:
            self.vector_store.clear()
        except Exception:  # noqa: BLE001 - defensive
            logger.exception("vector_store.clear() raised; ignoring.")
        self._indexed_papers.clear()
        self._chunk_count = 0

    def index_stats(self) -> Dict[str, Any]:
        """Return summary statistics about the current index."""
        try:
            store_count = self.vector_store.count()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - not all stores expose count()
            store_count = self._chunk_count
        return {
            "papers_indexed": len(self._indexed_papers),
            "chunks_indexed": self._chunk_count,
            "vector_store": type(self.vector_store).__name__,
            "store_records": store_count,
        }

    # --- Query ------------------------------------------------------------
    def query(
        self,
        question: str,
        top_k: int = DEFAULT_TOP_K,
        filter: Optional[Dict[str, Any]] = None,
    ) -> RAGResponse:
        """Answer ``question`` by retrieving chunks and synthesizing an answer.

        Args:
            question: The user's natural-language question.
            top_k: Number of chunks to retrieve.
            filter: Optional metadata filter applied to candidate chunks.
                Supported keys: ``paper_id`` (str or list of str),
                ``year_min`` (int), ``year_max`` (int).

        Returns:
            A :class:`RAGResponse` with the answer, sources, and chunks.
        """
        if not question.strip():
            return RAGResponse(answer="", sources=[], chunks=[], confidence=0.0)

        # Embed the query.
        try:
            q_vec = np.asarray(self.embedder.embed(question), dtype=np.float32).ravel()
        except Exception:  # noqa: BLE001 - degraded query embedding
            logger.exception("Failed to embed query; returning empty results.")
            return RAGResponse(answer="", sources=[], chunks=[], confidence=0.0)

        # Retrieve.
        raw_hits = self._store_search(q_vec, top_k=top_k * 2)

        hits = self._apply_filter(raw_hits, filter)
        hits = hits[:top_k]

        if not hits:
            return RAGResponse(
                answer="No relevant passages were found in the indexed corpus.",
                sources=[],
                chunks=[],
                confidence=0.0,
            )

        # Rerank (default: mmr for diversity).
        reranked = self.rerank(question, hits, method="mmr")
        chunks = reranked[:top_k]

        # Build context + sources.
        sources: List[Any] = []
        seen_papers: set[str] = set()
        context_parts: List[str] = []
        for i, c in enumerate(chunks, start=1):
            pid = c.get("paper_id")
            if pid and pid not in seen_papers:
                seen_papers.add(pid)
                paper = self._indexed_papers.get(pid)
                if paper is not None:
                    sources.append(paper)
            snippet = c.get("text", "")[:800]
            context_parts.append(f"[{i}] {_short_cite(c)}\n{snippet}")
        context = "\n\n".join(context_parts)

        # Generate the answer.
        prompt = (
            "Answer the user's question using ONLY the passages below. "
            "Cite passages using [n] markers that correspond to the passage "
            "numbers. If the passages do not contain the answer, say so "
            "explicitly.\n\n"
            f"QUESTION: {question}\n\n"
            f"PASSAGES:\n{context}\n\n"
            "ANSWER (in Markdown):"
        )
        try:
            answer = str(self.llm_client.complete(prompt, max_tokens=1200))
        except Exception:  # noqa: BLE001 - degraded generation
            logger.exception("LLM completion failed; returning raw retrieved passages.")
            answer = "Retrieved passages (LLM unavailable):\n\n" + "\n\n".join(
                f"[{i}] {c.get('text', '')[:400]}" for i, c in enumerate(chunks, start=1)
            )

        confidence = self._confidence(chunks)
        return RAGResponse(
            answer=answer.strip(),
            sources=sources,
            chunks=[
                {
                    "id": c.get("id"),
                    "paper_id": c.get("paper_id"),
                    "text": c.get("text", ""),
                    "score": float(c.get("score", 0.0)),
                }
                for c in chunks
            ],
            confidence=confidence,
        )

    # --- Reranking --------------------------------------------------------
    def rerank(
        self,
        query: str,
        retrieved: Sequence[Dict[str, Any]],
        method: str = "mmr",
    ) -> List[Dict[str, Any]]:
        """Rerank retrieved chunks for diversity (MMR) or pure relevance.

        Args:
            query: The original user query (used by ``mmr`` for embedding
                similarity and ignored by ``cross-encoder``).
            retrieved: List of chunk dicts containing ``text`` and ``score``.
            method: ``"mmr"`` for Maximal Marginal Relevance, or
                ``"cross-encoder"`` for a relevance-only score sort.

        Returns:
            A new list of chunks in reranked order.
        """
        items = list(retrieved)
        if not items:
            return []

        method_lower = method.lower()
        if method_lower == "cross-encoder":
            # No real cross-encoder available; fall back to original scores.
            return sorted(items, key=lambda c: float(c.get("score", 0.0)), reverse=True)

        # MMR (lambda = 0.7 by default).
        return self._mmr(query, items, lambda_param=0.7)

    def _mmr(
        self,
        query: str,
        items: List[Dict[str, Any]],
        lambda_param: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Maximal Marginal Relevance reranking using query and chunk embeddings."""
        if not items:
            return []
        try:
            q_vec = np.asarray(self.embedder.embed(query), dtype=np.float32).ravel()
        except Exception:  # noqa: BLE001
            return list(items)

        texts = [c.get("text", "") for c in items]
        if any(t.strip() for t in texts):
            try:
                chunk_embs = np.asarray(self.embedder.embed(texts), dtype=np.float32)
            except Exception:  # noqa: BLE001
                chunk_embs = None
        else:
            chunk_embs = None

        rel_scores = np.array(
            [float(c.get("score", 0.0)) for c in items], dtype=np.float32
        )
        if chunk_embs is not None and chunk_embs.size:
            sim_to_query = self._cosine_matrix(chunk_embs, q_vec)
            # Normalize relevance to [0, 1].
            if rel_scores.max() > rel_scores.min():
                rel_scores = (rel_scores - rel_scores.min()) / (
                    rel_scores.max() - rel_scores.min() + 1e-12
                )
            else:
                rel_scores = np.ones_like(rel_scores)
        else:
            sim_to_query = rel_scores.copy()

        selected: List[int] = []
        remaining = set(range(len(items)))
        # Pick the most relevant first.
        first = int(np.argmax(rel_scores))
        selected.append(first)
        remaining.discard(first)

        while remaining:
            best_idx = -1
            best_score = -np.inf
            for idx in remaining:
                if chunk_embs is not None and chunk_embs.size:
                    sims_sel = [
                        float(self._cosine(chunk_embs[idx], chunk_embs[s]))
                        for s in selected
                    ]
                    max_sim = max(sims_sel) if sims_sel else 0.0
                else:
                    max_sim = 0.0
                mmr_score = lambda_param * float(sim_to_query[idx]) - (1.0 - lambda_param) * max_sim
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx
            if best_idx < 0:
                break
            selected.append(best_idx)
            remaining.discard(best_idx)

        return [items[i] for i in selected]

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors."""
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    @staticmethod
    def _cosine_matrix(matrix: np.ndarray, vec: np.ndarray) -> np.ndarray:
        """Cosine similarity of each row of ``matrix`` to ``vec``."""
        if matrix.ndim != 2:
            matrix = matrix.reshape(1, -1)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
        vn = np.linalg.norm(vec) + 1e-12
        return (matrix @ vec) / (norms.ravel() * vn)

    # --- Filter + helpers -------------------------------------------------
    def _apply_filter(
        self, hits: Sequence[Dict[str, Any]], filter: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Apply a metadata filter to a list of chunk dicts."""
        if not filter:
            return list(hits)
        paper_ids = filter.get("paper_id")
        if isinstance(paper_ids, str):
            paper_ids = {paper_ids}
        elif isinstance(paper_ids, (list, tuple, set)):
            paper_ids = set(paper_ids)
        else:
            paper_ids = None

        year_min = filter.get("year_min")
        year_max = filter.get("year_max")

        out: List[Dict[str, Any]] = []
        for h in hits:
            pid = h.get("paper_id")
            if paper_ids is not None and pid not in paper_ids:
                continue
            year = h.get("year")
            if year is not None:
                try:
                    yi = int(year)
                    if year_min is not None and yi < int(year_min):
                        continue
                    if year_max is not None and yi > int(year_max):
                        continue
                except (TypeError, ValueError):
                    pass
            out.append(h)
        return out

    @staticmethod
    def _confidence(chunks: Sequence[Dict[str, Any]]) -> float:
        """Heuristic confidence score in [0, 1]."""
        if not chunks:
            return 0.0
        scores = [max(0.0, min(1.0, float(c.get("score", 0.0)))) for c in chunks]
        avg = sum(scores) / len(scores)
        # Bonus for having multiple high-scoring sources.
        n_bonus = min(0.2, 0.05 * len(chunks))
        return float(min(1.0, avg + n_bonus))


def _short_cite(chunk: Dict[str, Any]) -> str:
    """Build a short citation string from a chunk's metadata."""
    title = chunk.get("title") or ""
    authors = chunk.get("authors") or ""
    year = chunk.get("year") or ""
    if title and year and authors:
        first_author = authors.split(",")[0].strip() if authors else "Anon"
        return f"{first_author} et al. ({year}). {title[:80]}"
    if title:
        return title[:120]
    pid = chunk.get("paper_id") or chunk.get("id") or "?"
    return f"[{pid}]"


__all__ = ["RAGResponse", "RAGEngine", "Paper"]
