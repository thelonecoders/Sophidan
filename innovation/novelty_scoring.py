"""novelty_scoring — paper & topic novelty scoring for the Academic
Research Suite.

Implements three well-known novelty / disruption metrics from the
science-of-science literature:

* **Novelty score** (composite) — local outlier factor over paper
  embeddings (a paper is novel if it sits in a sparse region of
  embedding space).
* **Atypicality score** (Uzzi et al. 2013) — based on the rarity of a
  paper's *journal-pair* / *keyword-pair* combinations, computed as a
  z-score against a randomization baseline.
* **Disruption index (CD index)** (Funk & Owen-Smith 2017) — based
  on the citation graph of the focal paper and its citing / cited
  works. A positive index means the paper "disrupts" its field;
  negative means it "reinforces" existing work.

Also exposes convenience rankers and matplotlib visualizations
(distribution histogram + per-paper radar chart).
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

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class NoveltyScore:
    """Novelty scoring result for a single paper.

    Attributes:
        paper_id: Stable identifier (DOI or title).
        paper_title: Display title.
        novelty_score: Overall novelty in ``[0, 1]``.
        atypicality_score: Uzzi-style atypicality z-score mapped to
            ``[0, 1]`` (higher = more atypical).
        disruption_index: Funk & Owen-Smith CD index in ``[-1, 1]``
            (positive = disruptive).
        related_papers: Papers closely related to the focal paper
            (typically the k-NN neighborhood).
        closest_neighbors: ``[(paper, similarity)]`` pairs for the
            closest neighbors (used by the radar visualization).
        percentile: Novelty percentile in ``[0, 100]``.
    """

    paper_id: str = ""
    paper_title: str = ""
    novelty_score: float = 0.0
    atypicality_score: float = 0.0
    disruption_index: float = 0.0
    related_papers: List[Any] = field(default_factory=list)
    closest_neighbors: List[Tuple[Any, float]] = field(default_factory=list)
    percentile: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        d = asdict(self)
        d["related_papers"] = [
            (p.to_dict() if hasattr(p, "to_dict") else p)
            for p in self.related_papers
        ]
        d["closest_neighbors"] = [
            {"paper": (p.to_dict() if hasattr(p, "to_dict") else p),
             "similarity": float(s)}
            for p, s in self.closest_neighbors
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


def _safe_id(p: Any) -> str:
    """Stable identifier for a paper."""
    return str(getattr(p, "doi", None) or getattr(p, "title", None) or id(p))


def _safe_year(p: Any) -> Optional[int]:
    """Return ``int(p.year)`` or ``None``."""
    y = getattr(p, "year", None)
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize ``v`` row-wise (returns ``v`` unchanged for zero rows)."""
    if v.ndim == 1:
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


# ---------------------------------------------------------------------------
# NoveltyScorer
# ---------------------------------------------------------------------------


