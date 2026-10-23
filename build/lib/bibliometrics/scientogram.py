"""Sci2 / Loet Leydesdorff-style scientogram builder.

This module exposes :class:`ScientogramBuilder` which produces the
co-occurrence matrices (term×term, journal×journal, institution×
institution) and the normalisation / pruning / layout pipeline used by
the Sci2 Tool and by Loet Leydesdorff's scientogram workflow.

Implemented routines:

* :meth:`co_word_matrix`           — top-N term × term co-occurrence.
* :meth:`co_journal_matrix`        — journal × journal co-occurrence.
* :meth:`institute_collaboration_matrix` — institution × institution
  co-authorship (extracted from author-affiliation strings).
* :meth:`normalize`                — association / cosine / Jaccard /
  inclusion / Salton normalisation.
* :meth:`prune`                    — threshold-based edge pruning.
* :meth:`layout_scientogram`       — Kamada-Kawai / stress-majorisation
  layout, returning a ``networkx.Graph`` with ``pos`` attributes.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# networkx imported eagerly — every layout method needs it.
try:
    import networkx as nx
    _HAVE_NX = True
except ImportError:  # pragma: no cover - environment dependent
    _HAVE_NX = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper coercion helpers
# ---------------------------------------------------------------------------

_PAPER_FIELDS: Tuple[str, ...] = (
    "title", "authors", "abstract", "year", "doi",
    "citations_count", "references", "keywords", "fields_of_study",
    "journal", "source", "venue", "publisher",
)

# Institutional affiliation is rarely stored on the Paper dataclass
# itself. When present, it is usually encoded inside the author string
# (e.g. ``"Jane Smith (MIT, USA)"`` or ``"Smith, J. [MIT]"``). The
# regexes below extract a best-effort affiliation token from each
# author entry.
_AFFIL_PATTERNS: Tuple = (
    re.compile(r"\(([^()]+)\)"),         # (MIT, USA)
    re.compile(r"\[([^\[\]]+)\]"),       # [MIT]
    re.compile(r"<([^<>]+)>"),           # <MIT>
)


def _paper_to_dict(paper: Any) -> Dict[str, Any]:
    """Coerce a Paper-like object into a plain dict."""
    if isinstance(paper, dict):
        return dict(paper)
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(paper) and not isinstance(paper, type):
            return asdict(paper)
    except Exception:  # pragma: no cover - defensive
        pass
    return {f: getattr(paper, f, None) for f in _PAPER_FIELDS}


def _coerce_list(value: Any) -> List[Any]:
    """Coerce arbitrary input to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:  # pragma: no cover - defensive
            pass
    if isinstance(value, str):
        parts = re.split(r"[;,|]", value)
        return [p.strip() for p in parts if p.strip()]
    try:
        return list(value)
    except TypeError:
        return [value]


