"""paper_recommendation — semantic paper-recommendation engine for the
Academic Research Suite.

This module delivers a flexible, multi-strategy recommender that goes
well beyond simple keyword search:

* :meth:`PaperRecommender.recommend_for_query` — semantic search (query
  encoded into the same embedding space as the corpus).
* :meth:`PaperRecommender.recommend_similar` — "find more like this"
  for a given seed paper.
* :meth:`PaperRecommender.recommend_for_user` — personalized recs from
  a user's reading history (centroid of seed embeddings).
* :meth:`PaperRecommender.recommend_for_topic` — topic-aware recs.
* :meth:`PaperRecommender.recommend_bridge_papers` — papers that
  bridge two distinct research areas (high cosine similarity to both
  seed embeddings).
* :meth:`PaperRecommender.recommend_trending` — recently-published,
  high-citation-velocity papers.
* :meth:`PaperRecommender.diversify` — MMR (maximal-marginal-relevance)
  re-ranking for diversity.
* :meth:`PaperRecommender.explain` — natural-language explanation of
  *why* a paper was recommended.
* :meth:`PaperRecommender.evaluate` — held-out evaluation via nDCG /
  precision / recall.

When ``faiss`` is available, an index is built for fast similarity
search; otherwise the module falls back to in-memory cosine similarity
(numpy).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_fonts() -> None:
    """Configure matplotlib rcParams for CJK-aware font fallback."""
    try:
        import matplotlib
        from matplotlib import font_manager
        preferred = [
            "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
            "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans",
        ]
        available = {f.name for f in font_manager.fontManager.ttflist}
        family = [f for f in preferred if f in available] or ["DejaVu Sans"]
        matplotlib.rcParams["font.family"] = family
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Font configuration failed: %s", exc)


def _paper_text(p: Any) -> str:
    """Concatenated text representation of a paper."""
    parts = []
    title = getattr(p, "title", "") or ""
    abstract = getattr(p, "abstract", "") or ""
    if title:
        parts.append(title)
    if abstract:
        parts.append(abstract)
    kws = getattr(p, "keywords", []) or []
    if kws:
        parts.append(" ".join(str(k) for k in kws))
    return " ".join(parts).strip() or (title or "empty")


def _safe_year(p: Any) -> Optional[int]:
    """Return ``int(p.year)`` or ``None``."""
    y = getattr(p, "year", None)
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _safe_id(p: Any) -> str:
    """Return a stable identifier for a paper."""
    return str(getattr(p, "doi", None) or getattr(p, "title", None) or id(p))


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize ``v`` row-wise (returns ``v`` unchanged for zero rows)."""
    if v.ndim == 1:
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


# ---------------------------------------------------------------------------
# PaperRecommender
# ---------------------------------------------------------------------------