class NoveltyScorer:
    """Multi-dimensional novelty scorer."""

    DEFAULT_EMBEDDING_DIM = 384

    def __init__(
        self,
        papers: Sequence[Any],
        embedder: Any = None,
    ) -> None:
        """Initialize the scorer.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            embedder: Optional embedder with an ``encode(texts)`` method.
                If ``None``, a default :class:`EmbeddingsModel` is
                constructed lazily on first use.
        """
        self.papers: List[Any] = list(papers)
        self.embedder = embedder
        self._embeddings: Optional[np.ndarray] = None
        self._paper_ids: List[str] = [_safe_id(p) for p in self.papers]
        self._id_to_idx: Dict[str, int] = {
            pid: i for i, pid in enumerate(self._paper_ids) if pid
        }
        self.logger = logger

    # ------------------------------------------------------------------
    # Embeddings (lazy)
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

    def _get_embeddings(self) -> np.ndarray:
        """Return (cached) embeddings for all papers, L2-normalized."""
        if self._embeddings is not None:
            return self._embeddings
        if not self.papers:
            self._embeddings = np.zeros((0, self.DEFAULT_EMBEDDING_DIM),
                                         dtype=np.float32)
            return self._embeddings
        embedder = self._get_embedder()
        texts = [_paper_text(p) for p in self.papers]
        try:
            mat = embedder.encode(texts)
        except Exception as exc:
            self.logger.warning("Embedding failed (%s); random fallback.", exc)
            mat = _RandomEmbedder(self.DEFAULT_EMBEDDING_DIM).encode(texts)
        mat = np.asarray(mat, dtype=np.float32)
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        self._embeddings = _l2_normalize(mat)
        return self._embeddings

    # ------------------------------------------------------------------
    # Public scoring methods
    # ------------------------------------------------------------------

    def score_paper(self, paper: Any) -> NoveltyScore:
        """Compute the full novelty score for a single paper.

        Args:
            paper: A :class:`Paper`-like object.

        Returns:
            A :class:`NoveltyScore`.
        """
        if not self.papers:
            return NoveltyScore(
                paper_id=_safe_id(paper),
                paper_title=getattr(paper, "title", "") or "",
            )
        emb = self._get_embeddings()
        pid = _safe_id(paper)
        idx = self._id_to_idx.get(pid)
        if idx is None:
            # Out-of-corpus paper: encode on the fly.
            vec = self._encode_single(_paper_text(paper))
            # Compute novelty relative to corpus.
            return self._score_against(paper, vec, emb)

        # In-corpus paper.
        vec = emb[idx]
        return self._score_against(paper, vec, emb, focal_idx=idx)

    def _encode_single(self, text: str) -> np.ndarray:
        """Encode a single text and L2-normalize."""
        embedder = self._get_embedder()
        try:
            v = embedder.encode([text])
            v = np.asarray(v, dtype=np.float32)
            if v.ndim == 1:
                v = v.reshape(1, -1)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Encoding failed (%s); random fallback.", exc)
            v = _RandomEmbedder(self.DEFAULT_EMBEDDING_DIM).encode([text])
        return _l2_normalize(v)[0]

    def _score_against(
        self,
        paper: Any,
        vec: np.ndarray,
        emb: np.ndarray,
        focal_idx: Optional[int] = None,
    ) -> NoveltyScore:
        """Compute the composite novelty score for ``paper``."""
        # Closest neighbors (k-NN).
        k = min(5, max(1, len(emb) - 1))
        if focal_idx is not None:
            sims = emb @ vec
            sims[focal_idx] = -np.inf  # exclude self
        else:
            sims = emb @ vec
        order = np.argsort(-sims)[:k]
        neighbors: List[Tuple[Any, float]] = [
            (self.papers[int(i)], float(sims[int(i)])) for i in order
        ]
        # Local density: mean distance to k-NN (higher = sparser = more novel).
        knn_sims = np.array([s for _, s in neighbors]) if neighbors else np.zeros(0)
        if len(knn_sims) > 0:
            avg_sim = float(np.mean(knn_sims))
            # Novelty = 1 - avg_sim (in [0, 2]); clip to [0, 1].
            novelty = float(max(0.0, min(1.0, 1.0 - avg_sim)))
        else:
            novelty = 0.5

        # Atypicality: z-score of pair combinations.
        atypicality = self._atypicality_for(paper)
        # Disruption index: needs citing papers; if none provided,
        # we approximate via the paper's references.
        citing_papers = self._find_citing_papers(paper)
        disruption = self.disruption_index(paper, citing_papers)
        # Percentile: novelty vs the rest of the corpus.
        all_novelties = self._all_novelties(emb)
        percentile = self._percentile(novelty, all_novelties)

        return NoveltyScore(
            paper_id=_safe_id(paper),
            paper_title=getattr(paper, "title", "") or "",
            novelty_score=novelty,
            atypicality_score=float(max(0.0, min(1.0, atypicality))),
            disruption_index=float(max(-1.0, min(1.0, disruption))),
            related_papers=[p for p, _ in neighbors[:3]],
            closest_neighbors=neighbors,
            percentile=float(percentile),
        )

    def _all_novelties(self, emb: np.ndarray) -> np.ndarray:
        """Compute the novelty score (1 - mean k-NN similarity) for every paper."""
        if len(emb) == 0:
            return np.zeros(0, dtype=np.float32)
        k = min(5, max(1, len(emb) - 1))
        # Pairwise cosine similarity.
        sim = emb @ emb.T
        np.fill_diagonal(sim, -np.inf)
        # Top-k mean similarity per row.
        top_k = np.sort(sim, axis=1)[:, -k:]
        avg_sim = top_k.mean(axis=1)
        novelty = np.clip(1.0 - avg_sim, 0.0, 1.0)
        return novelty.astype(np.float32)

    @staticmethod
    def _percentile(value: float, all_values: np.ndarray) -> float:
        """Return the percentile of ``value`` within ``all_values``."""
        if len(all_values) == 0:
            return 50.0
        rank = float(np.sum(all_values <= value)) / len(all_values)
        return rank * 100.0

    def _find_citing_papers(self, paper: Any) -> List[Any]:
        """Return the list of papers that cite ``paper`` (by DOI matching)."""
        pid = _safe_id(paper)
        citing: List[Any] = []
        for p in self.papers:
            refs = getattr(p, "references", []) or []
            if not refs:
                continue
            if any(str(r) == pid or pid in str(r) for r in refs):
                citing.append(p)
        return citing

    def score_topic(
        self,
        topic: str,
        papers: Optional[Sequence[Any]] = None,
    ) -> NoveltyScore:
        """Compute the novelty of a topic (collection of papers).

        Aggregates per-paper novelty into a topic-level score by
        averaging.

        Args:
            topic: Topic label (used as the ``paper_id`` / ``paper_title``).
            papers: Papers belonging to the topic. If ``None``, all
                papers in :attr:`papers` that mention ``topic`` are used.

        Returns:
            A :class:`NoveltyScore` describing the topic.
        """
        if papers is None:
            topic_lower = topic.lower()
            papers = [
                p for p in self.papers
                if topic_lower in [str(k).lower() for k in (getattr(p, "keywords", []) or [])]
                or topic_lower in [str(f).lower() for f in (getattr(p, "fields_of_study", []) or [])]
                or topic_lower in (getattr(p, "title", "") or "").lower()
            ]
        if not papers:
            return NoveltyScore(paper_id=topic, paper_title=topic)
        scores: List[float] = []
        atyp: List[float] = []
        disrupt: List[float] = []
        for p in papers:
            s = self.score_paper(p)
            scores.append(s.novelty_score)
            atyp.append(s.atypicality_score)
            disrupt.append(s.disruption_index)
        novelty = float(np.mean(scores))
        # Percentile relative to the full corpus.
        emb = self._get_embeddings()
        all_novelties = self._all_novelties(emb)
        return NoveltyScore(
            paper_id=topic,
            paper_title=topic,
            novelty_score=novelty,
            atypicality_score=float(np.mean(atyp)) if atyp else 0.0,
            disruption_index=float(np.mean(disrupt)) if disrupt else 0.0,
            related_papers=list(papers)[:5],
            closest_neighbors=[],
            percentile=self._percentile(novelty, all_novelties),
        )

    # ------------------------------------------------------------------
    # Disruption index (CD index, Funk & Owen-Smith 2017)
    # ------------------------------------------------------------------

    def disruption_index(
        self,
        paper: Any,
        citing_papers: Sequence[Any],
    ) -> float:
        """Compute the Funk & Owen-Smith disruption index (CD index).

        Definitions (where ``focal`` is the paper under analysis):

        * **i** = number of citing papers that reference ``focal`` AND
          at least one of ``focal``'s references (i.e. they look both
          forward and backward through ``focal``).
        * **j** = number of citing papers that reference ``focal`` but
          NOT any of ``focal``'s references.
        * **k** = number of ``focal``'s references that are also cited
          by any of the citing papers (links from citing papers back to
          ``focal``'s references).

        Disruption index ``CD = (j - i) / (i + j + k)``.

        A positive value means ``focal`` disrupts the field (citing
        papers cite ``focal`` but not its references); negative means
        it reinforces (citing papers cite ``focal`` *and* its
        references).

        Args:
            paper: The focal paper.
            citing_papers: Papers that cite ``paper``.

        Returns:
            Disruption index in ``[-1, 1]``.
        """
        focal_refs = set(str(r) for r in (getattr(paper, "references", []) or []))
        if not focal_refs:
            focal_refs = set()
        i_count = 0  # citing papers that cite focal AND a focal reference
        j_count = 0  # citing papers that cite focal but NOT a focal reference
        k_count = 0  # number of focal refs cited by any citing paper

        if not citing_papers:
            return 0.0

        focal_ref_citation_count: Dict[str, int] = {r: 0 for r in focal_refs}
        for cp in citing_papers:
            cp_refs = set(str(r) for r in (getattr(cp, "references", []) or []))
            cites_focal_ref = focal_refs & cp_refs
            if cites_focal_ref:
                i_count += 1
                for r in cites_focal_ref:
                    focal_ref_citation_count[r] = (
                        focal_ref_citation_count.get(r, 0) + 1
                    )
            else:
                j_count += 1
        # k = total (summed over focal refs) of citations from citing papers
        k_count = sum(focal_ref_citation_count.values())
        denom = i_count + j_count + k_count
        if denom == 0:
            return 0.0
        return (j_count - i_count) / denom

    # ------------------------------------------------------------------
    # Atypicality score (Uzzi et al. 2013)
    # ------------------------------------------------------------------

    def atypicality_score(
        self,
        paper: Any,
        all_papers: Optional[Sequence[Any]] = None,
    ) -> float:
        """Compute the Uzzi-style atypicality z-score for a paper.

        Following Uzzi et al. (2013, "Atypical Combinations and
        Scientific Impact"), we measure how *uncommon* a paper's
        journal-pair and keyword-pair combinations are, compared to a
        randomization baseline where the same pairs are reshuffled
        across the corpus.

        We approximate the z-score by:

        1. Counting observed pair frequencies in the focal paper.
        2. Computing the expected frequency under random pairings
           (proportional to the product of single-element frequencies).
        3. ``z = (observed - expected) / std(expected)``.

        Higher z (less negative) means more conventional; lower z
        (more negative) means more atypical. We then map the z-score
        to ``[0, 1]`` via a sigmoid so that "more atypical" → higher
        returned value.

        Args:
            paper: The focal paper.
            all_papers: Corpus to compute background frequencies from
                (defaults to :attr:`papers`).

        Returns:
            Atypicality score in ``[0, 1]`` (1 = highly atypical).
        """
        if all_papers is None:
            all_papers = self.papers
        # Build background frequencies of single elements.
        elem_count: Dict[str, int] = {}
        pair_observed: Dict[str, int] = {}
        total_pairs = 0
        for p in all_papers:
            elements = self._paper_elements(p)
            for el in elements:
                elem_count[el] = elem_count.get(el, 0) + 1
            for i in range(len(elements)):
                for j in range(i + 1, len(elements)):
                    key = tuple(sorted([elements[i], elements[j]]))
                    pair_key = f"{key[0]}|{key[1]}"
                    pair_observed[pair_key] = pair_observed.get(pair_key, 0) + 1
                    total_pairs += 1
        if total_pairs == 0:
            return 0.5
        total_elements = sum(elem_count.values()) or 1
        # Focal paper's observed pair z-scores.
        focal_elements = self._paper_elements(paper)
        focal_pairs: List[Tuple[str, str]] = []
        for i in range(len(focal_elements)):
            for j in range(i + 1, len(focal_elements)):
                focal_pairs.append(tuple(sorted([focal_elements[i], focal_elements[j]])))
        if not focal_pairs:
            return 0.5
        z_list: List[float] = []
        for pair in focal_pairs:
            pair_key = f"{pair[0]}|{pair[1]}"
            obs = pair_observed.get(pair_key, 0)
            p_a = elem_count.get(pair[0], 0) / total_elements
            p_b = elem_count.get(pair[1], 0) / total_elements
            expected = p_a * p_b * total_pairs
            # Poisson-like std: sqrt(expected).
            std = math.sqrt(max(expected, 0.5))
            if std == 0:
                z = 0.0
            else:
                z = (obs - expected) / std
            z_list.append(z)
        # Aggregate z (mean of pair z-scores).
        avg_z = float(np.mean(z_list))
        # Map: more negative z = more atypical = closer to 1.
        atypicality = 1.0 / (1.0 + math.exp(avg_z))
        return float(atypicality)

    def _atypicality_for(self, paper: Any) -> float:
        """Internal alias for atypicality_score using self.papers."""
        try:
            return self.atypicality_score(paper, self.papers)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.debug("atypicality_score failed: %s", exc)
            return 0.5

    @staticmethod
    def _paper_elements(p: Any) -> List[str]:
        """Return the list of elements (keywords + journal + fields) for a paper."""
        elements: List[str] = []
        for kw in (getattr(p, "keywords", []) or []):
            if kw:
                elements.append(f"kw:{kw}".lower())
        j = getattr(p, "journal", None)
        if j:
            elements.append(f"j:{j}".lower())
        for fos in (getattr(p, "fields_of_study", []) or []):
            if fos:
                elements.append(f"fos:{fos}".lower())
        return elements

    # ------------------------------------------------------------------
    # Rankers
    # ------------------------------------------------------------------

    def rank_novel_papers(self, top_n: int = 100) -> List[NoveltyScore]:
        """Rank papers by overall novelty score (descending).

        Args:
            top_n: Maximum number of papers to return.

        Returns:
            List of :class:`NoveltyScore`.
        """
        scores = [self.score_paper(p) for p in self.papers]
        scores.sort(key=lambda s: -s.novelty_score)
        return scores[:top_n]

    def rank_disruptive_papers(self, top_n: int = 100) -> List[NoveltyScore]:
        """Rank papers by disruption index (descending).

        Args:
            top_n: Maximum number of papers to return.

        Returns:
            List of :class:`NoveltyScore` (only papers with non-zero
            disruption index are returned).
        """
        scores = [self.score_paper(p) for p in self.papers]
        scores = [s for s in scores if s.disruption_index != 0.0]
        scores.sort(key=lambda s: -s.disruption_index)
        return scores[:top_n]

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize_distribution(
        self,
        figsize: Tuple[int, int] = (10, 6),
    ) -> Any:
        """Render a histogram of novelty scores across the corpus.

        Args:
            figsize: Figure size.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        _configure_fonts()
        emb = self._get_embeddings()
        novelties = self._all_novelties(emb)
        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        if len(novelties) == 0:
            ax.text(0.5, 0.5, "No novelty scores to display",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig
        ax.hist(novelties, bins=30, color="steelblue",
                  edgecolor="black", alpha=0.7)
        ax.set_xlabel("Novelty score")
        ax.set_ylabel("Number of papers")
        ax.set_title("Distribution of paper novelty scores")
        ax.grid(True, alpha=0.3)
        return fig

    def visualize_paper(
        self,
        paper_id: str,
        figsize: Tuple[int, int] = (8, 8),
    ) -> Any:
        """Render a radar chart of the four novelty dimensions.

        The four axes are: ``novelty``, ``atypicality``,
        ``disruption`` (clipped to ``[0, 1]``), and ``percentile / 100``.

        Args:
            paper_id: DOI / title identifying the paper.
            figsize: Figure size.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        _configure_fonts()
        paper = self._find_paper(paper_id)
        if paper is None:
            fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
            ax.text(0.5, 0.5, f"Paper '{paper_id}' not found",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig
        score = self.score_paper(paper)
        # Radar chart.
        labels = ["Novelty", "Atypicality", "Disruption", "Percentile"]
        values = [
            max(0.0, min(1.0, score.novelty_score)),
            max(0.0, min(1.0, score.atypicality_score)),
            max(0.0, min(1.0, (score.disruption_index + 1.0) / 2.0)),
            score.percentile / 100.0,
        ]
        angles = np.linspace(0, 2 * math.pi, len(labels), endpoint=False).tolist()
        values_loop = values + [values[0]]
        angles_loop = angles + [angles[0]]

        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True,
                                subplot_kw={"projection": "polar"})
        ax.plot(angles_loop, values_loop, marker="o", color="steelblue")
        ax.fill(angles_loop, values_loop, color="steelblue", alpha=0.20)
        ax.set_xticks(angles)
        ax.set_xticklabels(labels, fontsize=10)
        ax.set_ylim(0, 1)
        ax.set_yticks([0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=8)
        ax.set_title(f"Novelty dimensions — {score.paper_title[:60]}",
                       fontsize=11, pad=20)
        return fig

    def _find_paper(self, paper_id: str) -> Optional[Any]:
        """Look up a paper by DOI or title."""
        for p in self.papers:
            if _safe_id(p) == str(paper_id):
                return p
            title = (getattr(p, "title", "") or "").lower()
            if title and title == str(paper_id).lower():
                return p
        return None


# ---------------------------------------------------------------------------
# Random-embedder fallback
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


__all__ = [
    "NoveltyScore",
    "NoveltyScorer",
]