def _normalise_id(s: Any) -> str:
    """Lowercase / strip / collapse-whitespace a string identifier."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _journal_of(d: Dict[str, Any]) -> str:
    """Return a normalised journal name for a paper dict."""
    for k in ("journal", "source", "venue", "publisher"):
        v = d.get(k)
        if v:
            n = _normalise_id(v)
            if n:
                return n
    return ""


def _institute_of(author: str) -> str:
    """Extract a best-effort affiliation token from an author string.

    Returns ``""`` when no token can be extracted — callers should
    treat such authors as having no affiliation.
    """
    if not author:
        return ""
    for pat in _AFFIL_PATTERNS:
        m = pat.search(author)
        if m:
            token = m.group(1).split(",")[0].strip()
            n = _normalise_id(token)
            if n:
                return n
    return ""


_STOP_WORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "for",
    "of", "to", "in", "on", "at", "by", "with", "as", "is", "are",
    "was", "were", "be", "been", "being", "this", "that", "these",
    "those", "it", "its", "from", "we", "our", "their", "they", "them",
    "which", "who", "whom", "what", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "can", "will", "just", "don", "should",
    "now", "also", "based", "using", "via", "into", "between",
    "through", "during", "before", "after", "above", "below", "up",
    "down", "out", "over", "under", "again", "further", "once",
    "here", "there", "study", "studies", "research", "paper",
    "article", "result", "results", "method", "methods", "approach",
    "approaches", "analysis", "model", "models", "data", "show",
    "shown", "showed", "found", "find", "finds", "use", "used",
    "uses", "using", "however", "although", "while", "whereas",
    "thus", "therefore", "hence", "discuss", "discusses",
    "discussed", "conclude", "concludes", "conclusion",
    "introduction", "abstract", "section",
})


def _tokenise(text: str) -> List[str]:
    """Lowercase + word-tokenise + stop-word filter a text blob."""
    if not text:
        return []
    text = text.lower()
    tokens = re.findall(r"[a-z][a-z0-9\-]{2,}", text)
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]


# ---------------------------------------------------------------------------
# ScientogramBuilder
# ---------------------------------------------------------------------------

class ScientogramBuilder:
    """Build and layout scientograms (co-occurrence network diagrams).

    The builder is stateless: every public method takes the corpus
    (``papers``) and returns either a :class:`pandas.DataFrame`
    (matrix methods), a :class:`pandas.DataFrame` (normalisation /
    pruning), or a :class:`networkx.Graph` (layout method).
    """

    def __init__(self) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Co-occurrence matrices
    # ------------------------------------------------------------------

    def co_word_matrix(
        self,
        papers: Sequence[Any],
        top_n: int = 200,
        fields: Sequence[str] = ("title", "abstract", "keywords"),
    ) -> pd.DataFrame:
        """Build a term × term co-occurrence matrix.

        Terms are extracted from each paper's title, abstract, and
        keywords. Co-occurrence = number of papers in which the term
        pair appears together. Only the top-N most frequent terms
        (by document frequency) are kept.

        Args:
            papers: Sequence of Paper objects.
            top_n: Maximum number of terms (default 200).
            fields: Text fields to extract terms from.

        Returns:
            Symmetric DataFrame indexed and columned by term. Diagonal
            entries are document frequencies.
        """
        per_paper_tokens: List[List[str]] = []
        doc_freq: Counter = Counter()
        for p in papers:
            d = _paper_to_dict(p)
            blob_parts: List[str] = []
            for f in fields:
                v = d.get(f)
                if isinstance(v, list):
                    blob_parts.extend(str(x) for x in v)
                elif v is not None:
                    blob_parts.append(str(v))
            tokens = _tokenise(" ".join(blob_parts))
            per_paper_tokens.append(tokens)
            for t in set(tokens):
                doc_freq[t] += 1
        top_terms = [t for t, _ in doc_freq.most_common(top_n)]
        top_set = set(top_terms)
        # Tally pair counts.
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        for tokens in per_paper_tokens:
            unique = sorted(set(tokens) & top_set)
            for a, b in combinations(unique, 2):
                pair_counts[(a, b)] += 1
        mat = pd.DataFrame(
            0, index=top_terms, columns=top_terms, dtype=int,
        )
        # Diagonal = document frequency.
        for t in top_terms:
            mat.loc[t, t] = doc_freq[t]
        for (a, b), c in pair_counts.items():
            mat.loc[a, b] = c
            mat.loc[b, a] = c
        return mat

    def co_journal_matrix(
        self,
        papers: Sequence[Any],
    ) -> pd.DataFrame:
        """Build a journal × journal co-citation matrix.

        Two journals are co-cited when they appear together in some
        citing paper's reference list. Diagonal entries are the
        number of papers in the corpus from that journal.

        Args:
            papers: Sequence of Paper objects.

        Returns:
            Symmetric DataFrame indexed and columned by journal name.
        """
        dicts = [_paper_to_dict(p) for p in papers]
        # Map reference id → journal of the cited paper (when the cited
        # paper is itself in the corpus).
        ref_to_journal: Dict[str, str] = {}
        journal_papers: Counter = Counter()
        for d in dicts:
            jname = _journal_of(d)
            rid = _normalise_id(d.get("doi") or d.get("title"))
            if jname and rid:
                ref_to_journal[rid] = jname
                journal_papers[jname] += 1
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        for d in dicts:
            js_in_paper: List[str] = []
            seen: set = set()
            for r in _coerce_list(d.get("references")):
                rid = _normalise_id(r)
                j = ref_to_journal.get(rid)
                if j and j not in seen:
                    js_in_paper.append(j)
                    seen.add(j)
            for a, b in combinations(sorted(set(js_in_paper)), 2):
                pair_counts[(a, b)] += 1
        journals = sorted(journal_papers.keys())
        mat = pd.DataFrame(
            0, index=journals, columns=journals, dtype=int,
        )
        for j in journals:
            mat.loc[j, j] = journal_papers[j]
        for (a, b), c in pair_counts.items():
            mat.loc[a, b] = c
            mat.loc[b, a] = c
        return mat

    def institute_collaboration_matrix(
        self,
        papers: Sequence[Any],
    ) -> pd.DataFrame:
        """Build an institution × institution collaboration matrix.

        Two institutions collaborate when authors affiliated with each
        co-author the same paper. Affiliations are extracted from
        author strings via the regex patterns in
        :data:`_AFFIL_PATTERNS` — when no affiliation can be parsed,
        the author's name itself is used as the "institution" (so
        single-author papers still appear on the diagonal).

        Args:
            papers: Sequence of Paper objects.

        Returns:
            Symmetric DataFrame indexed and columned by institution
            name. Diagonal entries are the number of papers with
            at least one author affiliated with that institution.
        """
        dicts = [_paper_to_dict(p) for p in papers]
        inst_papers: Counter = Counter()
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        for d in dicts:
            authors = _coerce_list(d.get("authors"))
            insts: List[str] = []
            seen: set = set()
            for a in authors:
                if not isinstance(a, str):
                    continue
                affil = _institute_of(a)
                if not affil:
                    # Fall back to the author name.
                    affil = _normalise_id(a)
                if not affil or affil in seen:
                    continue
                insts.append(affil)
                seen.add(affil)
            for i in insts:
                inst_papers[i] += 1
            for a, b in combinations(sorted(set(insts)), 2):
                pair_counts[(a, b)] += 1
        institutes = sorted(inst_papers.keys())
        mat = pd.DataFrame(
            0, index=institutes, columns=institutes, dtype=int,
        )
        for i in institutes:
            mat.loc[i, i] = inst_papers[i]
        for (a, b), c in pair_counts.items():
            mat.loc[a, b] = c
            mat.loc[b, a] = c
        return mat

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def normalize(
        self,
        matrix: pd.DataFrame,
        method: str = "association",
    ) -> pd.DataFrame:
        """Normalise a symmetric co-occurrence matrix.

        Supported methods:

        * ``"association"`` — ``M[i,j] / sqrt(M[i,i] * M[j,j])``
          (a.k.a. equivalence index in Leydesdorff's terminology).
        * ``"cosine"``       — same as association (Salton cosine).
        * ``"jaccard"``      — ``M[i,j] / (M[i,i] + M[j,j] - M[i,j])``.
        * ``"inclusion"``    — ``M[i,j] / min(M[i,i], M[j,j])``
          (a.k.a. overlap coefficient).
        * ``"salton"``       — alias for cosine.

        Args:
            matrix: Symmetric non-negative DataFrame.
            method: Normalisation method (default ``"association"``).

        Returns:
            Normalised DataFrame (float dtype). The diagonal is set
            to 1.0 for self-similarity.
        """
        m_lower = method.lower()
        if m_lower == "salton":
            m_lower = "cosine"
        if m_lower not in ("association", "cosine", "jaccard", "inclusion"):
            raise ValueError(f"unknown normalisation method: {method!r}")
        M = matrix.astype(float).values
        n = M.shape[0]
        idx = matrix.index
        cols = matrix.columns
        out = np.zeros_like(M)
        # Diagonal = M[i,i] (raw count).
        for i in range(n):
            out[i, i] = 1.0 if M[i, i] > 0 else 0.0
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                mi = M[i, i]
                mj = M[j, j]
                v = M[i, j]
                if m_lower in ("association", "cosine"):
                    denom = math.sqrt(mi * mj) if (mi > 0 and mj > 0) else 0.0
                    out[i, j] = (v / denom) if denom > 0 else 0.0
                elif m_lower == "jaccard":
                    denom = mi + mj - v
                    out[i, j] = (v / denom) if denom > 0 else 0.0
                elif m_lower == "inclusion":
                    denom = min(mi, mj)
                    out[i, j] = (v / denom) if denom > 0 else 0.0
        return pd.DataFrame(out, index=idx, columns=cols)

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune(
        self,
        matrix: pd.DataFrame,
        threshold: float = 0.05,
        absolute: bool = False,
    ) -> pd.DataFrame:
        """Zero out low-magnitude entries.

        Args:
            matrix: Input matrix.
            threshold: Cutoff value. Entries strictly below the
                threshold are set to 0.
            absolute: If ``True`` compare against the raw entry value;
                if ``False`` (default) compare against the entry as a
                fraction of the matrix maximum.

        Returns:
            New DataFrame with low-value entries zeroed (diagonal
            preserved).
        """
        M = matrix.astype(float).copy()
        if absolute:
            mask = M.abs() < threshold
        else:
            mx = float(M.max().max()) if M.size else 0.0
            if mx <= 0:
                return matrix
            mask = (M / mx) < threshold
        # Preserve the diagonal.
        np.fill_diagonal(mask.values, False)
        return M.where(~mask, other=0.0)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def layout_scientogram(
        self,
        matrix: pd.DataFrame,
        layout: str = "kamada_kawai",
        seed: Optional[int] = 42,
    ) -> "nx.Graph":
        """Lay out a co-occurrence matrix as a scientogram graph.

        Args:
            matrix: Symmetric co-occurrence DataFrame (will be
                converted to a graph; non-zero off-diagonal entries
                become edges weighted by their value).
            layout: ``"kamada_kawai"`` (default) or ``"stress"``.
            seed: RNG seed.

        Returns:
            ``networkx.Graph`` with ``pos`` attributes set on every
            node (a 2-tuple of floats). Nodes carry their row/column
            label as their ``label`` attribute.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for layout_scientogram")
        g = nx.Graph()
        labels = list(matrix.index)
        for lab in labels:
            g.add_node(lab, label=str(lab))
        M = matrix.astype(float)
        for i, li in enumerate(labels):
            for j, lj in enumerate(labels):
                if i >= j:
                    continue
                w = float(M.iloc[i, j])
                if w > 0:
                    g.add_edge(li, lj, weight=w, kind="cooccurrence")
        if len(g) == 0:
            return g
        layout_lower = layout.lower()
        if layout_lower == "stress":
            pos = nx.kamada_kawai_layout(g, weight="weight")
        elif layout_lower == "kamada_kawai":
            pos = nx.kamada_kawai_layout(g, weight="weight")
        else:
            pos = nx.spring_layout(g, weight="weight", seed=seed)
        for n, p in pos.items():
            g.nodes[n]["pos"] = (float(p[0]), float(p[1]))
        return g

    # ------------------------------------------------------------------
    # Convenience: build → normalise → prune → layout, all in one call.
    # ------------------------------------------------------------------

    def build_scientogram(
        self,
        papers: Sequence[Any],
        matrix_kind: str = "co_word",
        top_n: int = 200,
        normalisation: str = "association",
        prune_threshold: float = 0.05,
        layout: str = "kamada_kawai",
        seed: Optional[int] = 42,
    ) -> "nx.Graph":
        """One-shot scientogram builder.

        Args:
            papers: Corpus of papers.
            matrix_kind: ``"co_word"``, ``"co_journal"`` or
                ``"institute"``.
            top_n: Top-N cut-off (only used for ``co_word``).
            normalisation: Normalisation method
                (see :meth:`normalize`).
            prune_threshold: Pruning threshold (see :meth:`prune`).
            layout: Layout engine (see :meth:`layout_scientogram`).
            seed: RNG seed.

        Returns:
            ``networkx.Graph`` with ``pos`` attributes.
        """
        if matrix_kind == "co_word":
            mat = self.co_word_matrix(papers, top_n=top_n)
        elif matrix_kind == "co_journal":
            mat = self.co_journal_matrix(papers)
        elif matrix_kind == "institute":
            mat = self.institute_collaboration_matrix(papers)
        else:
            raise ValueError(f"unknown matrix_kind: {matrix_kind!r}")
        normed = self.normalize(mat, method=normalisation)
        pruned = self.prune(normed, threshold=prune_threshold)
        return self.layout_scientogram(pruned, layout=layout, seed=seed)