class PaperRecommender:
    """Multi-strategy paper-recommendation engine.

    Embeddings are computed lazily on the first call to any
    recommendation method or explicitly via :meth:`index_papers`.
    """

    DEFAULT_EMBEDDING_DIM = 384

    def __init__(
        self,
        papers: Sequence[Any],
        embedder: Any = None,
    ) -> None:
        """Initialize the recommender.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            embedder: Optional object with an ``encode(texts)``
                method. If ``None``, a
                :class:`data_science.embeddings.EmbeddingsModel` is
                constructed lazily on first use.
        """
        self.papers: List[Any] = list(papers)
        self.embedder = embedder
        self._embeddings: Optional[np.ndarray] = None
        self._faiss_index: Any = None
        self._index_built: bool = False
        self._paper_ids: List[str] = [_safe_id(p) for p in self.papers]
        self._id_to_idx: Dict[str, int] = {
            pid: i for i, pid in enumerate(self._paper_ids) if pid
        }
        self.logger = logger

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _get_embedder(self) -> Any:
        """Return the active embedder, constructing one lazily if needed."""
        if self.embedder is not None:
            return self.embedder
        try:
            from data_science.embeddings import EmbeddingsModel  # type: ignore
            self.embedder = EmbeddingsModel()
            return self.embedder
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning(
                "Could not construct EmbeddingsModel (%s); using random fallback.",
                exc,
            )
            return _RandomEmbedder(self.DEFAULT_EMBEDDING_DIM)

    def index_papers(self) -> None:
        """Precompute paper embeddings and build a similarity index.

        Uses FAISS if available, otherwise builds a plain numpy matrix
        for cosine similarity.
        """
        if not self.papers:
            self._embeddings = np.zeros((0, self.DEFAULT_EMBEDDING_DIM),
                                         dtype=np.float32)
            self._index_built = True
            return
        embedder = self._get_embedder()
        texts = [_paper_text(p) for p in self.papers]
        try:
            mat = embedder.encode(texts)
        except Exception as exc:
            self.logger.warning(
                "Embedder.encode failed (%s); using random fallback.", exc)
            mat = _RandomEmbedder(self.DEFAULT_EMBEDDING_DIM).encode(texts)
        mat = np.asarray(mat, dtype=np.float32)
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        self._embeddings = _l2_normalize(mat)
        # Try to build a FAISS index.
        try:
            import faiss  # type: ignore  # lazy
            dim = self._embeddings.shape[1]
            index = faiss.IndexFlatIP(dim)
            index.add(self._embeddings)
            self._faiss_index = index
            self.logger.info("FAISS index built with %d vectors.",
                              index.ntotal)
        except ImportError:
            self._faiss_index = None
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("FAISS index construction failed (%s); "
                                 "using numpy cosine similarity.", exc)
            self._faiss_index = None
        self._index_built = True

    def _ensure_index(self) -> None:
        """Build the index on first use."""
        if not self._index_built:
            self.index_papers()

    # ------------------------------------------------------------------
    # Internal similarity helpers
    # ------------------------------------------------------------------

    def _encode_query(self, text: str) -> np.ndarray:
        """Encode a single text string into a unit-norm vector."""
        embedder = self._get_embedder()
        try:
            v = embedder.encode([text])
            v = np.asarray(v, dtype=np.float32)
            if v.ndim == 1:
                v = v.reshape(1, -1)
        except Exception as exc:
            self.logger.warning("Query encode failed (%s); random fallback.", exc)
            v = _RandomEmbedder(self.DEFAULT_EMBEDDING_DIM).encode([text])
        return _l2_normalize(v)[0]

    def _top_k_cosine(
        self,
        query_vec: np.ndarray,
        top_k: int,
        exclude_ids: Optional[set] = None,
    ) -> List[Tuple[int, float]]:
        """Return top-k ``(paper_idx, cosine_similarity)`` pairs."""
        self._ensure_index()
        if self._embeddings is None or len(self._embeddings) == 0:
            return []
        q = _l2_normalize(query_vec.reshape(1, -1))[0]
        if self._faiss_index is not None:
            scores, indices = self._faiss_index.search(
                q.reshape(1, -1).astype(np.float32), max(top_k * 4, top_k),
            )
            pairs: List[Tuple[int, float]] = []
            for idx, score in zip(indices[0].tolist(), scores[0].tolist()):
                if idx < 0:
                    continue
                pid = self._paper_ids[idx] if idx < len(self._paper_ids) else ""
                if exclude_ids and pid in exclude_ids:
                    continue
                pairs.append((idx, float(score)))
                if len(pairs) >= top_k:
                    break
            return pairs
        # Numpy fallback: cosine similarity (vectors are unit-norm).
        sims = self._embeddings @ q
        order = np.argsort(-sims)
        out: List[Tuple[int, float]] = []
        for idx in order:
            idx = int(idx)
            pid = self._paper_ids[idx] if idx < len(self._paper_ids) else ""
            if exclude_ids and pid in exclude_ids:
                continue
            out.append((idx, float(sims[idx])))
            if len(out) >= top_k:
                break
        return out

    # ------------------------------------------------------------------
    # Public recommendation methods
    # ------------------------------------------------------------------

    def recommend_for_query(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Tuple[Any, float]]:
        """Return the top-k papers most semantically similar to ``query``.

        Args:
            query: Free-text query.
            top_k: Number of recommendations.

        Returns:
            List of ``(paper, score)`` tuples.
        """
        qv = self._encode_query(query)
        pairs = self._top_k_cosine(qv, top_k)
        return [(self.papers[i], s) for i, s in pairs]

    def recommend_similar(
        self,
        paper: Any,
        top_k: int = 10,
    ) -> List[Tuple[Any, float]]:
        """Return papers most similar to ``paper``.

        Args:
            paper: A :class:`Paper`-like object.
            top_k: Number of recommendations.

        Returns:
            List of ``(paper, score)`` tuples (the input paper is
            excluded from the result).
        """
        self._ensure_index()
        paper_id = _safe_id(paper)
        idx = self._id_to_idx.get(paper_id)
        if idx is None:
            # Not in the index: encode on the fly.
            qv = self._encode_query(_paper_text(paper))
        else:
            qv = self._embeddings[idx]
        pairs = self._top_k_cosine(qv, top_k, exclude_ids={paper_id})
        return [(self.papers[i], s) for i, s in pairs]

    def recommend_for_user(
        self,
        user_history: Sequence[Any],
        top_k: int = 10,
    ) -> List[Tuple[Any, float]]:
        """Return personalized recommendations from a user's history.

        The user profile is the centroid of the seed papers'
        embeddings. Seed papers themselves are excluded from results.

        Args:
            user_history: Sequence of :class:`Paper`-like objects the
                user has previously read or saved.
            top_k: Number of recommendations.

        Returns:
            List of ``(paper, score)`` tuples.
        """
        if not user_history:
            return []
        self._ensure_index()
        # Encode the seed papers.
        exclude: set = set()
        seed_vecs: List[np.ndarray] = []
        for p in user_history:
            pid = _safe_id(p)
            exclude.add(pid)
            idx = self._id_to_idx.get(pid)
            if idx is not None and self._embeddings is not None:
                seed_vecs.append(self._embeddings[idx])
            else:
                seed_vecs.append(self._encode_query(_paper_text(p)))
        if not seed_vecs:
            return []
        centroid = np.mean(np.vstack(seed_vecs), axis=0)
        pairs = self._top_k_cosine(centroid, top_k, exclude_ids=exclude)
        return [(self.papers[i], s) for i, s in pairs]

    def recommend_for_topic(
        self,
        topic: str,
        top_k: int = 10,
    ) -> List[Tuple[Any, float]]:
        """Return papers most relevant to a topic string.

        Equivalent to :meth:`recommend_for_query` but with a topic
        label as the query, plus a boost for papers that explicitly
        list the topic as a keyword.

        Args:
            topic: Topic keyword.
            top_k: Number of recommendations.

        Returns:
            List of ``(paper, score)`` tuples.
        """
        qv = self._encode_query(topic)
        pairs = self._top_k_cosine(qv, max(top_k * 2, top_k))
        results: List[Tuple[Any, float]] = []
        topic_lower = topic.lower()
        for idx, score in pairs:
            p = self.papers[idx]
            kws = [str(k).lower() for k in (getattr(p, "keywords", []) or [])]
            boost = 0.10 if topic_lower in kws else 0.0
            results.append((p, float(score + boost)))
            if len(results) >= top_k:
                break
        return results

    def recommend_bridge_papers(
        self,
        paper_a: Any,
        paper_b: Any,
        top_k: int = 5,
    ) -> List[Any]:
        """Return papers that *bridge* two research areas.

        A bridge paper has high cosine similarity to *both* seed papers
        — i.e. it lives at the intersection of two distinct research
        communities.

        Args:
            paper_a: First seed paper.
            paper_b: Second seed paper.
            top_k: Number of bridge papers.

        Returns:
            List of bridge :class:`Paper` objects (no scores — caller
            typically uses these as exploration seeds).
        """
        self._ensure_index()
        va = self._encode_query_or_index(paper_a)
        vb = self._encode_query_or_index(paper_b)
        exclude = {_safe_id(paper_a), _safe_id(paper_b)}
        # Score = harmonic mean of the two similarities.
        sims_a = self._embeddings @ va if self._embeddings is not None else np.zeros(0)
        sims_b = self._embeddings @ vb if self._embeddings is not None else np.zeros(0)
        # Guard against division by zero.
        sa = np.maximum(sims_a, 1e-6)
        sb = np.maximum(sims_b, 1e-6)
        bridge = 2 * sa * sb / (sa + sb)
        order = np.argsort(-bridge)
        out: List[Any] = []
        for idx in order:
            idx = int(idx)
            pid = self._paper_ids[idx] if idx < len(self._paper_ids) else ""
            if pid in exclude:
                continue
            out.append(self.papers[idx])
            if len(out) >= top_k:
                break
        return out

    def _encode_query_or_index(self, paper: Any) -> np.ndarray:
        """Return the embedding for a paper, using the index if available."""
        self._ensure_index()
        pid = _safe_id(paper)
        idx = self._id_to_idx.get(pid)
        if idx is not None and self._embeddings is not None:
            return self._embeddings[idx]
        return self._encode_query(_paper_text(paper))

    def recommend_trending(
        self,
        top_k: int = 20,
        days: int = 30,
    ) -> List[Tuple[Any, float]]:
        """Return recently-published papers with high citation velocity.

        Velocity is approximated by ``citations_count / age_in_days``
        (using ``year`` as the publication date, with ``days``
        interpreted as a *year* window for filtering recent papers).

        Args:
            top_k: Number of recommendations.
            days: Recency threshold (in *days* for filtering; papers
                published within ``days / 365`` years of the latest
                year in the corpus are considered "recent").

        Returns:
            List of ``(paper, velocity)`` tuples.
        """
        if not self.papers:
            return []
        years = [y for y in (_safe_year(p) for p in self.papers) if y is not None]
        if not years:
            return []
        max_year = max(years)
        year_cutoff = max_year - days / 365.0
        scored: List[Tuple[float, Any]] = []
        for p in self.papers:
            y = _safe_year(p)
            if y is None or y < year_cutoff:
                continue
            cit = int(getattr(p, "citations_count", 0) or 0)
            age_years = max(1, max_year - y + 1)
            # Velocity: citations per year since publication.
            velocity = cit / age_years
            scored.append((velocity, p))
        scored.sort(key=lambda kv: -kv[0])
        return [(p, v) for v, p in scored[:top_k]]

    # ------------------------------------------------------------------
    # Diversification (MMR)
    # ------------------------------------------------------------------

    def diversify(
        self,
        recommendations: List[Tuple[Any, float]],
        lambda_param: float = 0.5,
    ) -> List[Tuple[Any, float]]:
        """Re-rank recommendations using Maximal Marginal Relevance.

        MMR balances relevance and diversity:

            MMR = λ · rel(p) - (1-λ) · max_{p'∈S} sim(p, p')

        where ``rel`` is the original relevance score and ``sim`` is
        the cosine similarity in embedding space.

        Args:
            recommendations: Original ``(paper, score)`` list.
            lambda_param: Trade-off (1.0 = pure relevance, 0.0 = pure
                diversity).

        Returns:
            Re-ranked list of ``(paper, score)`` tuples.
        """
        if not recommendations:
            return []
        self._ensure_index()
        if self._embeddings is None or len(recommendations) <= 1:
            return list(recommendations)

        # Map papers to embedding rows.
        cand_idx: List[int] = []
        cand_emb: List[np.ndarray] = []
        cand_scores: List[float] = []
        for p, score in recommendations:
            pid = _safe_id(p)
            idx = self._id_to_idx.get(pid)
            if idx is not None:
                cand_idx.append(idx)
                cand_emb.append(self._embeddings[idx])
            else:
                v = self._encode_query(_paper_text(p))
                cand_idx.append(-1)
                cand_emb.append(v)
            cand_scores.append(float(score))
        cand_emb_arr = np.vstack(cand_emb)

        selected: List[int] = []
        remaining = list(range(len(recommendations)))
        # Greedy MMR.
        while remaining and len(selected) < len(recommendations):
            best_i = -1
            best_mmr = -math.inf
            for i in remaining:
                rel = cand_scores[i]
                if selected:
                    sims = cand_emb_arr[selected] @ cand_emb_arr[i]
                    max_sim = float(np.max(sims))
                else:
                    max_sim = 0.0
                mmr = lambda_param * rel - (1 - lambda_param) * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_i = i
            if best_i < 0:
                break
            selected.append(best_i)
            remaining.remove(best_i)
        return [(recommendations[i][0], recommendations[i][1]) for i in selected]

    # ------------------------------------------------------------------
    # Explanation
    # ------------------------------------------------------------------

    def explain(self, paper: Any, recommended_paper: Any) -> str:
        """Generate a human-readable explanation of a recommendation.

        Args:
            paper: The seed paper.
            recommended_paper: The recommended paper.

        Returns:
            A multi-sentence explanation string.
        """
        self._ensure_index()
        pid_a = _safe_id(paper)
        pid_b = _safe_id(recommended_paper)
        idx_a = self._id_to_idx.get(pid_a)
        idx_b = self._id_to_idx.get(pid_b)
        if (idx_a is not None and idx_b is not None
                and self._embeddings is not None):
            va = self._embeddings[idx_a]
            vb = self._embeddings[idx_b]
            sim = float(np.dot(va, vb))
        else:
            va = self._encode_query(_paper_text(paper))
            vb = self._encode_query(_paper_text(recommended_paper))
            sim = float(np.dot(va, vb))

        # Keyword overlap.
        kw_a = {str(k).lower() for k in (getattr(paper, "keywords", []) or [])}
        kw_b = {str(k).lower() for k in (getattr(recommended_paper, "keywords", []) or [])}
        shared = kw_a & kw_b
        # Shared authors.
        au_a = {str(a).lower() for a in (getattr(paper, "authors", []) or [])}
        au_b = {str(a).lower() for a in (getattr(recommended_paper, "authors", []) or [])}
        shared_authors = au_a & au_b

        reasons: List[str] = []
        reasons.append(
            f"Semantic similarity: {sim:.2f} (cosine in embedding space)."
        )
        if shared:
            reasons.append(
                f"Shares {len(shared)} keyword(s): {', '.join(sorted(shared))}."
            )
        if shared_authors:
            reasons.append(
                f"Shares {len(shared_authors)} author(s): "
                f"{', '.join(sorted(shared_authors))}."
            )
        # Field overlap.
        fos_a = {str(f).lower() for f in (getattr(paper, "fields_of_study", []) or [])}
        fos_b = {str(f).lower() for f in (getattr(recommended_paper, "fields_of_study", []) or [])}
        shared_fos = fos_a & fos_b
        if shared_fos:
            reasons.append(
                f"Same field(s) of study: {', '.join(sorted(shared_fos))}."
            )
        title_a = (getattr(paper, "title", "") or "the seed paper")[:60]
        title_b = (getattr(recommended_paper, "title", "") or "the recommended paper")[:60]
        intro = (f"'{title_b}' was recommended because it is conceptually "
                 f"similar to '{title_a}'.")
        return intro + " " + " ".join(reasons)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        test_set: List[Tuple[Any, Any]],
        metric: str = "ndcg",
        k: int = 10,
    ) -> float:
        """Evaluate recommender quality on a held-out test set.

        Each ``(query_paper, relevant_paper)`` pair is treated as a
        relevance judgment: the query paper is used as the seed, the
        recommender produces a ranked list, and we score whether the
        relevant paper appears in the top-k.

        Args:
            test_set: List of ``(seed_paper, relevant_paper)`` pairs.
            metric: ``"ndcg"`` | ``"precision"`` | ``"recall"``.
            k: Cutoff for top-k metrics.

        Returns:
            The mean metric value across the test set (in ``[0, 1]``).
        """
        if not test_set:
            return 0.0
        metric = (metric or "ndcg").lower()
        scores: List[float] = []
        for seed, relevant in test_set:
            recs = self.recommend_similar(seed, top_k=max(k, 10))
            rel_id = _safe_id(relevant)
            rank = None
            for i, (p, _) in enumerate(recs):
                if _safe_id(p) == rel_id:
                    rank = i + 1
                    break
            if metric == "ndcg":
                if rank is None:
                    scores.append(0.0)
                else:
                    scores.append(1.0 / math.log2(rank + 1))
            elif metric == "precision":
                scores.append(1.0 if rank is not None else 0.0)
            elif metric == "recall":
                # Single relevant item per query => recall = hit.
                scores.append(1.0 if rank is not None else 0.0)
            else:
                raise ValueError(f"Unknown metric: {metric!r}")
        return float(np.mean(scores)) if scores else 0.0


# ---------------------------------------------------------------------------
# Random-embedder fallback (used when sentence-transformers unavailable)
# ---------------------------------------------------------------------------


class _RandomEmbedder:
    """Deterministic hash-based fallback embedder (mock mode)."""

    def __init__(self, dim: int = 384) -> None:
        import hashlib
        self._hashlib = hashlib
        self.dim = int(dim)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return a deterministic pseudo-embedding matrix."""
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            seed = int.from_bytes(
                self._hashlib.sha256(str(t).encode("utf-8")).digest()[:8],
                "little",
            )
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            n = float(np.linalg.norm(v))
            if n > 0:
                v = v / n
            out[i] = v
        return out


__all__ = ["PaperRecommender"]
