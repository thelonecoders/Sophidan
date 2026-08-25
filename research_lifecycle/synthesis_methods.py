"""Evidence-synthesis methods beyond meta-analysis.

Meta-analysis is the most-cited synthesis method but is often
inappropriate: only ~30% of systematic reviews pool effect sizes
quantitatively (Page et al., 2021). This module provides the
*qualitative and configurational* synthesis methods that the rest of
the suite relies on:

* :class:`NarrativeSynthesis` — SWiM-aligned narrative synthesis of
  quantitative extractions with comparison tables and key-findings
  summaries.
* :class:`ThematicSynthesis` — Thomas & Harden (2008) thematic
  synthesis with optional ``framework`` and ``grounded`` modes; returns
  a :class:`networkx.Graph` hierarchy (lazy import).
* :class:`QualitativeComparativeAnalysis` — QCA with fuzzy-set
  calibration, truth-table construction, and necessary / sufficient
  condition detection (consistency, coverage).
* :class:`MetaSynthesis` — thematic meta-synthesis across qualitative
  studies, returning a conceptual model as a
  :class:`networkx.DiGraph`.
* :class:`BestFitFrameworkSynthesis` — Carroll et al. (2013)
  best-fit framework synthesis for policy / implementation research.

Heavy dependencies (``pandas``, ``networkx``, ``numpy``) are imported
lazily inside the methods that need them so the module is importable in
minimal environments.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------
_STOPWORDS = frozenset(
    """
    a an the and or but if then else for of to in on at by with from into
    is are was were be been being this that these those it its their our
    we i you they he she his her my your their them us him me as not no
    can could should would may might must will shall do does did done have
    has had having which who whom whose what when where why how
    """.split()
)


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-z][a-z0-9_\-]{1,}", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def _ensure_pandas():
    try:
        import pandas as pd  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "pandas is required for this synthesis method; "
            "install with: pip install pandas"
        ) from exc
    return pd


def _ensure_networkx():
    try:
        import networkx as nx  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "networkx is required for this synthesis method; "
            "install with: pip install networkx"
        ) from exc
    return nx


# ---------------------------------------------------------------------------
# Narrative synthesis
# ---------------------------------------------------------------------------
@dataclass
class NarrativeResult:
    """Outcome of a :class:`NarrativeSynthesis.synthesize` call.

    Attributes:
        themes: A list of ``{name, description, studies}`` dicts.
        narrative_text: A markdown-formatted narrative summary.
        comparison_table: A :class:`pandas.DataFrame` comparing studies
            on key outcome columns (lazy — ``None`` if pandas missing).
        key_findings: Bullet-list of key findings.
        limitations: Bullet-list of synthesis limitations.
    """

    themes: List[Dict[str, Any]] = field(default_factory=list)
    narrative_text: str = ""
    comparison_table: Any = None
    key_findings: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


class NarrativeSynthesis:
    """SWiM-aligned narrative synthesis of quantitative extractions.

    The synthesiser does *not* pool effect sizes quantitatively (that is
    the job of :mod:`meta_analysis`). Instead it groups studies by
    outcome / population / intervention pattern, builds a comparison
    table, and produces a markdown narrative.

    Examples:
        >>> synth = NarrativeSynthesis()
        >>> result = synth.synthesize(extractions=[{"study_id": "A", "outcome": "X"}])
    """

    # Default columns to pivot the comparison table on.
    DEFAULT_PIVOT_COLUMNS = (
        "study_id",
        "year",
        "design",
        "population",
        "intervention",
        "outcome",
        "effect_estimate",
        "effect_measure_type",
        "ci_lower",
        "ci_upper",
        "rob_overall",
    )

    def synthesize(
        self,
        extractions: Sequence[Dict[str, Any]],
        themes: Optional[Sequence[str]] = None,
    ) -> NarrativeResult:
        """Synthesise a list of extraction dicts into a narrative.

        Args:
            extractions: List of dicts (typically produced by
                :meth:`ExtractionSession.to_dict`).
            themes: Optional explicit theme labels; if omitted themes
                are derived from the dominant ``outcome`` values.

        Returns:
            A :class:`NarrativeResult`.
        """
        if not extractions:
            return NarrativeResult(
                limitations=["No extractions provided."],
            )
        extractions = list(extractions)

        # --- Derive themes ----------------------------------------------
        if themes:
            theme_labels = list(themes)
        else:
            outcome_counter: Counter = Counter()
            for ex in extractions:
                out = ex.get("outcome") or ex.get("primary_outcome")
                if out:
                    outcome_counter[str(out).strip()] += 1
            theme_labels = [t for t, _ in outcome_counter.most_common(5)]
            if not theme_labels:
                theme_labels = ["Overall"]

        themes_out: List[Dict[str, Any]] = []
        for label in theme_labels:
            members = []
            for ex in extractions:
                out = ex.get("outcome") or ex.get("primary_outcome") or ""
                if label == "Overall" or str(out).strip() == label:
                    members.append(ex.get("study_id") or ex.get("title") or "?")
            themes_out.append(
                {
                    "name": label,
                    "description": (
                        f"Studies reporting on '{label}' "
                        f"(n={len(members)})."
                    ),
                    "studies": members,
                }
            )

        # --- Comparison table -------------------------------------------
        comparison_table: Any = None
        try:
            pd = _ensure_pandas()
            cols = [
                c for c in self.DEFAULT_PIVOT_COLUMNS
                if any(c in ex for ex in extractions)
            ]
            if cols:
                df = pd.DataFrame(extractions)
                # Restrict to known columns present.
                cols_present = [c for c in cols if c in df.columns]
                comparison_table = df[cols_present] if cols_present else df
        except ImportError:
            logger.info("pandas unavailable — comparison_table left as None.")
            comparison_table = None
        except Exception:  # noqa: BLE001 — fall back to None
            logger.exception("Failed to build comparison table.")
            comparison_table = None

        # --- Key findings -----------------------------------------------
        key_findings: List[str] = []
        if comparison_table is not None:
            try:
                n_studies = len(comparison_table)
                key_findings.append(
                    f"Synthesised {n_studies} studies across "
                    f"{len(theme_labels)} theme(s)."
                )
                if "effect_estimate" in comparison_table.columns:
                    est = comparison_table["effect_estimate"].dropna()
                    if len(est) > 0:
                        direction = "positive" if est.mean() >= 0 else "negative"
                        key_findings.append(
                            f"Mean effect estimate across {len(est)} "
                            f"reporting studies: {est.mean():.3f} "
                            f"(direction: {direction})."
                        )
                if "rob_overall" in comparison_table.columns:
                    rob = comparison_table["rob_overall"].value_counts().to_dict()
                    key_findings.append(f"RoB distribution: {rob}.")
            except Exception:  # noqa: BLE001
                logger.exception("Key-findings derivation failed.")
        else:
            key_findings.append(
                f"Synthesised {len(extractions)} studies across "
                f"{len(theme_labels)} theme(s) (no comparison table)."
            )

        # --- Narrative text ---------------------------------------------
        narrative_lines: List[str] = ["# Narrative Synthesis", ""]
        narrative_lines.append(
            f"## Overview\n\nA total of {len(extractions)} studies were "
            f"synthesised thematically under {len(theme_labels)} theme(s): "
            f"{', '.join(theme_labels)}."
        )
        for theme in themes_out:
            narrative_lines.append(f"\n## Theme: {theme['name']}\n")
            narrative_lines.append(theme["description"])
            narrative_lines.append("Studies: " + ", ".join(map(str, theme["studies"])))
        narrative_lines.append("\n## Key findings\n")
        for kf in key_findings:
            narrative_lines.append(f"- {kf}")
        narrative_lines.append("\n## Limitations\n")
        for lim in self._derive_limitations(extractions, comparison_table):
            narrative_lines.append(f"- {lim}")

        return NarrativeResult(
            themes=themes_out,
            narrative_text="\n".join(narrative_lines),
            comparison_table=comparison_table,
            key_findings=key_findings,
            limitations=self._derive_limitations(extractions, comparison_table),
        )

    @staticmethod
    def _derive_limitations(
        extractions: Sequence[Dict[str, Any]], table: Any
    ) -> List[str]:
        lims: List[str] = []
        n = len(extractions)
        if n < 5:
            lims.append(
                f"Small evidence base (n={n}); narrative findings are "
                f"tentative and should be interpreted with caution."
            )
        # Heterogeneity in study designs.
        designs = {ex.get("study_design") or ex.get("design") for ex in extractions}
        if len(designs) > 3:
            lims.append(
                "Substantial methodological heterogeneity across designs; "
                "comparison is qualitative only."
            )
        # Missing effect estimates.
        n_missing = sum(
            1
            for ex in extractions
            if not ex.get("effect_estimate") and not ex.get("primary_outcome_measure")
        )
        if n_missing > n // 2:
            lims.append(
                f"More than half of studies ({n_missing}/{n}) lacked a "
                f"quantitative effect estimate."
            )
        if not lims:
            lims.append(
                "No major methodological limitations identified."
            )
        return lims


# ---------------------------------------------------------------------------
# Thematic synthesis
# ---------------------------------------------------------------------------
@dataclass
class Theme:
    """A qualitative theme.

    Attributes:
        name: Theme label.
        description: One-sentence description.
        frequency: Number of textual_data instances supporting the theme.
        supporting_quotes: Up to 5 representative quotes.
        sub_themes: Sub-theme labels.
    """

    name: str
    description: str = ""
    frequency: int = 0
    supporting_quotes: List[str] = field(default_factory=list)
    sub_themes: List[str] = field(default_factory=list)


@dataclass
class ThematicResult:
    """Outcome of a :class:`ThematicSynthesis.synthesize` call.

    Attributes:
        themes: List of :class:`Theme`.
        theme_hierarchy: :class:`networkx.Graph` with theme/sub-theme
            edges (lazy — ``None`` if networkx unavailable).
        quotes_per_theme: ``{theme_name: [quotes]}``.
    """

    themes: List[Theme] = field(default_factory=list)
    theme_hierarchy: Any = None
    quotes_per_theme: Dict[str, List[str]] = field(default_factory=dict)


class ThematicSynthesis:
    """Thematic / framework / grounded synthesis of textual data.

    Methods supported (via the ``method`` argument to :meth:`synthesize`):

    * ``"thematic"`` (default) — Thomas & Harden (2008) inductive
      thematic synthesis: line-by-line coding → descriptive themes →
      analytical themes.
    * ``"framework"`` — Gale et al. (2013) framework analysis: charting
      into a matrix of pre-specified themes.
    * ``"grounded"`` — Glaser & Strauss (1967) constant comparison:
      codes are merged until saturation.

    The implementation is intentionally lightweight (regex + frequency
    analysis); for serious qualitative work the user should export the
    line-by-line codes and continue in NVivo / ATLAS.ti. The point of
    this implementation is to *bootstrap* the analysis deterministically
    inside the suite.
    """

    SUPPORTED_METHODS = ("thematic", "framework", "grounded")

    # A small set of seed "framework" themes used in framework mode when
    # the caller supplies no explicit theme list. These come from
    # common implementation-research frameworks.
    _DEFAULT_FRAMEWORK_THEMES = (
        "barriers",
        "facilitators",
        "context",
        "intervention",
        "outcomes",
        "implementation",
    )

    def synthesize(
        self,
        textual_data: Sequence[str],
        method: str = "thematic",
        max_themes: int = 10,
    ) -> ThematicResult:
        """Synthesise textual data into themes.

        Args:
            textual_data: List of strings (sentences, paragraphs,
                interview excerpts, etc.).
            method: One of :data:`SUPPORTED_METHODS`.
            max_themes: Maximum number of top-level themes.

        Returns:
            A :class:`ThematicResult`.
        """
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(
                f"Unknown method {method!r}; choose from {self.SUPPORTED_METHODS}"
            )
        if not textual_data:
            return ThematicResult()

        # Tokenise all texts once.
        tokenised = [list(set(_tokenize(t))) for t in textual_data]

        # --- Build candidate themes ------------------------------------
        if method == "framework":
            seeds = list(self._DEFAULT_FRAMEWORK_THEMES)
        else:
            # thematic / grounded: derive from frequency.
            freq = Counter(tok for toks in tokenised for tok in toks)
            seeds = [t for t, _ in freq.most_common(max_themes * 3)]
            if not seeds:
                return ThematicResult()

        # Cluster seeds by co-occurrence so related codes become one theme.
        cooccur: Counter = Counter()
        for toks in tokenised:
            for i, a in enumerate(toks):
                for b in toks[i + 1 :]:
                    cooccur[(a, b)] += 1
        clusters = self._cluster_seeds(seeds, cooccur, max_themes)

        # --- Build Theme objects --------------------------------------
        themes: List[Theme] = []
        quotes_per_theme: Dict[str, List[str]] = {}
        for cluster in clusters:
            if not cluster:
                continue
            name = cluster[0] if len(cluster) == 1 else f"{cluster[0]} + {len(cluster) - 1}"
            supporting: List[str] = []
            n_support = 0
            for text, toks in zip(textual_data, tokenised):
                if any(s in toks for s in cluster):
                    n_support += 1
                    if len(supporting) < 5:
                        supporting.append(text.strip()[:200])
            themes.append(
                Theme(
                    name=name,
                    description=f"Cluster of related codes: {', '.join(cluster)}.",
                    frequency=n_support,
                    supporting_quotes=supporting,
                    sub_themes=cluster[1:] if len(cluster) > 1 else [],
                )
            )
            quotes_per_theme[name] = supporting
        themes.sort(key=lambda t: t.frequency, reverse=True)

        # --- Theme hierarchy ------------------------------------------
        hierarchy: Any = None
        try:
            nx = _ensure_networkx()
            g = nx.Graph()
            for theme in themes:
                g.add_node(theme.name, frequency=theme.frequency)
                for sub in theme.sub_themes:
                    g.add_node(sub, frequency=0)
                    g.add_edge(theme.name, sub)
            hierarchy = g
        except ImportError:
            logger.info("networkx unavailable — theme_hierarchy left as None.")

        return ThematicResult(
            themes=themes,
            theme_hierarchy=hierarchy,
            quotes_per_theme=quotes_per_theme,
        )

    @staticmethod
    def _cluster_seeds(
        seeds: Sequence[str],
        cooccur: Counter,
        max_clusters: int,
    ) -> List[List[str]]:
        """Greedy co-occurrence clustering of seeds."""
        clusters: List[List[str]] = []
        assigned: set = set()
        # Sort seeds by descending marginal frequency (preserved order).
        for seed in seeds:
            if seed in assigned:
                continue
            cluster = [seed]
            assigned.add(seed)
            # Greedily attach seeds that co-occur most strongly with seed.
            partners = sorted(
                (
                    (cnt, other)
                    for (a, b), cnt in cooccur.items()
                    for other in ((b if a == seed else None),)
                    if other is not None and other not in assigned
                ),
                reverse=True,
            )
            for cnt, other in partners[:2]:
                if cnt >= 2 and other not in assigned:
                    cluster.append(other)
                    assigned.add(other)
            clusters.append(cluster)
            if len(clusters) >= max_clusters:
                break
        return clusters


# ---------------------------------------------------------------------------
# Qualitative Comparative Analysis (QCA)
# ---------------------------------------------------------------------------
@dataclass
class QCAResult:
    """Outcome of a :class:`QualitativeComparativeAnalysis.run` call.

    Attributes:
        truth_table: :class:`pandas.DataFrame` with one row per
            condition configuration (lazy — ``None`` if pandas missing).
        necessary_conditions: Conditions whose consistency ≥ 0.9.
        sufficient_conditions: Configurations whose consistency ≥ 0.75
            and frequency ≥ 1.
        consistency: Solution-wide consistency (mean of sufficient rows).
        coverage: Solution-wide coverage (proportion of cases explained).
    """

    truth_table: Any = None
    necessary_conditions: List[str] = field(default_factory=list)
    sufficient_conditions: List[List[str]] = field(default_factory=list)
    consistency: float = 0.0
    coverage: float = 0.0


class QualitativeComparativeAnalysis:
    """Fuzzy-set / crisp-set QCA (Ragin 1987, 2008).

    The implementation supports both crisp-set (0/1) and fuzzy-set
    (0..1) conditions and outcomes. Necessary-condition analysis uses
    Ragin's consistency formula ``consistency = Σ min(x_i, y_i) / Σ y_i``;
    sufficient-condition analysis uses
    ``consistency = Σ min(x_i, y_i) / Σ x_i`` and
    ``coverage   = Σ min(x_i, y_i) / Σ y_i`` (overall coverage).
    """

    # Default thresholds (Ragin convention).
    NECESSARY_CONSISTENCY_THRESHOLD = 0.9
    SUFFICIENT_CONSISTENCY_THRESHOLD = 0.75

    def calibrate(
        self,
        value: float,
        threshold_full: float,
        threshold_cross: float,
        threshold_none: float,
    ) -> float:
        """Fuzzy-set calibration via the indirect (Ragin 2008) method.

        Maps a raw value onto the [0, 1] interval using three qualitative
        anchors: ``threshold_full`` (fuzzy = 1.0), ``threshold_cross``
        (fuzzy = 0.5), ``threshold_none`` (fuzzy = 0.0). Values outside
        the [none, full] range are clamped to 0/1.

        Args:
            value: Raw value to calibrate.
            threshold_full: Raw value mapped to fuzzy-set membership 1.0.
            threshold_cross: Raw value mapped to fuzzy-set membership 0.5
                (the point of maximum ambiguity).
            threshold_none: Raw value mapped to fuzzy-set membership 0.0.

        Returns:
            Calibrated membership score in [0, 1].
        """
        if threshold_full == threshold_none:
            raise ValueError("threshold_full must differ from threshold_none")
        if not (threshold_none <= threshold_cross <= threshold_full) and not (
            threshold_none >= threshold_cross >= threshold_full
        ):
            raise ValueError(
                "threshold_cross must lie between threshold_none and threshold_full"
            )
        if value >= threshold_full:
            return 1.0
        if value <= threshold_none:
            return 0.0
        # Logit-style calibration centred on the crossover.
        # Use a logistic with steepness inferred from the anchor distances.
        span = max(
            abs(threshold_full - threshold_none),
            1e-9,
        )
        # Logistic steepness: ~5 / span gives a reasonable S-curve.
        k = 5.0 / span
        x0 = threshold_cross
        import math

        raw = 1.0 / (1.0 + math.exp(-k * (value - x0)))
        # Clamp to [0, 1] for safety.
        return float(max(0.0, min(1.0, raw)))

    def run(
        self,
        extractions: Sequence[Dict[str, Any]],
        outcome: str,
        conditions: Sequence[str],
    ) -> QCAResult:
        """Run QCA on ``extractions``.

        Args:
            extractions: List of dicts mapping condition / outcome names
                to values in [0, 1] (fuzzy) or {0, 1} (crisp).
            outcome: Name of the outcome field.
            conditions: Names of the condition fields.

        Returns:
            A :class:`QCAResult` with truth table and necessary /
            sufficient conditions.
        """
        if not extractions:
            return QCAResult()
        if not conditions:
            return QCAResult()
        if outcome not in extractions[0]:
            raise KeyError(f"Outcome {outcome!r} not found in extractions[0]")

        # Build truth table: one row per configuration.
        config_rows: Dict[Tuple[int, ...], List[Dict[str, Any]]] = defaultdict(list)
        for ex in extractions:
            y = float(ex.get(outcome, 0.0) or 0.0)
            config = tuple(
                1 if float(ex.get(c, 0.0) or 0.0) > 0.5 else 0 for c in conditions
            )
            config_rows[config].append({**ex, "_y": y, "_config": config})

        try:
            pd = _ensure_pandas()
            rows = []
            for config, cases in config_rows.items():
                ys = [c["_y"] for c in cases]
                # Sufficient-condition consistency = Σ min(X, Y) / Σ X
                # — for a configuration, X = membership in the config (1 here).
                numerator = sum(min(1.0, y) for y in ys)
                suff_consistency = numerator / max(1e-9, float(len(ys)))
                # Outcome frequency = proportion of cases with Y > 0.5.
                freq = sum(1 for y in ys if y > 0.5)
                rows.append(
                    {
                        **{c: config[i] for i, c in enumerate(conditions)},
                        "n": len(cases),
                        "outcome_freq": freq,
                        "suff_consistency": suff_consistency,
                        "cases": ";".join(
                            str(c.get("study_id") or c.get("title") or i)
                            for i, c in enumerate(cases)
                        ),
                    }
                )
            truth_df = pd.DataFrame(rows)
        except ImportError:
            logger.info("pandas unavailable — truth_table left as None.")
            truth_df = None

        # --- Necessary conditions -------------------------------------
        # Necessary-condition consistency = Σ min(X, Y) / Σ Y over cases.
        necessary: List[str] = []
        for cond in conditions:
            num = 0.0
            denom = 0.0
            for ex in extractions:
                x = float(ex.get(cond, 0.0) or 0.0)
                y = float(ex.get(outcome, 0.0) or 0.0)
                num += min(x, y)
                denom += y
            if denom < 1e-9:
                continue
            cons = num / denom
            if cons >= self.NECESSARY_CONSISTENCY_THRESHOLD:
                necessary.append(cond)

        # --- Sufficient conditions ------------------------------------
        # Configurations with suff_consistency ≥ threshold AND freq ≥ 1.
        sufficient: List[List[str]] = []
        weighted_consistencies: List[float] = []
        weighted_coverage_num = 0.0
        weighted_coverage_den = 0.0
        for config, cases in config_rows.items():
            ys = [c["_y"] for c in cases]
            num = sum(min(1.0, y) for y in ys)
            cons = num / max(1e-9, float(len(ys)))
            freq = sum(1 for y in ys if y > 0.5)
            if cons >= self.SUFFICIENT_CONSISTENCY_THRESHOLD and freq >= 1:
                # The configuration is a conjunction of present (+cond) and
                # absent (~cond) conditions.
                path: List[str] = []
                for i, cond in enumerate(conditions):
                    path.append(cond if config[i] == 1 else f"~{cond}")
                sufficient.append(path)
                weighted_consistencies.append(cons)
            # Coverage numerator sums min(X, Y) over sufficient configs.
            weighted_coverage_num += num
            weighted_coverage_den += sum(ys)

        overall_consistency = (
            sum(weighted_consistencies) / max(1, len(weighted_consistencies))
            if weighted_consistencies
            else 0.0
        )
        overall_coverage = (
            weighted_coverage_num / max(1e-9, weighted_coverage_den)
            if weighted_coverage_den > 0
            else 0.0
        )

        return QCAResult(
            truth_table=truth_df,
            necessary_conditions=necessary,
            sufficient_conditions=sufficient,
            consistency=round(overall_consistency, 3),
            coverage=round(overall_coverage, 3),
        )


# ---------------------------------------------------------------------------
# Meta-synthesis (qualitative cross-study synthesis)
# ---------------------------------------------------------------------------
@dataclass
class MetaSynthesisResult:
    """Outcome of a :class:`MetaSynthesis.synthesize` call.

    Attributes:
        themes: List of cross-study themes.
        conceptual_model: :class:`networkx.DiGraph` of theme → sub-theme
            / proposition links (lazy — ``None`` if networkx unavailable).
        propositions: Concrete testable propositions.
    """

    themes: List[Theme] = field(default_factory=list)
    conceptual_model: Any = None
    propositions: List[str] = field(default_factory=list)


class MetaSynthesis:
    """Thematic meta-synthesis across qualitative studies (Noblit & Hare, 1988).

    Aggregates themes across studies, builds a conceptual model graph,
    and derives testable propositions. Uses :class:`ThematicSynthesis`
    internally for the line-by-line coding step.
    """

    def synthesize(
        self,
        studies: Sequence[Dict[str, Any]],
        max_themes: int = 10,
    ) -> MetaSynthesisResult:
        """Synthesise a list of qualitative-study dicts.

        Args:
            studies: List of dicts each typically containing ``study_id``,
                ``findings`` / ``themes_identified`` / ``key_quotes``
                text, and optional ``methodology``.
            max_themes: Max number of themes to retain.

        Returns:
            A :class:`MetaSynthesisResult`.
        """
        if not studies:
            return MetaSynthesisResult()
        # Pull qualitative text out of each study.
        texts: List[str] = []
        for s in studies:
            parts = []
            for key in ("findings", "themes_identified", "key_quotes",
                        "key_findings_qual", "results"):
                v = s.get(key)
                if v:
                    parts.append(str(v))
            if parts:
                texts.append("\n".join(parts))

        themes_result = ThematicSynthesis().synthesize(
            texts, method="thematic", max_themes=max_themes
        )

        # Derive propositions of the form:
        #   "Where <theme>, then <outcome implication>."
        propositions: List[str] = []
        for theme in themes_result.themes[:max_themes]:
            if theme.frequency < 2:
                continue
            propositions.append(
                f"Where the theme '{theme.name}' is salient, the phenomenon "
                f"tends to manifest in ways described by its supporting "
                f"quotes; further empirical testing is warranted."
            )

        # Conceptual model as a DiGraph of themes → propositions.
        conceptual: Any = None
        try:
            nx = _ensure_networkx()
            g = nx.DiGraph()
            for theme in themes_result.themes[:max_themes]:
                g.add_node(theme.name, kind="theme",
                           frequency=theme.frequency)
                for sub in theme.sub_themes:
                    g.add_node(sub, kind="sub_theme")
                    g.add_edge(theme.name, sub)
            for i, prop in enumerate(propositions):
                node = f"prop_{i + 1}"
                g.add_node(node, kind="proposition", text=prop)
                if themes_result.themes:
                    g.add_edge(themes_result.themes[0].name, node)
            conceptual = g
        except ImportError:
            logger.info("networkx unavailable — conceptual_model left as None.")

        return MetaSynthesisResult(
            themes=themes_result.themes,
            conceptual_model=conceptual,
            propositions=propositions,
        )


# ---------------------------------------------------------------------------
# Best-Fit Framework Synthesis
# ---------------------------------------------------------------------------
class BestFitFrameworkSynthesis:
    """Carroll et al. (2013) best-fit framework synthesis for policy research.

    The method takes an *a priori* framework (expressed as a list of
    column / category names) and maps each extracted finding into the
    framework column it best fits.  Findings that do not fit any column
    are surfaced as "off-framework" themes that may warrant framework
    revision.
    """

    def synthesize(
        self,
        studies: Sequence[Dict[str, Any]],
        framework_columns: Sequence[str],
    ) -> Dict[str, Any]:
        """Synthesise studies into a framework matrix.

        Args:
            studies: List of dicts each containing at least a textual
                ``findings`` / ``key_findings`` field.
            framework_columns: Pre-specified framework categories.

        Returns:
            A dict with keys:
              * ``matrix``: ``{column: [study_ids]}`` mapping.
              * ``off_framework``: list of "(study_id, snippet)" tuples
                for findings that did not match any column.
              * ``summary``: per-column count + total off-framework.
              * ``coverage``: proportion of studies that mapped to ≥1 col.
        """
        if not framework_columns:
            raise ValueError("framework_columns must not be empty")
        cols = list(framework_columns)
        # Lowercase column tokens for matching.
        col_tokens = {
            col: set(_tokenize(col)) | {col.lower()}
            for col in cols
        }
        matrix: Dict[str, List[str]] = {col: [] for col in cols}
        off_framework: List[Tuple[str, str]] = []
        n_mapped_studies = 0
        for s in studies:
            sid = str(s.get("study_id") or s.get("id") or "?")
            text_parts = []
            for key in ("findings", "key_findings", "themes_identified",
                        "key_findings_qual", "results"):
                v = s.get(key)
                if v:
                    text_parts.append(str(v))
            text = "\n".join(text_parts)
            if not text:
                continue
            text_toks = set(_tokenize(text))
            matched_any = False
            for col in cols:
                overlap = text_toks & col_tokens[col]
                if overlap:
                    matrix[col].append(sid)
                    matched_any = True
            if not matched_any:
                off_framework.append((sid, text[:200]))
            if matched_any:
                n_mapped_studies += 1

        coverage = (
            n_mapped_studies / len(studies) if studies else 0.0
        )
        summary = {
            col: len(matrix[col]) for col in cols
        }
        summary["off_framework_count"] = len(off_framework)
        summary["coverage"] = round(coverage, 3)
        return {
            "matrix": matrix,
            "off_framework": off_framework,
            "summary": summary,
            "coverage": coverage,
        }


__all__ = [
    "NarrativeResult",
    "NarrativeSynthesis",
    "Theme",
    "ThematicResult",
    "ThematicSynthesis",
    "QCAResult",
    "QualitativeComparativeAnalysis",
    "MetaSynthesisResult",
    "MetaSynthesis",
    "BestFitFrameworkSynthesis",
]
