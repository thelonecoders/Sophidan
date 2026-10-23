"""Data-science sub-package for the Academic Research Suite.

Provides the analysis engine, topic modeling, embeddings, clustering,
temporal analysis, bibliometric statistics, and visualization helpers.

Each submodule is independently importable; heavy / optional dependencies
(``sentence-transformers``, ``bertopic``, ``hdbscan``, ``umap-learn``,
``statsmodels``, ``wordcloud``, ``geopandas``, ``pyLDAvis``) are lazily
imported inside the functions that need them so that ``import data_science``
never fails on a fresh environment.
"""

# Public API surface (kept lightweight; no heavy deps imported here).
__all__ = [
    "AnalysisEngine",
    "TopicModeler",
    "TopicModel",
    "EmbeddingsModel",
    "Clusterer",
    "ClusterResult",
    "TemporalAnalyzer",
    "Bibliometrics",
    "Visualizer",
]


def __getattr__(name: str):
    """Lazy attribute access for the public classes.

    Implements PEP 562 so that importing one class does not force the
    import of all sibling modules (which would pull in matplotlib,
    scikit-learn, etc. eagerly).
    """
    if name in {"AnalysisEngine"}:
        from .analysis_engine import AnalysisEngine as _cls
        return _cls
    if name in {"TopicModeler", "TopicModel"}:
        from . import topic_modeler as _tm
        return getattr(_tm, name)
    if name == "EmbeddingsModel":
        from .embeddings import EmbeddingsModel as _cls
        return _cls
    if name in {"Clusterer", "ClusterResult"}:
        from . import clustering as _cl
        return getattr(_cl, name)
    if name == "TemporalAnalyzer":
        from .temporal_analysis import TemporalAnalyzer as _cls
        return _cls
    if name == "Bibliometrics":
        from .statistics import Bibliometrics as _cls
        return _cls
    if name == "Visualizer":
        from .visualizations import Visualizer as _cls
        return _cls
    raise AttributeError(f"module 'data_science' has no attribute {name!r}")
