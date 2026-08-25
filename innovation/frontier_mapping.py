"""frontier_mapping — knowledge-frontier mapping for the Academic
Research Suite.

A *knowledge frontier* is a region of the research landscape where
work is sparse but actively growing — the conceptual equivalent of the
"edge of the map". Identifying such regions is valuable for
researchers who want to spot emerging fields before they become
crowded, and for funding agencies who want to seed high-potential
areas.

This module implements three complementary approaches:

* :meth:`KnowledgeFrontier.embedding_density_approach` — clusters
  papers in embedding space and identifies sparse boundary regions
  between dense clusters as candidate frontiers.
* :meth:`KnowledgeFrontier.topic_model_boundary_approach` — runs
  LDA / NMF / BERTopic on the corpus and identifies topics that are
  *low-prevalence* but *high-growth-rate* (i.e. new and rising).
* :meth:`KnowledgeFrontier.citation_velocity_approach` — finds papers
  whose citation count has high positive second-derivative (citation
  *acceleration*) over the recent window, treating them as evidence of
  an emerging frontier.

A :class:`FrontierTracker` companion class tracks how frontier regions
evolve year-over-year.

Heavy dependencies (``sentence-transformers``, ``bertopic``, ``umap``)
are imported lazily so the module loads cleanly on minimal installs.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import math
import warnings
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Silence noisy sklearn / numpy warnings that arise from degenerate inputs
# (NMF non-convergence on tiny corpora, PCA divide-by-zero on constant vectors).
# These do not affect correctness — the algorithm falls back gracefully.
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*Maximum number of iterations.*")
warnings.filterwarnings("ignore", message=".*invalid value encountered in divide.*")


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class FrontierRegion:
    """A single detected knowledge-frontier region.

    Attributes:
        id: Stable identifier (e.g. ``"frontier_0"``).
        centroid_embedding: Centroid of the region in embedding space
            (``np.ndarray`` of shape ``(embedding_dim,)``).
        representative_papers: A small set of papers (typically ≤5)
            that exemplify the frontier.
        novelty_score: Novelty in ``[0, 1]`` (1 = very novel).
        growth_rate: Estimated annual growth rate (e.g. ``0.45``
            means ~45% year-over-year growth in paper count).
        neighbor_topics: Indices of nearby dense topics.
        keywords: Top keywords characterizing the frontier.
    """

    id: str = ""
    centroid_embedding: Optional[np.ndarray] = None
    representative_papers: List[Any] = field(default_factory=list)
    novelty_score: float = 0.0
    growth_rate: float = 0.0
    neighbor_topics: List[int] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        d = asdict(self)
        if self.centroid_embedding is not None:
            d["centroid_embedding"] = self.centroid_embedding.tolist()
        d["representative_papers"] = [
            (p.to_dict() if hasattr(p, "to_dict") else p)
            for p in self.representative_papers
        ]
        return d


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
    """Return the concatenated text representation of a paper."""
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
    return " ".join(parts).strip()


def _normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize ``v`` (returns ``v`` unchanged if zero-norm)."""
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _safe_year(p: Any) -> Optional[int]:
    """Return ``int(p.year)`` or ``None``."""
    y = getattr(p, "year", None)
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _year_growth_rate(counts_per_year: Dict[int, int], lookback: int = 3) -> float:
    """Estimate the average annual growth rate over the last ``lookback`` yrs."""
    if not counts_per_year:
        return 0.0
    years = sorted(counts_per_year.keys())
    if len(years) < 2:
        return 0.0
    recent = years[-lookback:] if len(years) >= lookback else years
    vals = [counts_per_year[y] for y in recent]
    rates = []
    for i in range(1, len(vals)):
        prev = max(vals[i - 1], 1)
        rates.append((vals[i] - prev) / prev)
    if not rates:
        return 0.0
    return float(np.mean(rates))


# ---------------------------------------------------------------------------
# KnowledgeFrontier
# ---------------------------------------------------------------------------


