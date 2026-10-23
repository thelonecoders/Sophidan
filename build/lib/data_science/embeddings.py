"""Sentence-embedding utilities with graceful mock fallback.

The :class:`EmbeddingsModel` wraps ``sentence-transformers`` and exposes a
small, serialisable API for encoding texts into dense vectors and computing
cosine similarities. If ``sentence-transformers`` is unavailable at runtime
the class transparently switches to a deterministic *mock mode* that returns
hash-seeded random vectors of the same dimensionality — this keeps unit
tests green without forcing a heavy install.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingsModel:
    """Wrapper around ``sentence-transformers`` with mock-mode fallback.

    Attributes:
        model_name: Name of the underlying sentence-transformers model.
        embedding_dim: Dimensionality of the produced embeddings.
        mock: ``True`` when running without a real backend.
    """

    #: Default embedding dimension (matches ``all-MiniLM-L6-v2``).
    DEFAULT_DIM: int = 384

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: Optional[str] = None,
        mock: Optional[bool] = None,
    ) -> None:
        """Initialize the embeddings model.

        Args:
            model_name: HuggingFace / sentence-transformers model id.
            device: Optional torch device (``"cpu"``, ``"cuda"`` ...).
            mock: Force mock mode on/off. When ``None`` (default), mock
                mode is auto-enabled if sentence-transformers cannot be
                imported.
        """
        self.model_name = model_name
        self.device = device
        self._model: Any = None
        self.embedding_dim: int = self.DEFAULT_DIM
        if mock is None:
            mock = not self._can_import_st()
        self.mock: bool = bool(mock)
        self.logger = logger
        if self.mock:
            self.logger.warning(
                "EmbeddingsModel running in MOCK mode "
                "(sentence-transformers unavailable). Returning deterministic "
                "random vectors — NOT suitable for production use."
            )

    # ------------------------------------------------------------------
    # Backend resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _can_import_st() -> bool:
        """Return ``True`` if ``sentence_transformers`` is importable."""
        try:
            import sentence_transformers  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure_model(self) -> None:
        """Lazily construct the underlying sentence-transformers model."""
        if self.mock:
            return
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning(
                "sentence-transformers import failed (%s); "
                "switching to MOCK mode.", exc
            )
            self.mock = True
            return
        try:
            self._model = SentenceTransformer(self.model_name, device=self.device)
            try:
                self.embedding_dim = int(self._model.get_sentence_embedding_dimension())
            except Exception:  # pragma: no cover - defensive
                self.embedding_dim = self.DEFAULT_DIM
        except Exception as exc:
            self.logger.warning(
                "Failed to load sentence-transformers model '%s' (%s); "
                "switching to MOCK mode.", self.model_name, exc
            )
            self.mock = True

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def _mock_vector(self, text: str) -> np.ndarray:
        """Produce a deterministic pseudo-embedding for ``text``."""
        seed = int.from_bytes(
            hashlib.sha256(text.encode("utf-8")).digest()[:8], "little"
        )
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.embedding_dim).astype(np.float32)
        n = float(np.linalg.norm(v))
        if n > 0:
            v = v / n
        return v

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single text into a 1-D embedding vector.

        Args:
            text: Input text.

        Returns:
            ``np.ndarray`` of shape ``(embedding_dim,)`` and dtype
            ``float32``. Mock mode returns a hash-seeded random unit
            vector.
        """
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        self._ensure_model()
        if self.mock or self._model is None:
            return self._mock_vector(text)
        vec = self._model.encode(
            [text], convert_to_numpy=True, show_progress_bar=False
        )
        return np.asarray(vec[0], dtype=np.float32)

    def encode(
        self, texts: Sequence[str], batch_size: int = 32
    ) -> np.ndarray:
        """Encode a batch of texts into a 2-D embedding matrix.

        Args:
            texts: Sequence of input strings.
            batch_size: Batch size forwarded to the underlying encoder.

        Returns:
            ``np.ndarray`` of shape ``(len(texts), embedding_dim)``.
        """
        texts = list(texts)
        self._ensure_model()
        if self.mock or self._model is None:
            return np.vstack(
                [self._mock_vector(t if isinstance(t, str) else str(t)) for t in texts]
            ) if texts else np.zeros((0, self.embedding_dim), dtype=np.float32)
        vecs = self._model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    # ------------------------------------------------------------------
    # Similarity
    # ------------------------------------------------------------------

    @staticmethod
    def _unit(v: np.ndarray) -> np.ndarray:
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v

    def similarity(self, a: Any, b: Any) -> float:
        """Cosine similarity between two vectors (or texts).

        Args:
            a: Vector or text. If a string, it is encoded first.
            b: Vector or text. If a string, it is encoded first.

        Returns:
            Cosine similarity in ``[-1, 1]``.
        """
        va = self._as_vector(a)
        vb = self._as_vector(b)
        denom = float(np.linalg.norm(va)) * float(np.linalg.norm(vb))
        if denom == 0.0:
            return 0.0
        return float(np.dot(va, vb) / denom)

    def similarities(
        self, query: Any, docs: Sequence[Any]
    ) -> np.ndarray:
        """Cosine similarities from a query to each document.

        Args:
            query: Query vector or text.
            docs: Sequence of document vectors or texts.

        Returns:
            ``np.ndarray`` of shape ``(len(docs),)``.
        """
        q = self._as_vector(query)
        docs = list(docs)
        if not docs:
            return np.zeros((0,), dtype=np.float32)
        mat = np.vstack([self._as_vector(d) for d in docs])
        qn = float(np.linalg.norm(q))
        dn = np.linalg.norm(mat, axis=1)
        denom = qn * dn
        out = np.zeros(mat.shape[0], dtype=np.float32)
        nonzero = denom > 0
        if np.any(nonzero):
            out[nonzero] = (mat[nonzero] @ q) / denom[nonzero]
        return out

    def _as_vector(self, value: Any) -> np.ndarray:
        """Coerce ``value`` (str or vector) into a 1-D ``np.ndarray``."""
        if isinstance(value, str):
            return self.encode_single(value)
        arr = np.asarray(value, dtype=np.float32)
        if arr.ndim == 2 and arr.shape[0] == 1:
            arr = arr[0]
        return arr

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist a snapshot of this model's configuration and vectors.

        The underlying sentence-transformers model is *not* serialised
        (it can simply be re-loaded by name). Instead we persist the
        model name, mock flag, and embedding dimension via ``joblib``.

        Args:
            path: Destination ``.joblib`` path.
        """
        try:
            import joblib
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                "joblib is required to save EmbeddingsModel"
            ) from exc
        snapshot = {
            "model_name": self.model_name,
            "embedding_dim": self.embedding_dim,
            "mock": self.mock,
            "device": self.device,
        }
        joblib.dump(snapshot, path)
        self.logger.info("Saved EmbeddingsModel snapshot -> %s", path)

    def load(self, path: str) -> "EmbeddingsModel":
        """Load a previously saved snapshot and apply it to ``self``.

        Args:
            path: Source ``.joblib`` path.

        Returns:
            ``self`` (for chaining).
        """
        try:
            import joblib
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                "joblib is required to load EmbeddingsModel"
            ) from exc
        snapshot = joblib.load(path)
        self.model_name = snapshot.get("model_name", self.model_name)
        self.embedding_dim = snapshot.get("embedding_dim", self.embedding_dim)
        self.mock = bool(snapshot.get("mock", self.mock))
        self.device = snapshot.get("device", self.device)
        self._model = None  # force lazy reload
        return self
