"""Topic-modeling utilities (LDA / NMF / BERTopic).

The :class:`TopicModeler` exposes a uniform API over three different
backends: classical LDA / NMF via scikit-learn and modern transformer-based
topic extraction via BERTopic. The heavy / optional dependencies are
lazily imported, so the module is always importable even when
``bertopic`` (and its torch / sentence-transformers stack) is not installed.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paper field discovery (mirror of the data_acquisition.base_scraper.Paper API)
# ---------------------------------------------------------------------------

_PAPER_FIELDS = (
    "title", "authors", "abstract", "year", "doi",
    "citations_count", "references", "keywords", "fields_of_study",
)

# Reasonable default stop-word set used by the LDA/NMF vectorizer.
_DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "did", "do",
    "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers",
    "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "me", "more", "most", "my",
    "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only",
    "or", "other", "our", "ours", "ourselves", "out", "over", "own",
    "same", "she", "should", "so", "some", "such", "than", "that", "the",
    "their", "theirs", "them", "themselves", "then", "there", "these",
    "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your",
    "yours", "yourself", "yourselves",
    "abstract", "introduction", "method", "methods", "methodology",
    "result", "results", "conclusion", "conclusions", "discussion",
    "figure", "table", "data", "analysis", "study", "paper", "research",
    "article", "journal", "et", "al", "fig", "doi", "author", "authors",
    "university", "published", "copyright", "based",
})


def _paper_to_text(paper: Any) -> str:
    """Extract a representative text string from a Paper-like object."""
    if paper is None:
        return ""
    if isinstance(paper, str):
        return paper
    if isinstance(paper, dict):
        d = paper
    else:
        try:
            from dataclasses import asdict, is_dataclass
            if is_dataclass(paper) and not isinstance(paper, type):
                d = asdict(paper)
            else:
                d = {f: getattr(paper, f, None) for f in _PAPER_FIELDS}
        except Exception:
            d = {f: getattr(paper, f, None) for f in _PAPER_FIELDS}
    parts: List[str] = []
    title = d.get("title")
    if title:
        parts.append(str(title))
    abstract = d.get("abstract")
    if abstract:
        parts.append(str(abstract))
    keywords = d.get("keywords")
    if keywords:
        if isinstance(keywords, (list, tuple, set)):
            parts.extend(str(k) for k in keywords)
        else:
            parts.append(str(keywords))
    return " ".join(parts).strip()


def _clean_text(text: str) -> str:
    """Light text cleaning for topic modeling."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text)
    # Strip simple inline LaTeX
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}\\]", " ", text)
    text = re.sub(r"[^A-Za-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


# ---------------------------------------------------------------------------
# TopicModel dataclass
# ---------------------------------------------------------------------------

@dataclass
class TopicModel:
    """Container for a fitted topic model.

    Attributes:
        topics: List of dicts, one per topic. Each dict contains
            ``id`` (int), ``words`` (list of ``(word, weight)`` tuples),
            and ``top_words`` (list of bare strings for convenience).
        doc_topic_matrix: ``np.ndarray`` of shape
            ``(n_docs, n_topics)`` giving the per-document topic
            distribution.
        model_object: Underlying fitted model (LDA / NMF / BERTopic).
        vectorizer: The vectorizer used (LDA / NMF only).
        method: Name of the backend used.
        texts: Original input texts (when available).
        papers: Original input papers (when available).
    """

    topics: List[dict] = field(default_factory=list)
    doc_topic_matrix: Optional[np.ndarray] = None
    model_object: Any = None
    vectorizer: Any = None
    method: str = "nmf"
    texts: Optional[List[str]] = None
    papers: Optional[List[Any]] = None
    n_topics: int = 0

    def top_papers_per_topic(self, n: int = 5) -> dict[int, List[Any]]:
        """Return the ``n`` most representative papers per topic.

        Args:
            n: Number of papers to return per topic.

        Returns:
            Dict mapping topic id -> list of (paper, score) tuples
            sorted by descending topic probability.
        """
        if self.doc_topic_matrix is None or self.papers is None:
            return {}
        arr = np.asarray(self.doc_topic_matrix)
        if arr.ndim != 2 or arr.shape[0] != len(self.papers):
            return {}
        out: dict[int, List[Any]] = {}
        n_topics = arr.shape[1]
        for t in range(n_topics):
            order = np.argsort(-arr[:, t])
            top_idx = order[:n]
            out[t] = [(self.papers[i], float(arr[i, t])) for i in top_idx]
        return out


# ---------------------------------------------------------------------------
# TopicModeler
# ---------------------------------------------------------------------------

class TopicModeler:
    """Uniform wrapper around LDA / NMF / BERTopic backends.

    Supported ``method`` values: ``"lda"``, ``"nmf"``, ``"bertopic"``.
    """

    SUPPORTED: tuple[str, ...] = ("lda", "nmf", "bertopic")

    def __init__(self, method: str = "nmf", **kwargs: Any) -> None:
        """Initialize the topic modeler.

        Args:
            method: One of :attr:`SUPPORTED`.
            **kwargs: Backend-specific hyper-parameters. ``n_top_words``
                (default 10) controls how many words are stored per topic
                in the resulting :class:`TopicModel`.

        Raises:
            ValueError: If ``method`` is not recognised.
        """
        method = method.lower()
        if method not in self.SUPPORTED:
            raise ValueError(
                f"Unsupported topic method '{method}'. "
                f"Choose from {self.SUPPORTED}."
            )
        self.method = method
        self.kwargs = kwargs
        self.n_top_words: int = int(kwargs.pop("n_top_words", 10))
        self.random_state: int = int(kwargs.pop("random_state", 42))
        self._last_model: Optional[TopicModel] = None
        self.logger = logger

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(
        self,
        source: Sequence[Any],
        num_topics: int = 10,
    ) -> TopicModel:
        """Fit the topic model to a collection of papers or texts.

        Args:
            source: Sequence of Paper objects or raw strings.
            num_topics: Number of topics to extract.

        Returns:
            A :class:`TopicModel` describing the fitted model.
        """
        source = list(source)
        if not source:
            raise ValueError("Cannot fit a topic model on an empty collection.")
        # Detect whether source is papers or plain strings
        if all(isinstance(s, str) for s in source):
            texts = [s for s in source]
            papers = None
        else:
            papers = source
            texts = [_paper_to_text(p) for p in source]

        cleaned = [_clean_text(t) for t in texts]
        cleaned = [t for t in cleaned if t]
        if not cleaned:
            raise ValueError("All input texts are empty after cleaning.")

        if self.method == "bertopic":
            model = self._fit_bertopic(cleaned, num_topics, source, texts, papers)
        else:
            model = self._fit_sklearn(cleaned, num_topics, source, texts, papers)
        self._last_model = model
        return model

    # ------------------------------------------------------------------
    # Sklearn backends
    # ------------------------------------------------------------------

    def _fit_sklearn(
        self,
        cleaned: List[str],
        num_topics: int,
        source: Sequence[Any],
        texts: List[str],
        papers: Optional[List[Any]],
    ) -> TopicModel:
        """Fit LDA or NMF via scikit-learn."""
        from sklearn.feature_extraction.text import (
            CountVectorizer, TfidfVectorizer,
        )
        vectorizer_cls = CountVectorizer if self.method == "lda" else TfidfVectorizer
        vectorizer = vectorizer_cls(
            stop_words=list(_DEFAULT_STOPWORDS),
            max_df=0.95, min_df=2,
            ngram_range=(1, 1),
        )
        try:
            features = vectorizer.fit_transform(cleaned)
        except ValueError:
            # min_df too aggressive — relax
            vectorizer = vectorizer_cls(
                stop_words=list(_DEFAULT_STOPWORDS),
                max_df=1.0, min_df=1,
                ngram_range=(1, 1),
            )
            features = vectorizer.fit_transform(cleaned)
        feature_names = vectorizer.get_feature_names_out()

        n_samples, n_features = features.shape
        # NNDSVD init requires n_components <= min(n_samples, n_features)
        max_components = max(1, min(n_samples, n_features))
        n_components = max(2, min(num_topics, max_components))
        if max_components < 2:
            # Degenerate corpus; force a single pseudo-topic
            n_components = 1

        if self.method == "lda":
            from sklearn.decomposition import LatentDirichletAllocation
            estimator = LatentDirichletAllocation(
                n_components=n_components,
                random_state=self.random_state,
                max_iter=20,
                learning_method="batch",
            )
            doc_topic = estimator.fit_transform(features)
            components = estimator.components_
        else:  # nmf
            from sklearn.decomposition import NMF
            init = "nndsvd" if n_components <= min(n_samples, n_features) else "random"
            estimator = NMF(
                n_components=n_components,
                random_state=self.random_state,
                init=init,
            )
            doc_topic = estimator.fit_transform(features)
            components = estimator.components_

        # Build topic descriptions
        topics: List[dict] = []
        for t in range(components.shape[0]):
            top_idx = components[t].argsort()[::-1][: self.n_top_words]
            words = [(str(feature_names[i]), float(components[t, i]))
                     for i in top_idx]
            topics.append({
                "id": t,
                "words": words,
                "top_words": [w for w, _ in words],
            })

        return TopicModel(
            topics=topics,
            doc_topic_matrix=np.asarray(doc_topic, dtype=np.float32),
            model_object=estimator,
            vectorizer=vectorizer,
            method=self.method,
            texts=texts,
            papers=papers,
            n_topics=components.shape[0],
        )

    def _fit_bertopic(
        self,
        cleaned: List[str],
        num_topics: int,
        source: Sequence[Any],
        texts: List[str],
        papers: Optional[List[Any]],
    ) -> TopicModel:
        """Fit a BERTopic model (lazy import)."""
        try:
            from bertopic import BERTopic
        except Exception as exc:  # pragma: no cover - optional dep
            self.logger.warning(
                "bertopic unavailable (%s); falling back to NMF.", exc
            )
            self.method = "nmf"
            return self._fit_sklearn(cleaned, num_topics, source, texts, papers)
        estimator = BERTopic(
            nr_topics=num_topics,
            calculate_probabilities=True,
            verbose=False,
            **{k: v for k, v in self.kwargs.items()
               if k not in ("n_top_words", "random_state")},
        )
        topics_arr, probs = estimator.fit_transform(cleaned)
        # Build topic descriptions
        topics: List[dict] = []
        topic_ids = sorted({int(t) for t in topics_arr if int(t) >= 0})
        for t in topic_ids:
            words_tuples = estimator.get_topic(t) or []
            words = [(str(w), float(s)) for w, s in words_tuples[: self.n_top_words]]
            topics.append({
                "id": t,
                "words": words,
                "top_words": [w for w, _ in words],
            })
        # Build doc-topic matrix aligned with topic_ids (and -1 for outliers)
        full_ids = topic_ids + ([-1] if -1 in set(topics_arr.tolist()) else [])
        idx_map = {t: i for i, t in enumerate(full_ids)}
        if probs is not None and probs.ndim == 2:
            doc_topic = np.zeros((len(cleaned), len(full_ids)), dtype=np.float32)
            for i, t in enumerate(topics_arr):
                col = idx_map.get(int(t))
                if col is not None and probs.shape[1] > col:
                    doc_topic[i, col] = float(probs[i, col])
                elif col is not None:
                    doc_topic[i, col] = 1.0
        else:
            doc_topic = np.zeros((len(cleaned), len(full_ids)), dtype=np.float32)
            for i, t in enumerate(topics_arr):
                col = idx_map.get(int(t))
                if col is not None:
                    doc_topic[i, col] = 1.0
        return TopicModel(
            topics=topics,
            doc_topic_matrix=doc_topic,
            model_object=estimator,
            vectorizer=None,
            method="bertopic",
            texts=texts,
            papers=papers,
            n_topics=len(topic_ids),
        )

    # ------------------------------------------------------------------
    # Transform / inspect
    # ------------------------------------------------------------------

    def transform(self, text: str) -> List[float]:
        """Return the topic distribution for a new text.

        Args:
            text: Input text.

        Returns:
            A list of per-topic probabilities (sum ~= 1).

        Raises:
            RuntimeError: If the model has not been fitted yet.
        """
        if self._last_model is None or self._last_model.model_object is None:
            raise RuntimeError("TopicModeler must be fitted before transform().")
        cleaned = _clean_text(text)
        model = self._last_model
        if model.method in ("lda", "nmf") and model.vectorizer is not None:
            vec = model.vectorizer.transform([cleaned])
            dist = model.model_object.transform(vec)
            return [float(x) for x in np.asarray(dist)[0]]
        if model.method == "bertopic":
            try:
                _, probs = model.model_object.transform([cleaned])
            except Exception:
                _, probs = model.model_object.transform([cleaned], probabilities=False)
                probs = None
            if probs is None:
                return []
            arr = np.asarray(probs)[0]
            return [float(x) for x in arr]
        raise RuntimeError("Unsupported backend for transform().")

    def top_papers_per_topic(self, n: int = 5) -> dict[int, List[Any]]:
        """Return the ``n`` most representative papers per topic.

        Uses the most recently fitted model.

        Args:
            n: Number of papers per topic.

        Returns:
            Dict mapping topic id -> list of ``(paper, score)`` tuples.

        Raises:
            RuntimeError: If the model has not been fitted yet.
        """
        if self._last_model is None:
            raise RuntimeError("TopicModeler must be fitted first.")
        return self._last_model.top_papers_per_topic(n=n)

    # ------------------------------------------------------------------
    # Visualisation
    # ------------------------------------------------------------------

    def visualize(self) -> "Figure":  # type: ignore[name-defined]
        """Visualize the fitted topic model.

        Tries to use ``pyLDAvis`` when available; otherwise falls back
        to a simple grid of bar charts of the top words per topic.

        Returns:
            A :class:`matplotlib.figure.Figure`.

        Raises:
            RuntimeError: If the model has not been fitted yet.
        """
        import matplotlib.pyplot as plt
        if self._last_model is None:
            raise RuntimeError("TopicModeler must be fitted before visualize().")
        model = self._last_model
        # Try pyLDAvis for sklearn LDA / NMF
        if model.method in ("lda", "nmf") and model.vectorizer is not None:
            try:
                import pyLDAvis  # type: ignore
                # Don't display; just note availability. We still render
                # bar charts as the canonical return type (Figure).
                pass
            except Exception:
                pass
        topics = model.topics or []
        n = max(1, len(topics))
        n_cols = min(3, n)
        n_rows = int(np.ceil(n / n_cols))
        fig, axes = plt.subplots(
            n_rows, n_cols, figsize=(4 * n_cols, 3 * n_rows),
            constrained_layout=True, squeeze=False,
        )
        for idx, topic in enumerate(topics):
            ax = axes[idx // n_cols, idx % n_cols]
            words = topic.get("words", [])[: self.n_top_words]
            if not words:
                ax.set_axis_off()
                continue
            labels = [w for w, _ in words]
            weights = [s for _, s in words]
            ax.barh(labels[::-1], weights[::-1], color="#3a7ca5")
            ax.set_title(f"Topic {topic.get('id', idx)}", fontsize=10)
            ax.tick_params(axis="y", labelsize=8)
        # Hide unused axes
        for j in range(len(topics), n_rows * n_cols):
            axes[j // n_cols, j % n_cols].set_axis_off()
        fig.suptitle("Topic Top Words", fontsize=12)
        return fig

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the most recently fitted model via ``joblib``.

        Args:
            path: Destination ``.joblib`` file.
        """
        try:
            import joblib
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError("joblib is required to save TopicModel") from exc
        if self._last_model is None:
            raise RuntimeError("Nothing to save: model not fitted.")
        snapshot = {
            "method": self._last_model.method,
            "topics": self._last_model.topics,
            "doc_topic_matrix": self._last_model.doc_topic_matrix,
            "model_object": self._last_model.model_object,
            "vectorizer": self._last_model.vectorizer,
            "n_topics": self._last_model.n_topics,
            "texts": self._last_model.texts,
            "papers": self._last_model.papers,
        }
        joblib.dump(snapshot, path)
        self.logger.info("Saved TopicModel snapshot -> %s", path)

    def load(self, path: str) -> TopicModel:
        """Load a previously saved model.

        Args:
            path: Source ``.joblib`` file.

        Returns:
            The restored :class:`TopicModel`.
        """
        try:
            import joblib
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError("joblib is required to load TopicModel") from exc
        snap = joblib.load(path)
        model = TopicModel(
            topics=snap.get("topics", []),
            doc_topic_matrix=snap.get("doc_topic_matrix"),
            model_object=snap.get("model_object"),
            vectorizer=snap.get("vectorizer"),
            method=snap.get("method", "nmf"),
            texts=snap.get("texts"),
            papers=snap.get("papers"),
            n_topics=snap.get("n_topics", 0),
        )
        self._last_model = model
        self.method = model.method
        return model
