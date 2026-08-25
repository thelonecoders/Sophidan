"""Local vector store for RAG embeddings.

Two-tier implementation:

1. **Preferred backend** — ChromaDB persistent client under
   ``data/chroma/``. Zero-config, in-process, no server required.
2. **Fallback backend** — an in-memory NumPy cosine-similarity index used
   when ChromaDB cannot be imported (e.g. on minimal installs). The
   fallback is non-persistent across processes but keeps the API identical
   so callers do not need to branch.

The :class:`VectorStore` API mirrors the small subset of Chroma's
collection API that ARS actually uses, so swapping backends is invisible
to the rest of the codebase.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

# Heavy deps — import lazily inside functions so this module imports cleanly
# even when chromadb / numpy are not installed.

EmbeddingInput = Union[Sequence[float], Sequence[Sequence[float]]]


def _lazy_numpy():
    """Import numpy on demand and raise a helpful error if missing."""
    try:
        import numpy as np
        return np
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "numpy is required for VectorStore's fallback backend. "
            f"Install it via `pip install numpy>=1.26`. Original error: {exc!r}.",
        ) from exc


def _lazy_chromadb():
    """Import chromadb on demand; return None if unavailable."""
    try:
        import chromadb
        return chromadb
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.info("chromadb unavailable — VectorStore will use NumPy fallback. (%s)", exc)
        return None


@dataclass
class SearchResult:
    """A single vector-search hit.

    Attributes:
        id: The vector's external id (typically ``"paper:{pid}:chunk:{idx}"``).
        document: The chunk text that was indexed.
        metadata: Arbitrary metadata dict associated with the chunk.
        distance: Backend-native distance (lower = more similar for L2;
            higher = more similar for cosine depending on backend).
        score: Normalised similarity score in ``[0, 1]`` — higher is more
            similar. Computed from ``distance`` using each backend's
            semantics.
    """

    id: str
    document: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    distance: float = 0.0
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "id": self.id,
            "document": self.document,
            "metadata": self.metadata or {},
            "distance": self.distance,
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# Fallback backend: in-process NumPy cosine-similarity index.
# ---------------------------------------------------------------------------
class _NumpyBackend:
    """A minimal in-process vector index using NumPy cosine similarity.

    Not persistent across processes. Used only when ChromaDB is missing.
    """

    def __init__(self) -> None:
        self._ids: List[str] = []
        self._docs: List[str] = []
        self._metas: List[Dict[str, Any]] = []
        self._matrix = None  # np.ndarray, shape (N, D)
        self._lock = threading.RLock()

    def add(self, ids: List[str], embeddings, documents: List[str],
            metadatas: Optional[List[Dict[str, Any]]] = None) -> None:
        np = _lazy_numpy()
        emb = np.asarray(embeddings, dtype="float32")
        if emb.ndim == 1:
            emb = emb.reshape(1, -1)
        if emb.shape[0] != len(ids):
            raise ValueError(
                f"Mismatch: {emb.shape[0]} embeddings for {len(ids)} ids.",
            )
        if metadatas is None:
            metadatas = [{} for _ in ids]
        with self._lock:
            # Replace any existing ids.
            existing = set(self._ids)
            keep = [i for i, _id in enumerate(self._ids) if _id not in set(ids)]
            self._ids = [self._ids[i] for i in keep]
            self._docs = [self._docs[i] for i in keep]
            self._metas = [self._metas[i] for i in keep]
            if self._matrix is not None and keep:
                self._matrix = self._matrix[keep]
            elif self._matrix is not None and not keep:
                self._matrix = None
            self._ids.extend(ids)
            self._docs.extend(documents)
            self._metas.extend(metadatas)
            if self._matrix is None:
                self._matrix = emb
            else:
                self._matrix = np.vstack([self._matrix, emb])

    def delete(self, ids: Iterable[str]) -> None:
        ids_set = set(ids)
        with self._lock:
            keep = [i for i, _id in enumerate(self._ids) if _id not in ids_set]
            self._ids = [self._ids[i] for i in keep]
            self._docs = [self._docs[i] for i in keep]
            self._metas = [self._metas[i] for i in keep]
            np = _lazy_numpy()
            if self._matrix is not None and keep:
                self._matrix = self._matrix[keep]
            else:
                self._matrix = None

    def clear(self) -> None:
        with self._lock:
            self._ids.clear()
            self._docs.clear()
            self._metas.clear()
            self._matrix = None

    def count(self) -> int:
        with self._lock:
            return len(self._ids)

    def search(self, query_embedding: Sequence[float], top_k: int = 5,
               where: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        np = _lazy_numpy()
        with self._lock:
            if self._matrix is None or not self._ids:
                return []
            q = np.asarray(query_embedding, dtype="float32").reshape(-1)
            # Cosine similarity.
            qn = q / (np.linalg.norm(q) + 1e-12)
            mat = self._matrix
            norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
            matn = mat / norms
            sims = matn @ qn  # shape (N,)
            order = np.argsort(-sims)[:top_k]
            results: List[SearchResult] = []
            for idx in order:
                meta = dict(self._metas[idx])
                if where and not all(meta.get(k) == v for k, v in where.items()):
                    continue
                sim = float(sims[idx])
                results.append(SearchResult(
                    id=self._ids[idx],
                    document=self._docs[idx],
                    metadata=meta,
                    distance=1.0 - sim,  # convert sim to distance
                    score=max(0.0, min(1.0, sim)),
                ))
            return results

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "backend": "numpy",
                "count": len(self._ids),
                "embedding_dim": int(self._matrix.shape[1]) if self._matrix is not None else None,
                "persistent": False,
            }


# ---------------------------------------------------------------------------
# Main public class.
# ---------------------------------------------------------------------------
class VectorStore:
    """Local vector DB for RAG embeddings.

    Uses ChromaDB persistent client under ``data/chroma/`` when available;
    otherwise falls back to an in-process NumPy cosine-similarity index
    (non-persistent).

    The API intentionally mirrors the small subset of Chroma's collection
    API that ARS needs.
    """

    def __init__(self, collection_name: str = "papers",
                 embedding_dim: int = 384,
                 persist_path: Optional[Union[str, Path]] = None,
                 db: Any = None) -> None:
        """Initialise the store, lazily creating the backend.

        Args:
            collection_name: ChromaDB collection name (default ``"papers"``).
            embedding_dim: Expected embedding dimensionality (used by the
                NumPy fallback and for validation).
            persist_path: Directory for the ChromaDB persistent client.
                Defaults to ``data/chroma/``.
            db: Optional :class:`database.connection.DatabaseConnection`
                (unused right now but kept for future cross-DB integration).
        """
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim
        self.persist_path = Path(persist_path) if persist_path else Path("data/chroma")
        self._db = db
        self._backend: Optional[Any] = None  # chromadb collection or _NumpyBackend
        self._client: Any = None
        self._lock = threading.RLock()
        self._init_backend()

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------
    def _init_backend(self) -> None:
        """Pick ChromaDB if available; otherwise instantiate the NumPy fallback."""
        chromadb = _lazy_chromadb()
        if chromadb is None:
            self._backend = _NumpyBackend()
            logger.info("VectorStore using NumPy fallback backend (non-persistent).")
            return
        try:
            self.persist_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.persist_path))
            self._backend = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("VectorStore using ChromaDB backend at %s.", self.persist_path)
        except Exception as exc:  # pragma: no cover - depends on environment
            logger.warning("ChromaDB init failed (%s) — falling back to NumPy.", exc)
            self._backend = _NumpyBackend()
            self._client = None

    @property
    def backend_name(self) -> str:
        """Return the backend in use (``"chromadb"`` or ``"numpy"``)."""
        if isinstance(self._backend, _NumpyBackend):
            return "numpy"
        return "chromadb"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def add(self, ids: List[str],
            embeddings: EmbeddingInput,
            documents: List[str],
            metadatas: Optional[List[Dict[str, Any]]] = None) -> None:
        """Add (or upsert) embeddings to the store.

        Args:
            ids: External ids, one per embedding. Typically
                ``"paper:{pid}:chunk:{idx}"``.
            embeddings: 2-D array-like of shape ``(N, D)`` (or 1-D for a
                single embedding).
            documents: Chunk text strings, one per embedding.
            metadatas: Optional per-row metadata dicts.
        """
        if len(ids) != len(documents):
            raise ValueError(
                f"ids ({len(ids)}) and documents ({len(documents)}) must align.",
            )
        if metadatas is not None and len(metadatas) != len(ids):
            raise ValueError(
                f"metadatas ({len(metadatas)}) and ids ({len(ids)}) must align.",
            )
        if isinstance(self._backend, _NumpyBackend):
            self._backend.add(ids, embeddings, documents, metadatas)
            return
        # ChromaDB path.
        emb_list = self._coerce_embeddings(embeddings)
        self._backend.upsert(
            ids=ids,
            embeddings=emb_list,
            documents=documents,
            metadatas=metadatas or [{} for _ in ids],
        )

    def _coerce_embeddings(self, embeddings: EmbeddingInput) -> List[List[float]]:
        """Normalise embeddings to a plain list-of-lists of floats."""
        try:
            np = _lazy_numpy()
            arr = np.asarray(embeddings, dtype="float32")
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.shape[1] != self.embedding_dim:
                logger.warning(
                    "Embedding dim %d != configured %d — proceed anyway.",
                    arr.shape[1], self.embedding_dim,
                )
            return arr.tolist()
        except ImportError:
            # numpy not available; coerce manually.
            if isinstance(embeddings[0], (int, float)):
                return [list(embeddings)]  # type: ignore[arg-type]
            return [list(e) for e in embeddings]  # type: ignore[arg-type]

    def search(self, query_embedding: Sequence[float],
               top_k: int = 5,
               where: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """Return the ``top_k`` most similar chunks.

        Args:
            query_embedding: A 1-D embedding vector.
            top_k: Maximum number of hits to return.
            where: Optional Chroma-style metadata filter (e.g.
                ``{"paper_id": 42}``).

        Returns:
            A list of :class:`SearchResult` (highest score first).
        """
        if isinstance(self._backend, _NumpyBackend):
            return self._backend.search(query_embedding, top_k, where)
        # ChromaDB path.
        q = self._coerce_embeddings(query_embedding)[0]
        kwargs: Dict[str, Any] = {
            "query_embeddings": [q],
            "n_results": top_k,
        }
        if where:
            kwargs["where"] = where
        res = self._backend.query(**kwargs)
        return self._chroma_results_to_searchresults(res)

    @staticmethod
    def _chroma_results_to_searchresults(res: Dict[str, Any]) -> List[SearchResult]:
        """Convert a ChromaDB query result into ``SearchResult`` instances."""
        out: List[SearchResult] = []
        if not res or not res.get("ids"):
            return out
        ids_batch = res["ids"][0]
        docs_batch = (res.get("documents") or [[]])[0]
        metas_batch = (res.get("metadatas") or [[]])[0]
        dists_batch = (res.get("distances") or [[]])[0]
        for i, _id in enumerate(ids_batch):
            dist = float(dists_batch[i]) if i < len(dists_batch) else 0.0
            # Chroma cosine distance is in [0, 2]; similarity = 1 - distance.
            score = max(0.0, min(1.0, 1.0 - dist))
            out.append(SearchResult(
                id=_id,
                document=docs_batch[i] if i < len(docs_batch) else "",
                metadata=metas_batch[i] if i < len(metas_batch) else {},
                distance=dist,
                score=score,
            ))
        return out

    def delete(self, ids: Union[str, Iterable[str]]) -> None:
        """Delete one or more vectors by id."""
        if isinstance(ids, str):
            ids = [ids]
        ids = list(ids)
        if isinstance(self._backend, _NumpyBackend):
            self._backend.delete(ids)
            return
        self._backend.delete(ids=ids)

    def clear(self) -> None:
        """Remove every vector from the active collection."""
        if isinstance(self._backend, _NumpyBackend):
            self._backend.clear()
            return
        # ChromaDB: drop + recreate the collection.
        if self._client is not None:
            try:
                self._client.delete_collection(self.collection_name)
            except Exception:  # pragma: no cover
                pass
            self._backend = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

    def count(self) -> int:
        """Return the number of vectors currently in the store."""
        if isinstance(self._backend, _NumpyBackend):
            return self._backend.count()
        try:
            return int(self._backend.count())
        except Exception:  # pragma: no cover
            return 0

    def stats(self) -> Dict[str, Any]:
        """Return a dict describing the store state."""
        if isinstance(self._backend, _NumpyBackend):
            s = self._backend.stats()
        else:
            s = {
                "backend": "chromadb",
                "count": self.count(),
                "collection": self.collection_name,
                "persist_path": str(self.persist_path),
                "persistent": True,
            }
        s["embedding_dim"] = self.embedding_dim
        return s

    # ------------------------------------------------------------------
    # Bulk rebuild from a list of papers.
    # ------------------------------------------------------------------
    def rebuild(self, embedder: Any, papers: Sequence[Any],
                chunk_size: int = 800) -> int:
        """Rebuild the entire index from a list of papers.

        Args:
            embedder: Any object exposing ``.embed(texts: List[str])
                -> List[List[float]]`` or ``.encode(...)`` (sentence-
                transformers-style). The embedder is called once per chunk
                batch.
            papers: Iterable of paper-like objects with ``.id``,
                ``.title``, ``.abstract`` attributes.
            chunk_size: Approximate character length per chunk.

        Returns:
            The number of chunks indexed.
        """
        self.clear()
        total = 0
        batch_ids: List[str] = []
        batch_docs: List[str] = []
        batch_metas: List[Dict[str, Any]] = []

        def _flush() -> None:
            nonlocal total
            if not batch_ids:
                return
            embs = self._embed_texts(embedder, batch_docs)
            self.add(batch_ids, embs, batch_docs, batch_metas)
            total += len(batch_ids)
            batch_ids.clear()
            batch_docs.clear()
            batch_metas.clear()

        for paper in papers:
            pid = getattr(paper, "id", None)
            if pid is None:
                logger.warning("Skipping paper with no id: %r", paper)
                continue
            text_parts = [
                getattr(paper, "title", "") or "",
                getattr(paper, "abstract", "") or "",
            ]
            full_text = "\n\n".join(p for p in text_parts if p).strip()
            if not full_text:
                continue
            chunks = self._chunk_text(full_text, chunk_size)
            for idx, chunk in enumerate(chunks):
                batch_ids.append(f"paper:{pid}:chunk:{idx}")
                batch_docs.append(chunk)
                batch_metas.append({
                    "paper_id": pid,
                    "chunk_idx": idx,
                    "title": getattr(paper, "title", ""),
                    "source": getattr(paper, "source", ""),
                    "year": getattr(paper, "year", None),
                })
                if len(batch_ids) >= 64:
                    _flush()
        _flush()
        logger.info("VectorStore rebuild complete — %d chunks indexed.", total)
        return total

    @staticmethod
    def _chunk_text(text: str, chunk_size: int) -> List[str]:
        """Naive word-boundary chunker.

        Args:
            text: Input text.
            chunk_size: Approximate target chunk length in characters.

        Returns:
            List of chunk strings.
        """
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]
        words = text.split()
        chunks: List[str] = []
        cur: List[str] = []
        cur_len = 0
        for w in words:
            if cur_len + len(w) + 1 > chunk_size and cur:
                chunks.append(" ".join(cur))
                cur = [w]
                cur_len = len(w)
            else:
                cur.append(w)
                cur_len += len(w) + 1
        if cur:
            chunks.append(" ".join(cur))
        return chunks

    @staticmethod
    def _embed_texts(embedder: Any, texts: List[str]) -> List[List[float]]:
        """Call the supplied embedder on a batch of texts.

        Supports both sentence-transformers-style ``.encode`` (returns numpy
        array) and a custom ``.embed`` (returns list of lists).
        """
        if hasattr(embedder, "embed"):
            return list(embedder.embed(texts))
        if hasattr(embedder, "encode"):
            out = embedder.encode(texts)
            try:
                np = _lazy_numpy()
                arr = np.asarray(out, dtype="float32")
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                return arr.tolist()
            except ImportError:
                return [list(row) for row in out]
        raise TypeError(
            f"embedder {type(embedder)!r} exposes neither .embed() nor .encode().",
        )

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<VectorStore backend={self.backend_name!r} count={self.count()}>"


__all__ = ["VectorStore", "SearchResult"]