class KnowledgeFrontier:
    """Knowledge-frontier mapping on a corpus of papers.

    Provides three complementary approaches for identifying frontier
    regions, plus a temporal tracker. Heavy dependencies are loaded
    lazily.
    """

    DEFAULT_EMBEDDING_DIM = 384

    def __init__(
        self,
        papers: Sequence[Any],
        embeddings_model: Any = None,
    ) -> None:
        """Initialize the frontier mapper.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            embeddings_model: Optional pre-constructed embedder with an
                ``encode(texts) -> np.ndarray`` API. If ``None``, a
                :class:`data_science.embeddings.EmbeddingsModel` is
                constructed lazily on first use.
        """
        self.papers: List[Any] = list(papers)
        self.embeddings_model = embeddings_model
        self._embeddings: Optional[np.ndarray] = None
        self._cluster_labels: Optional[np.ndarray] = None
        self.logger = logger

    # ------------------------------------------------------------------
    # Embeddings (lazy)
    # ------------------------------------------------------------------

    def _get_embedder(self) -> Any:
        """Return the active embedder, constructing one lazily if needed."""
        if self.embeddings_model is not None:
            return self.embeddings_model
        try:
            from data_science.embeddings import EmbeddingsModel  # type: ignore
            self.embeddings_model = EmbeddingsModel()
            return self.embeddings_model
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning(
                "Could not construct EmbeddingsModel (%s); using random "
                "fallback vectors.", exc,
            )
            return _RandomEmbedder(self.DEFAULT_EMBEDDING_DIM)

    def _get_embeddings(self) -> np.ndarray:
        """Return the (cached) embeddings matrix for all papers."""
        if self._embeddings is not None:
            return self._embeddings
        if not self.papers:
            self._embeddings = np.zeros((0, self.DEFAULT_EMBEDDING_DIM),
                                         dtype=np.float32)
            return self._embeddings
        embedder = self._get_embedder()
        texts = [_paper_text(p) or p.title or "empty" for p in self.papers]
        try:
            mat = embedder.encode(texts)
        except Exception as exc:
            self.logger.warning(
                "Embedder.encode failed (%s); using random fallback.", exc)
            mat = _RandomEmbedder(self.DEFAULT_EMBEDDING_DIM).encode(texts)
        mat = np.asarray(mat, dtype=np.float32)
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        # L2-normalize rows for cosine geometry.
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._embeddings = mat / norms
        return self._embeddings

    # ------------------------------------------------------------------
    # Compute frontier (dispatch)
    # ------------------------------------------------------------------

    def compute_frontier(
        self,
        method: str = "embedding_density",
        top_n: int = 10,
        **kwargs: Any,
    ) -> List[FrontierRegion]:
        """Detect frontier regions using the requested method.

        Args:
            method: ``"embedding_density"`` | ``"topic_model_boundary"``
                | ``"citation_velocity"``.
            top_n: Maximum number of frontier regions to return.
            **kwargs: Method-specific hyperparameters.

        Returns:
            A list of :class:`FrontierRegion` sorted by novelty score
            (descending).
        """
        method = (method or "").lower()
        if method == "embedding_density":
            regions = self.embedding_density_approach(**kwargs)
        elif method == "topic_model_boundary":
            regions = self.topic_model_boundary_approach(**kwargs)
        elif method == "citation_velocity":
            regions = self.citation_velocity_approach(**kwargs)
        else:
            raise ValueError(f"Unknown frontier method: {method!r}")
        regions = sorted(regions, key=lambda r: r.novelty_score, reverse=True)
        return regions[:top_n]

    # ------------------------------------------------------------------
    # Method 1: embedding density
    # ------------------------------------------------------------------

    def embedding_density_approach(
        self,
        n_clusters: int = 8,
        boundary_quantile: float = 0.10,
        min_papers: int = 2,
    ) -> List[FrontierRegion]:
        """Cluster papers in embedding space and identify sparse boundary regions.

        The intuition: dense clusters represent well-established research
        areas. Frontier regions live *between* clusters where papers
        are sparse but not noise. We compute a k-NN density estimate,
        flag the lowest-density papers as "boundary" papers, cluster
        *those* via agglomerative clustering, and treat each resulting
        micro-cluster as a frontier region.

        Args:
            n_clusters: Number of k-means clusters used to characterize
                "established" areas.
            boundary_quantile: Fraction of lowest-density papers to
                treat as boundary candidates.
            min_papers: Minimum papers per frontier region.

        Returns:
            List of :class:`FrontierRegion`.
        """
        if len(self.papers) < 4:
            return []
        from sklearn.cluster import KMeans, AgglomerativeClustering  # lazy
        from sklearn.metrics import pairwise_distances  # lazy

        emb = self._get_embeddings()
        n_clusters = max(2, min(n_clusters, len(self.papers) - 1))

        # k-NN density: mean distance to the 5 nearest neighbors.
        k = min(5, len(self.papers) - 1)
        dists = pairwise_distances(emb, emb, metric="cosine")
        np.fill_diagonal(dists, np.inf)
        knn = np.sort(dists, axis=1)[:, :k]
        density = knn.mean(axis=1)
        # Higher density -> lower value (closer neighbors).
        threshold = np.quantile(density, boundary_quantile)
        boundary_idx = np.where(density <= threshold)[0]
        if len(boundary_idx) < min_papers:
            # Invert: take highest-density papers if no sparse boundary.
            order = np.argsort(-density)
            boundary_idx = order[:max(min_papers, len(order) // 5)]

        # Cluster the dense regions to find "established" centroids.
        dense_idx = np.setdiff1d(np.arange(len(self.papers)), boundary_idx)
        if len(dense_idx) < n_clusters:
            dense_idx = np.arange(len(self.papers))
        try:
            km = KMeans(n_clusters=min(n_clusters, len(dense_idx)),
                         n_init=4, random_state=42)
            km.fit(emb[dense_idx])
            centroids = km.cluster_centers_
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("KMeans failed: %s", exc)
            return []

        # Micro-cluster the boundary papers.
        n_sub = max(2, min(len(boundary_idx) // max(1, min_papers), 8))
        try:
            agg = AgglomerativeClustering(
                n_clusters=n_sub, metric="cosine", linkage="average",
            )
            sub_labels = agg.fit_predict(emb[boundary_idx])
        except Exception as exc:
            self.logger.warning("Agglomerative clustering failed: %s", exc)
            return []

        regions: List[FrontierRegion] = []
        for sub_id in range(n_sub):
            mask = sub_labels == sub_id
            if mask.sum() < 1:
                continue
            idx = boundary_idx[mask]
            if len(idx) < 1:
                continue
            centroid = emb[idx].mean(axis=0)
            centroid = _normalize(centroid)
            # Novelty: inversely proportional to mean density of papers
            # in this micro-cluster (sparser = more novel).
            local_density = density[idx].mean()
            global_mean = float(density.mean()) or 1.0
            novelty = float(min(1.0, max(0.0, local_density / global_mean)))
            # Growth rate: fraction of papers in last 3 years.
            recent_frac = self._recent_fraction(idx.tolist())
            growth = float(recent_frac)
            # Neighbor topics: closest dense centroids.
            cos = (centroids @ centroid)
            neighbor_topics = list(np.argsort(-cos)[:5].tolist())
            # Keywords: top 5 most frequent keywords among boundary papers.
            kws = self._top_keywords(idx.tolist(), 5)
            regions.append(FrontierRegion(
                id=f"frontier_emb_{len(regions)}",
                centroid_embedding=centroid,
                representative_papers=[self.papers[i] for i in idx[:5]],
                novelty_score=novelty,
                growth_rate=growth,
                neighbor_topics=neighbor_topics,
                keywords=kws,
            ))
        return regions

    # ------------------------------------------------------------------
    # Method 2: topic model boundary
    # ------------------------------------------------------------------

    def topic_model_boundary_approach(
        self,
        n_topics: int = 12,
        min_prevalence: float = 0.02,
        max_prevalence: float = 0.15,
        lookback_years: int = 3,
        method: str = "nmf",
    ) -> List[FrontierRegion]:
        """Run a topic model and find low-prevalence, high-growth topics.

        Args:
            n_topics: Number of topics to fit.
            min_prevalence: Minimum fraction of documents assigned to a
                topic for it to be a candidate frontier.
            max_prevalence: Maximum fraction (above this the topic is
                considered established, not frontier).
            lookback_years: Window for growth-rate computation.
            method: Topic-model backend (``"nmf"`` / ``"lda"`` /
                ``"bertopic"``).

        Returns:
            List of :class:`FrontierRegion`.
        """
        if len(self.papers) < 8:
            return []
        try:
            from data_science.topic_modeler import TopicModeler  # type: ignore
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("TopicModeler unavailable (%s).", exc)
            return []

        n_topics = max(2, min(n_topics, max(2, len(self.papers) // 5)))
        try:
            tm = TopicModeler(method=method, n_top_words=8)
            topic_model = tm.fit(self.papers, num_topics=n_topics)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Topic model fit failed (%s).", exc)
            return []

        doc_topic = getattr(topic_model, "doc_topic_matrix", None)
        if doc_topic is None or doc_topic.shape[0] != len(self.papers):
            return []

        # Assign each paper to its dominant topic.
        dominant = np.argmax(doc_topic, axis=1)
        total = len(self.papers)
        regions: List[FrontierRegion] = []
        emb = self._get_embeddings()
        topics_meta = getattr(topic_model, "topics", []) or []
        for t in range(doc_topic.shape[1]):
            mask = dominant == t
            n_t = int(mask.sum())
            prev = n_t / total if total > 0 else 0.0
            if not (min_prevalence <= prev <= max_prevalence):
                continue
            idx = np.where(mask)[0]
            if len(idx) == 0:
                continue
            centroid = emb[idx].mean(axis=0) if emb.size else np.zeros(
                self.DEFAULT_EMBEDDING_DIM, dtype=np.float32)
            centroid = _normalize(centroid)
            # Growth rate: year-over-year growth in topic assignment.
            counts_per_year: Dict[int, int] = {}
            for i in idx:
                y = _safe_year(self.papers[i])
                if y is not None:
                    counts_per_year[y] = counts_per_year.get(y, 0) + 1
            growth = _year_growth_rate(counts_per_year, lookback_years)
            # Novelty: combination of low prevalence and high growth.
            novelty = float(min(1.0, max(0.0,
                (1.0 - prev / max_prevalence) * 0.5 +
                min(growth, 1.0) * 0.5
            )))
            meta = topics_meta[t] if t < len(topics_meta) else {}
            kws = list(meta.get("top_words", []))[:5]
            regions.append(FrontierRegion(
                id=f"frontier_topic_{t}",
                centroid_embedding=centroid,
                representative_papers=[self.papers[i] for i in idx[:5]],
                novelty_score=novelty,
                growth_rate=growth,
                neighbor_topics=[],
                keywords=kws,
            ))
        return regions

    # ------------------------------------------------------------------
    # Method 3: citation velocity
    # ------------------------------------------------------------------

    def citation_velocity_approach(
        self,
        recent_years: int = 3,
        min_papers_per_year: int = 3,
        top_n: int = 10,
    ) -> List[FrontierRegion]:
        """Identify frontier papers by citation acceleration.

        For each year ``y`` and each paper published in year ``y``, we
        compute the *citation acceleration* — the second difference of
        the paper's cumulative citation curve (approximated by a ramp
        since publication year, as in
        :class:`innovation.citation_bursts.CitationBurstDetector`).
        Papers with high positive acceleration signal an emerging
        frontier; we group them by keyword co-occurrence to form
        frontier regions.

        Args:
            recent_years: Only consider papers published in the last
                ``recent_years`` years.
            min_papers_per_year: Minimum distinct papers per year to
                consider that year.
            top_n: Maximum number of frontier regions to return.

        Returns:
            List of :class:`FrontierRegion`.
        """
        if not self.papers:
            return []
        years = [y for y in (_safe_year(p) for p in self.papers) if y is not None]
        if not years:
            return []
        max_year = max(years)
        cutoff = max_year - recent_years
        recent_papers = [p for p in self.papers
                          if (_safe_year(p) or 0) >= cutoff]
        if len(recent_papers) < min_papers_per_year:
            return []

        # Acceleration: proxy = citations_count / years_since_publication.
        accels: List[Tuple[float, int]] = []
        for i, p in enumerate(recent_papers):
            y = _safe_year(p)
            if y is None or y > max_year:
                continue
            age = max(1, max_year - y + 1)
            cit = int(getattr(p, "citations_count", 0) or 0)
            accel = cit / (age * age)  # acceleration proxy
            accels.append((accel, i))
        accels.sort(reverse=True)
        top_idx = [i for _, i in accels[:top_n * 3]]

        if not top_idx:
            return []

        # Group by shared keywords.
        groups: Dict[str, List[int]] = {}
        for i in top_idx:
            p = recent_papers[i]
            kws = getattr(p, "keywords", []) or []
            if not kws:
                kws = ["__no_keyword__"]
            primary_kw = str(kws[0])
            groups.setdefault(primary_kw, []).append(i)

        emb = self._get_embeddings()
        # Build a paper-index map from self.papers to emb row.
        id_to_emb_idx = {id(p): k for k, p in enumerate(self.papers)}

        regions: List[FrontierRegion] = []
        for kw, paper_indices in sorted(groups.items(),
                                          key=lambda kv: -len(kv[1])):
            if len(paper_indices) < 2:
                continue
            # Map back to self.papers indices to fetch embeddings.
            emb_idxs = [id_to_emb_idx[id(recent_papers[i])]
                          for i in paper_indices
                          if id(recent_papers[i]) in id_to_emb_idx]
            if not emb_idxs:
                continue
            centroid = emb[emb_idxs].mean(axis=0)
            centroid = _normalize(centroid)
            # Novelty: 1 - fraction of total papers with this keyword.
            total_with_kw = sum(
                1 for p in self.papers
                if any(str(k) == kw for k in (getattr(p, "keywords", []) or []))
            )
            novelty = 1.0 - min(1.0, total_with_kw / max(1, len(self.papers)))
            # Growth: fraction of recent papers among those with this kw.
            recent_with_kw = len(paper_indices)
            growth = recent_with_kw / max(1, total_with_kw)
            regions.append(FrontierRegion(
                id=f"frontier_vel_{len(regions)}",
                centroid_embedding=centroid,
                representative_papers=[recent_papers[i] for i in paper_indices[:5]],
                novelty_score=float(novelty),
                growth_rate=float(growth),
                neighbor_topics=[],
                keywords=[kw],
            ))
            if len(regions) >= top_n:
                break
        return regions

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize(
        self,
        method: str = "tsne",
        figsize: Tuple[int, int] = (12, 10),
        regions: Optional[List[FrontierRegion]] = None,
    ) -> Any:
        """Render a 2-D scatter of papers with frontier regions highlighted.

        Args:
            method: ``"tsne"`` | ``"umap"`` | ``"pca"`` (UMAP is used if
                installed, otherwise falls back to PCA).
            figsize: Figure size.
            regions: Optional pre-computed frontier regions to highlight.
                If ``None``, runs :meth:`compute_frontier` first.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        _configure_fonts()

        if regions is None:
            regions = self.compute_frontier()

        emb = self._get_embeddings()
        if len(emb) == 0:
            fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
            ax.text(0.5, 0.5, "No papers to visualize",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig

        coords = self._reduce_dims(emb, method)

        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        ax.scatter(coords[:, 0], coords[:, 1],
                    s=10, c="lightgray", alpha=0.5, label="papers")

        frontier_idx: set = set()
        for region in regions:
            for p in region.representative_papers:
                try:
                    frontier_idx.add(id(p))
                except Exception:  # pragma: no cover - defensive
                    pass

        # Highlight frontier papers in red.
        frontier_pts = []
        for i, p in enumerate(self.papers):
            if id(p) in frontier_idx:
                frontier_pts.append(i)
        if frontier_pts:
            pts = coords[frontier_pts]
            ax.scatter(pts[:, 0], pts[:, 1], s=60, c="red",
                       edgecolors="darkred", linewidths=0.8,
                       label="frontier papers")

        # Annotate frontier region centroids.
        for region in regions:
            if region.centroid_embedding is None:
                continue
            cent = self._reduce_dims(
                region.centroid_embedding.reshape(1, -1), method,
            )
            kw_label = ", ".join(region.keywords[:3]) or region.id
            ax.scatter(cent[0, 0], cent[0, 1], marker="*",
                       s=300, c="gold", edgecolors="black",
                       linewidths=1.0, zorder=5)
            ax.annotate(
                kw_label, (cent[0, 0], cent[0, 1]),
                fontsize=8, ha="left", va="bottom",
                xytext=(5, 5), textcoords="offset points",
            )

        ax.set_title(f"Knowledge frontier map ({method})")
        ax.set_xlabel(f"{method}-1")
        ax.set_ylabel(f"{method}-2")
        ax.legend(loc="best", fontsize=8)
        return fig

    def _reduce_dims(self, emb: np.ndarray, method: str) -> np.ndarray:
        """Project embeddings to 2-D using the requested method."""
        method = (method or "pca").lower()
        if method == "umap":
            try:
                import umap  # type: ignore
                reducer = umap.UMAP(n_components=2, random_state=42)
                return reducer.fit_transform(emb)
            except Exception as exc:
                self.logger.warning(
                    "UMAP unavailable (%s); falling back to PCA.", exc)
                method = "pca"
        if method == "tsne":
            try:
                from sklearn.manifold import TSNE  # lazy
                perplexity = max(2, min(30, len(emb) - 1))
                tsne = TSNE(n_components=2, perplexity=perplexity,
                             random_state=42, init="pca",
                             learning_rate="auto")
                return tsne.fit_transform(emb)
            except Exception as exc:
                self.logger.warning(
                    "t-SNE failed (%s); falling back to PCA.", exc)
                method = "pca"
        # Default: PCA.
        from sklearn.decomposition import PCA  # lazy
        n_comp = min(2, emb.shape[1], max(1, emb.shape[0] - 1))
        pca = PCA(n_components=n_comp, random_state=42)
        result = pca.fit_transform(emb)
        if result.shape[1] < 2:
            result = np.hstack([result, np.zeros((len(result), 2 - result.shape[1]))])
        return result

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot of this frontier mapper."""
        return {
            "num_papers": len(self.papers),
            "has_embeddings": self._embeddings is not None,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _recent_fraction(self, indices: Sequence[int], lookback: int = 3) -> float:
        """Fraction of ``indices`` whose paper is from the last ``lookback`` years."""
        years = [y for y in (_safe_year(self.papers[i]) for i in indices)
                  if y is not None]
        if not years:
            return 0.0
        max_y = max(years)
        cutoff = max_y - lookback + 1
        recent = sum(1 for y in years if y >= cutoff)
        return recent / len(years)

    def _top_keywords(self, indices: Sequence[int], top_n: int = 5) -> List[str]:
        """Return the ``top_n`` most common keywords among the given papers."""
        from collections import Counter
        c: Counter = Counter()
        for i in indices:
            kws = getattr(self.papers[i], "keywords", []) or []
            c.update(str(k) for k in kws if k)
        return [k for k, _ in c.most_common(top_n)]


# ---------------------------------------------------------------------------
# FrontierTracker
# ---------------------------------------------------------------------------


class FrontierTracker:
    """Tracks the evolution of frontier regions year over year.

    The tracker accepts a per-year mapping of paper lists and runs
    :class:`KnowledgeFrontier` on each year, then matches frontier
    regions across consecutive years by embedding centroid similarity.
    """

    def __init__(
        self,
        papers_per_year: Dict[int, Sequence[Any]],
        embeddings_model: Any = None,
    ) -> None:
        """Initialize the tracker.

        Args:
            papers_per_year: Mapping ``year -> list of papers``.
            embeddings_model: Optional shared embedder.
        """
        self.papers_per_year: Dict[int, List[Any]] = {
            int(y): list(p) for y, p in (papers_per_year or {}).items()
        }
        self.embeddings_model = embeddings_model
        self.logger = logger
        self._cache: Dict[int, List[FrontierRegion]] = {}

    def _frontiers_for_year(self, year: int) -> List[FrontierRegion]:
        """Return (cached) frontier regions for a given year."""
        year = int(year)
        if year in self._cache:
            return self._cache[year]
        papers = self.papers_per_year.get(year, [])
        if not papers:
            self._cache[year] = []
            return []
        kf = KnowledgeFrontier(papers, embeddings_model=self.embeddings_model)
        regions = kf.compute_frontier()
        self._cache[year] = regions
        return regions

    def track_over_time(self, years: Optional[Sequence[int]] = None) -> Any:
        """Return a dataframe describing frontier evolution.

        Args:
            years: Optional subset of years to track. Defaults to all
                years present in :attr:`papers_per_year`.

        Returns:
            ``pandas.DataFrame`` with one row per (year, frontier)
            pair and columns ``year``, ``frontier_id``, ``novelty``,
            ``growth``, ``keywords``, ``matched_prev_year`` (bool).
        """
        import pandas as pd  # lazy
        years = sorted(years) if years else sorted(self.papers_per_year.keys())
        rows: List[Dict[str, Any]] = []
        prev_regions: List[FrontierRegion] = []
        for y in years:
            regions = self._frontiers_for_year(y)
            for r in regions:
                matched = False
                if r.centroid_embedding is not None and prev_regions:
                    for pr in prev_regions:
                        if pr.centroid_embedding is None:
                            continue
                        sim = float(np.dot(r.centroid_embedding,
                                            pr.centroid_embedding))
                        if sim >= 0.7:
                            matched = True
                            break
                rows.append({
                    "year": y,
                    "frontier_id": r.id,
                    "novelty": r.novelty_score,
                    "growth": r.growth_rate,
                    "keywords": ", ".join(r.keywords),
                    "matched_prev_year": matched,
                })
            prev_regions = regions
        return pd.DataFrame(rows)

    def emerging_topics(
        self,
        year: int,
        lookback: int = 3,
    ) -> List[FrontierRegion]:
        """Return frontiers that emerged in ``year`` (absent in prior years).

        Args:
            year: The target year.
            lookback: Number of prior years to compare against.

        Returns:
            List of :class:`FrontierRegion` present in ``year`` but not
            matched to any region in ``year-lookback`` … ``year-1``.
        """
        year = int(year)
        current = self._frontiers_for_year(year)
        if not current:
            return []
        prior: List[FrontierRegion] = []
        for y in range(year - lookback, year):
            prior.extend(self._frontiers_for_year(y))
        if not prior:
            return list(current)
        emerging: List[FrontierRegion] = []
        for r in current:
            if r.centroid_embedding is None:
                continue
            best_sim = 0.0
            for pr in prior:
                if pr.centroid_embedding is None:
                    continue
                sim = float(np.dot(r.centroid_embedding, pr.centroid_embedding))
                if sim > best_sim:
                    best_sim = sim
            if best_sim < 0.7:
                emerging.append(r)
        return emerging

    def fading_topics(
        self,
        year: int,
        lookback: int = 3,
    ) -> List[FrontierRegion]:
        """Return frontiers that disappeared by ``year``.

        Args:
            year: The target year.
            lookback: Number of prior years to scan for now-absent topics.

        Returns:
            List of :class:`FrontierRegion` present in any of
            ``year-lookback`` … ``year-1`` but with no match in ``year``.
        """
        year = int(year)
        current = self._frontiers_for_year(year)
        prior: List[FrontierRegion] = []
        for y in range(year - lookback, year):
            prior.extend(self._frontiers_for_year(y))
        if not prior:
            return []
        fading: List[FrontierRegion] = []
        for pr in prior:
            if pr.centroid_embedding is None:
                continue
            best_sim = 0.0
            for r in current:
                if r.centroid_embedding is None:
                    continue
                sim = float(np.dot(pr.centroid_embedding, r.centroid_embedding))
                if sim > best_sim:
                    best_sim = sim
            if best_sim < 0.7:
                fading.append(pr)
        # Deduplicate by id (since prior covers multiple years).
        seen: set = set()
        unique: List[FrontierRegion] = []
        for r in fading:
            if r.id not in seen:
                seen.add(r.id)
                unique.append(r)
        return unique


# ---------------------------------------------------------------------------
# Random-embedder fallback (used when sentence-transformers unavailable)
# ---------------------------------------------------------------------------


class _RandomEmbedder:
    """Deterministic hash-based fallback embedder (mock mode).

    Used only when ``EmbeddingsModel`` cannot be constructed and no
    explicit embedder was supplied.
    """

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


__all__ = [
    "FrontierRegion",
    "KnowledgeFrontier",
    "FrontierTracker",
]
