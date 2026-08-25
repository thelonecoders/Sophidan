"""Clustering utilities for embedding vectors.

Wraps scikit-learn and (optionally) ``hdbscan`` behind a single, friendly
API. Heavy / optional dependencies are lazily imported so the module can
always be imported even when ``hdbscan`` or ``umap-learn`` are not
installed.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClusterResult:
    """Outcome of a clustering fit.

    Attributes:
        labels: Cluster id per sample (``-1`` denotes noise for
            density-based methods).
        centroids: Array of cluster centroids, or ``None`` when not
            applicable (e.g. DBSCAN / HDBSCAN).
        silhouette: Mean silhouette score (``None`` when undefined).
        n_clusters: Number of clusters found.
        method: Name of the clustering method that produced the result.
        model_object: Underlying fitted model (for inspection / re-use).
        inertia: Within-cluster sum-of-squares for KMeans-family models.
    """

    labels: np.ndarray
    centroids: Optional[np.ndarray] = None
    silhouette: Optional[float] = None
    n_clusters: int = 0
    method: str = "kmeans"
    model_object: Any = None
    inertia: Optional[float] = None
    extra: dict = field(default_factory=dict)


class Clusterer:
    """Thin facade over scikit-learn / hdbscan clustering algorithms.

    Supported ``method`` values: ``"kmeans"``, ``"dbscan"``,
    ``"hdbscan"`` (optional), ``"agglomerative"``.
    """

    SUPPORTED: tuple[str, ...] = ("kmeans", "dbscan", "hdbscan", "agglomerative")

    def __init__(self, method: str = "kmeans", **kwargs: Any) -> None:
        """Initialise the clusterer.

        Args:
            method: One of :attr:`SUPPORTED`.
            **kwargs: Algorithm-specific hyper-parameters forwarded to
                the underlying scikit-learn / hdbscan estimator.

        Raises:
            ValueError: If ``method`` is not recognised.
        """
        method = method.lower()
        if method not in self.SUPPORTED:
            raise ValueError(
                f"Unsupported clustering method '{method}'. "
                f"Choose from {self.SUPPORTED}."
            )
        self.method = method
        self.kwargs = kwargs
        self._model: Any = None
        self.logger = logger

    # ------------------------------------------------------------------
    # Estimator construction
    # ------------------------------------------------------------------

    def _build_estimator(self, n_samples: int) -> Any:
        """Build the underlying scikit-learn / hdbscan estimator."""
        kw = dict(self.kwargs)
        if self.method == "kmeans":
            from sklearn.cluster import KMeans
            n_clusters = int(kw.pop("n_clusters", min(8, max(2, n_samples - 1))))
            kw.setdefault("n_init", 10)
            kw.setdefault("random_state", 42)
            return KMeans(n_clusters=n_clusters, **kw)
        if self.method == "agglomerative":
            from sklearn.cluster import AgglomerativeClustering
            n_clusters = int(kw.pop("n_clusters", min(8, max(2, n_samples - 1))))
            return AgglomerativeClustering(n_clusters=n_clusters, **kw)
        if self.method == "dbscan":
            from sklearn.cluster import DBSCAN
            kw.setdefault("eps", 0.5)
            kw.setdefault("min_samples", 5)
            return DBSCAN(**kw)
        if self.method == "hdbscan":
            try:
                from hdbscan import HDBSCAN
            except Exception as exc:  # pragma: no cover - defensive
                raise RuntimeError(
                    "hdbscan is not installed. Install 'hdbscan' or "
                    "choose another method."
                ) from exc
            kw.setdefault("min_cluster_size", 5)
            return HDBSCAN(**kw)
        raise ValueError(f"Unsupported method: {self.method}")  # pragma: no cover

    # ------------------------------------------------------------------
    # Fit / predict
    # ------------------------------------------------------------------

    def fit(self, vectors: np.ndarray) -> ClusterResult:
        """Fit the clusterer to ``vectors``.

        Args:
            vectors: 2-D array of shape ``(n_samples, n_features)``.

        Returns:
            A :class:`ClusterResult` describing the clustering.
        """
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2:
            raise ValueError("vectors must be a 2-D array")
        if vectors.shape[0] < 2:
            raise ValueError("Need at least 2 samples to cluster")
        estimator = self._build_estimator(vectors.shape[0])
        self._model = estimator
        estimator.fit(vectors)
        labels_attr = getattr(estimator, "labels_", None)
        if labels_attr is not None:
            labels = np.asarray(labels_attr)
        else:
            labels = np.asarray(estimator.predict(vectors))
        # Compute centroids
        centroids = self._compute_centroids(vectors, labels)
        # Silhouette score
        silhouette = self._safe_silhouette(vectors, labels)
        # inertia for KMeans-family
        inertia = getattr(estimator, "inertia_", None)
        n_clusters = int(len(set(labels.tolist())) - (1 if -1 in labels else 0))
        self.logger.info(
            "Clusterer.fit (%s): n_clusters=%d silhouette=%s",
            self.method, n_clusters, silhouette,
        )
        return ClusterResult(
            labels=labels,
            centroids=centroids,
            silhouette=silhouette,
            n_clusters=n_clusters,
            method=self.method,
            model_object=estimator,
            inertia=None if inertia is None else float(inertia),
        )

    def predict(self, vectors: np.ndarray) -> np.ndarray:
        """Predict cluster labels for new samples.

        Density-based methods (DBSCAN / HDBSCAN) may not support
        out-of-sample prediction; in that case the samples are assigned
        to the nearest centroid by Euclidean distance (``-1`` if no
        centroids are available).

        Args:
            vectors: 2-D array of shape ``(n_samples, n_features)``.

        Returns:
            ``np.ndarray`` of predicted labels.
        """
        if self._model is None:
            raise RuntimeError("Clusterer must be fitted before predict()")
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        predict_fn = getattr(self._model, "predict", None)
        if callable(predict_fn):
            return np.asarray(predict_fn(vectors))
        # Density-based fallback: assign to nearest previously-computed centroid
        centroids = self._last_centroids
        unique = self._last_unique_labels
        if centroids is None or not unique:
            return np.full(vectors.shape[0], -1, dtype=int)
        if centroids.shape[1] != vectors.shape[1]:
            return np.full(vectors.shape[0], -1, dtype=int)
        dists = np.linalg.norm(
            vectors[:, None, :] - centroids[None, :, :], axis=2
        )
        return np.asarray([unique[int(i)] for i in np.argmin(dists, axis=1)])

    # Internal helper used by predict() — populated by fit()
    _last_centroids: Optional[np.ndarray] = None
    _last_unique_labels: Optional[list] = None

    def _centroids_from_labels(self, vectors: np.ndarray, labels: np.ndarray) -> np.ndarray:
        """Compute centroids per unique non-noise label."""
        unique = sorted(set(int(x) for x in labels if int(x) >= 0))
        if not unique:
            return np.zeros((0, vectors.shape[1]))
        out = np.zeros((len(unique), vectors.shape[1]), dtype=np.float32)
        for i, c in enumerate(unique):
            mask = labels == c
            if mask.any():
                out[i] = vectors[mask].mean(axis=0)
        return out

    def _compute_centroids(
        self, vectors: np.ndarray, labels: np.ndarray
    ) -> Optional[np.ndarray]:
        """Return centroids for the fitted labels, when computable."""
        unique = sorted(set(int(x) for x in labels if int(x) >= 0))
        if not unique:
            self._last_centroids = None
            self._last_unique_labels = None
            return None
        cents = self._centroids_from_labels(vectors, labels)
        self._last_centroids = cents
        self._last_unique_labels = unique
        return cents

    @staticmethod
    def _safe_silhouette(
        vectors: np.ndarray, labels: np.ndarray
    ) -> Optional[float]:
        """Best-effort silhouette score (returns ``None`` if undefined)."""
        try:
            from sklearn.metrics import silhouette_score
        except Exception:  # pragma: no cover - defensive
            return None
        n_labels = len(set(int(x) for x in labels))
        if n_labels < 2 or len(labels) < 3:
            return None
        if -1 in labels and n_labels - 1 < 2:
            return None
        try:
            return float(silhouette_score(vectors, labels))
        except Exception as exc:
            logger.debug("silhouette_score failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Model selection
    # ------------------------------------------------------------------

    def optimal_k(
        self,
        vectors: np.ndarray,
        k_range: range = range(2, 21),
    ) -> int:
        """Estimate the optimal ``k`` for KMeans-style clustering.

        Combines silhouette analysis with the elbow method (knee
        detection on inertia). The silhouette maximum wins; ties fall
        back to the elbow heuristic.

        Args:
            vectors: 2-D array of shape ``(n_samples, n_features)``.
            k_range: Candidate ``k`` values.

        Returns:
            The optimal ``k``.
        """
        from sklearn.cluster import KMeans

        vectors = np.asarray(vectors, dtype=np.float32)
        ks = [k for k in k_range if 2 <= k < len(vectors)]
        if not ks:
            return 2
        sil_scores: list[float] = []
        inertias: list[float] = []
        for k in ks:
            km = KMeans(n_clusters=k, n_init=10, random_state=42)
            km.fit(vectors)
            inertias.append(float(km.inertia_))
            try:
                from sklearn.metrics import silhouette_score
                sil_scores.append(float(silhouette_score(vectors, km.labels_)))
            except Exception:
                sil_scores.append(-1.0)
        # Best silhouette
        best_sil_idx = int(np.argmax(sil_scores))
        best_k_sil = ks[best_sil_idx]
        # Elbow: largest second-difference (curvature) — the knee
        elbow_k = best_k_sil
        if len(inertias) >= 3:
            diffs = np.diff(inertias)
            curv = np.diff(diffs)
            elbow_k = ks[int(np.argmax(curv)) + 1] if len(curv) else best_k_sil
        # Prefer silhouette; fall back to elbow on tie / degenerate
        if sil_scores[best_sil_idx] <= 0:
            return int(elbow_k)
        return int(best_k_sil)

    # ------------------------------------------------------------------
    # Visualisation
    # ------------------------------------------------------------------

    def visualize(
        self,
        vectors: np.ndarray,
        labels: Optional[np.ndarray] = None,
        method: str = "tsne",
    ) -> "Figure":  # type: ignore[name-defined]
        """Render a 2-D scatter plot of the (already fitted) vectors.

        Args:
            vectors: 2-D array of shape ``(n_samples, n_features)``.
            labels: Optional cluster labels (uses the latest fit if
                omitted).
            method: Dimensionality reduction method: ``"tsne"``,
                ``"umap"`` (optional), or ``"pca"``.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt

        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2:
            raise ValueError("vectors must be 2-D")
        if labels is None:
            if self._model is None:
                labels = np.zeros(vectors.shape[0], dtype=int)
            else:
                labels = np.asarray(getattr(self._model, "labels_"))
        method = method.lower()
        if method == "tsne":
            from sklearn.manifold import TSNE
            perp = min(30, max(2, vectors.shape[0] - 1))
            proj = TSNE(
                n_components=2,
                perplexity=perp,
                init="pca",
                learning_rate="auto",
                random_state=42,
            ).fit_transform(vectors)
        elif method == "umap":
            try:
                import umap  # type: ignore
            except Exception as exc:  # pragma: no cover - optional dep
                raise RuntimeError(
                    "umap-learn is not installed; choose 'tsne' or 'pca'."
                ) from exc
            proj = umap.UMAP(
                n_components=2, random_state=42
            ).fit_transform(vectors)
        elif method == "pca":
            from sklearn.decomposition import PCA
            proj = PCA(n_components=2, random_state=42).fit_transform(vectors)
        else:
            raise ValueError(f"Unsupported visualization method: {method}")

        fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
        labels = np.asarray(labels)
        unique_labels = sorted(set(labels.tolist()))
        cmap = plt.get_cmap("tab20", max(len(unique_labels), 1))
        for i, lab in enumerate(unique_labels):
            mask = labels == lab
            color = "k" if int(lab) == -1 else cmap(i % cmap.N)
            label_name = "noise" if int(lab) == -1 else f"cluster {lab}"
            ax.scatter(
                proj[mask, 0], proj[mask, 1],
                s=18, alpha=0.75, color=color, label=label_name,
            )
        ax.set_title(f"Cluster visualization ({method.upper()})")
        ax.set_xlabel(f"{method}_1")
        ax.set_ylabel(f"{method}_2")
        ax.legend(loc="best", fontsize=8)
        return fig
