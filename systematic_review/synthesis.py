"""Evidence synthesis methods for systematic reviews.

This module provides:

* :class:`SynthesisMethod`              — enum of supported methods
* :class:`NarrativeSynthesis`           — narrative / tabular synthesis
* :class:`QualitativeComparativeAnalysis` — set-theoretic QCA
* :class:`SWiMReportingChecklist`        — Synthesis Without Meta-analysis
  reporting checklist (9 items)
* :class:`SynthesisFactory`              — factory returning a synthesizer

The factory returns a :class:`Synthesizer` instance whose
:meth:`Synthesizer.synthesize` method takes a list of
:class:`~systematic_review.data_extraction.DataExtractionForm` objects
and returns a synthesis-specific result object.

For meta-analysis, the factory delegates to the sibling
:mod:`meta_analysis` package when available — if it is not yet
installed, an explicit :class:`NotImplementedError` is raised so the
caller can fall back to narrative synthesis.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Synthesis method enum
# ---------------------------------------------------------------------------

class SynthesisMethod(Enum):
    """Enumeration of supported synthesis methods."""

    NARRATIVE = "narrative"
    NARRATIVE_TABULAR = "narrative_tabular"
    META_ANALYSIS = "meta_analysis"
    NETWORK_META_ANALYSIS = "network_meta_analysis"
    QUALITATIVE_COMPARATIVE = "qualitative_comparative"


# ---------------------------------------------------------------------------
# Narrative synthesis
# ---------------------------------------------------------------------------

@dataclass
class NarrativeSummary:
    """Outcome of a :class:`NarrativeSynthesis`.

    Attributes:
        themes: List of theme dicts, each ``{'name': str, 'studies':
            List[str], 'description': str}``.
        summary_text: Markdown-formatted synthesis narrative.
        comparison_table: :class:`pandas.DataFrame` (or empty DataFrame)
            comparing studies on key dimensions.
        key_findings: List of headline findings.
    """

    themes: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""
    comparison_table: Any = None
    key_findings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this summary."""
        ct = self.comparison_table
        if ct is not None and hasattr(ct, "to_dict"):
            ct_out = ct.to_dict(orient="records")
        elif isinstance(ct, list):
            ct_out = ct
        else:
            ct_out = []
        return {
            "themes": list(self.themes),
            "summary_text": self.summary_text,
            "comparison_table": ct_out,
            "key_findings": list(self.key_findings),
        }


class NarrativeSynthesis:
    """Narrative / tabular synthesis of included studies.

    The synthesizer groups studies by intervention name and outcome
    name, builds a comparison table, and produces a Markdown narrative
    summary with key findings.
    """

    DEFAULT_COMPARISON_COLUMNS: List[str] = [
        "study_id",
        "year",
        "study_design",
        "n_total",
        "intervention_name",
        "comparator_name",
        "primary_outcome",
        "effect_size_summary",
    ]

    def synthesize(self, extractions: List[Any]) -> NarrativeSummary:
        """Run the narrative synthesis.

        Args:
            extractions: List of :class:`DataExtractionForm` objects
                (or duck-typed objects exposing the same attributes).

        Returns:
            A populated :class:`NarrativeSummary`.
        """
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "pandas is required for NarrativeSynthesis.synthesize()"
            ) from exc

        rows: List[Dict[str, Any]] = []
        themes: List[Dict[str, Any]] = []
        key_findings: List[str] = []
        for form in extractions:
            row = {
                "study_id": getattr(form, "study_id", ""),
                "year": getattr(form, "year", None),
                "study_design": getattr(form, "study_design", ""),
                "n_total": getattr(getattr(form, "population", None), "n_total", None),
                "intervention_name": getattr(
                    getattr(form, "intervention", None), "name", ""
                ),
                "comparator_name": getattr(
                    getattr(form, "intervention", None), "comparator_name", ""
                ),
            }
            primary = getattr(form, "primary_outcomes", []) or []
            primary_name = ""
            if primary:
                primary_name = getattr(primary[0], "name", "") or (
                    primary[0].get("name", "") if isinstance(primary[0], dict) else ""
                )
            row["primary_outcome"] = primary_name
            # effect-size summary (mean diff or events/total)
            results = getattr(form, "results", None)
            effect_summary = ""
            if results is not None:
                es_list = getattr(results, "effect_sizes", []) or []
                if es_list:
                    first = es_list[0]
                    if isinstance(first, dict):
                        if first.get("mean") is not None:
                            effect_summary = (
                                f"mean={first.get('mean')} (n={first.get('n')})"
                            )
                        elif first.get("events") is not None:
                            effect_summary = (
                                f"{first.get('events')}/{first.get('total')} events"
                            )
                        elif first.get("hazard_ratio") is not None:
                            effect_summary = (
                                f"HR={first.get('hazard_ratio')} "
                                f"({first.get('ci_lower')}-{first.get('ci_upper')})"
                            )
                    else:
                        if getattr(first, "mean", None) is not None:
                            effect_summary = (
                                f"mean={first.mean} (n={first.n})"
                            )
                        elif getattr(first, "events", None) is not None:
                            effect_summary = (
                                f"{first.events}/{first.total} events"
                            )
                        elif getattr(first, "hazard_ratio", None) is not None:
                            effect_summary = (
                                f"HR={first.hazard_ratio} "
                                f"({first.ci_lower}-{first.ci_upper})"
                            )
            row["effect_size_summary"] = effect_summary
            rows.append(row)

        comparison_table = pd.DataFrame(rows, columns=self.DEFAULT_COMPARISON_COLUMNS)

        # themes grouped by intervention
        themes_by_intervention: Dict[str, List[str]] = {}
        for row in rows:
            intervention = row["intervention_name"] or "(unspecified)"
            themes_by_intervention.setdefault(intervention, []).append(
                row["study_id"]
            )
        for intervention, sids in themes_by_intervention.items():
            themes.append({
                "name": f"Intervention: {intervention}",
                "studies": sids,
                "description": (
                    f"{len(sids)} stud{'y' if len(sids)==1 else 'ies'} "
                    f"evaluated {intervention}."
                ),
            })

        # key findings
        n_studies = len(rows)
        n_interventions = len(themes_by_intervention)
        if n_studies:
            key_findings.append(
                f"A total of {n_studies} studies were synthesised, "
                f"covering {n_interventions} intervention{'s' if n_interventions != 1 else ''}."
            )
        if rows:
            designs = [r["study_design"] for r in rows if r["study_design"]]
            if designs:
                from collections import Counter
                design_counts = Counter(designs)
                most_common_design, n = design_counts.most_common(1)[0]
                key_findings.append(
                    f"The most common study design was "
                    f"'{most_common_design}' ({n}/{n_studies})."
                )

        # narrative summary (markdown)
        md_lines: List[str] = ["# Narrative Synthesis", ""]
        md_lines.append(f"## Overview")
        md_lines.append("")
        md_lines.append(
            f"This synthesis summarises {n_studies} included studies."
        )
        md_lines.append("")
        md_lines.append("## Themes")
        md_lines.append("")
        for t in themes:
            md_lines.append(f"### {t['name']}")
            md_lines.append("")
            md_lines.append(t["description"])
            md_lines.append("")
            md_lines.append(
                "Studies: " + ", ".join(t["studies"])
            )
            md_lines.append("")
        md_lines.append("## Key findings")
        md_lines.append("")
        for kf in key_findings:
            md_lines.append(f"- {kf}")
        md_lines.append("")
        md_lines.append("## Comparison table")
        md_lines.append("")
        md_lines.append(_df_to_markdown(comparison_table))

        return NarrativeSummary(
            themes=themes,
            summary_text="\n".join(md_lines),
            comparison_table=comparison_table,
            key_findings=key_findings,
        )


def _df_to_markdown(df: Any) -> str:
    """Render a pandas DataFrame as a Markdown table (best-effort)."""
    if df is None or getattr(df, "empty", True):
        return "_(no data)_"
    try:
        # pandas >=1.0 has to_markdown
        md = df.to_markdown(index=False)
        return str(md)
    except Exception:
        cols = list(df.columns)
        lines = ["| " + " | ".join(str(c) for c in cols) + " |",
                 "|" + "|".join(["---"] * len(cols)) + "|"]
        for _, row in df.iterrows():
            lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Qualitative Comparative Analysis (QCA)
# ---------------------------------------------------------------------------

@dataclass
class QCAResult:
    """Outcome of a :class:`QualitativeComparativeAnalysis`.

    Attributes:
        outcome: Name of the outcome analysed.
        conditions: List of condition names analysed.
        truth_table: :class:`pandas.DataFrame` of the truth table.
        necessary_conditions: List of (condition, consistency, coverage).
        sufficient_conditions: List of (condition_set, consistency,
            coverage).
        summary_text: Markdown summary.
    """

    outcome: str = ""
    conditions: List[str] = field(default_factory=list)
    truth_table: Any = None
    necessary_conditions: List[Dict[str, Any]] = field(default_factory=list)
    sufficient_conditions: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this result."""
        tt = self.truth_table
        if tt is not None and hasattr(tt, "to_dict"):
            tt_out = tt.to_dict(orient="records")
        elif isinstance(tt, list):
            tt_out = tt
        else:
            tt_out = []
        return {
            "outcome": self.outcome,
            "conditions": list(self.conditions),
            "truth_table": tt_out,
            "necessary_conditions": list(self.necessary_conditions),
            "sufficient_conditions": list(self.sufficient_conditions),
            "summary_text": self.summary_text,
        }


class QualitativeComparativeAnalysis:
    """Set-theoretic Qualitative Comparative Analysis (QCA).

    This implementation provides a *crisp-set* QCA: each condition and
    the outcome are coded as binary (0/1). It computes:

    * **Necessary conditions**: a condition is necessary for the
      outcome when the outcome never occurs without it. Reported as
      ``(condition, consistency, coverage)``.
    * **Sufficient conditions**: a condition (or conjunction) is
      sufficient for the outcome when its presence always produces the
      outcome. Reported as ``(condition_set, consistency, coverage)``.
    * **Truth table**: the full configuration x outcome frequency
      table.

    Args:
        consistency_threshold: Minimum consistency for a condition
            to be considered necessary (default 0.9).
        coverage_threshold: Minimum coverage for a condition to be
            reported as sufficient (default 0.5).
    """

    def __init__(
        self,
        consistency_threshold: float = 0.9,
        coverage_threshold: float = 0.5,
    ) -> None:
        self.consistency_threshold = float(consistency_threshold)
        self.coverage_threshold = float(coverage_threshold)

    def run(
        self,
        extractions: List[Any],
        outcome: str,
        conditions: List[str],
    ) -> QCAResult:
        """Run QCA on a list of extraction forms.

        Args:
            extractions: List of :class:`DataExtractionForm` (or
                duck-typed objects). Each must expose ``study_id`` and
                a ``raw`` / attribute access pattern that lets us
                read boolean values for the ``outcome`` and each
                ``condition``.
            outcome: Name of the outcome (must be a key in each
                form's ``raw`` dict, or an attribute on the form).
            conditions: List of condition names (same access pattern).

        Returns:
            A populated :class:`QCAResult`.
        """
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "pandas is required for QualitativeComparativeAnalysis.run()"
            ) from exc

        # build a binary matrix (study x [conditions + outcome])
        rows: List[Dict[str, Any]] = []
        for form in extractions:
            sid = getattr(form, "study_id", None) or f"study_{len(rows)+1}"
            row: Dict[str, Any] = {"study_id": sid}
            # resolve outcome value
            out_val = self._resolve_value(form, outcome)
            row[outcome] = self._to_bool(out_val)
            for cond in conditions:
                row[cond] = self._to_bool(self._resolve_value(form, cond))
            rows.append(row)
        df = pd.DataFrame(rows)

        # truth table: group by configuration
        if df.empty:
            return QCAResult(
                outcome=outcome,
                conditions=list(conditions),
                truth_table=df,
                summary_text="No studies supplied to QCA.",
            )
        truth = (
            df.groupby(conditions + [outcome])
              .size()
              .reset_index(name="n")
              .sort_values(conditions)
        )

        # necessary conditions: outcome implies condition present.
        # i.e. consistency = P(condition=1 | outcome=1) = n(cond=1 & out=1) / n(out=1)
        necessary: List[Dict[str, Any]] = []
        out_pos = df[df[outcome] == 1]
        n_out_pos = len(out_pos)
        for cond in conditions:
            if n_out_pos == 0:
                consistency = 0.0
                coverage = 0.0
            else:
                both = len(out_pos[out_pos[cond] == 1])
                consistency = both / n_out_pos
                # coverage = n(out=1 & cond=1) / n(cond=1)
                cond_pos = df[df[cond] == 1]
                n_cond_pos = len(cond_pos)
                coverage = both / n_cond_pos if n_cond_pos else 0.0
            if consistency >= self.consistency_threshold:
                necessary.append({
                    "condition": cond,
                    "consistency": round(consistency, 3),
                    "coverage": round(coverage, 3),
                })

        # sufficient conditions: each single condition whose presence
        # always produces the outcome (consistency=1 above threshold)
        sufficient: List[Dict[str, Any]] = []
        for cond in conditions:
            cond_pos = df[df[cond] == 1]
            n_cond_pos = len(cond_pos)
            if n_cond_pos == 0:
                continue
            both = len(cond_pos[cond_pos[outcome] == 1])
            consistency = both / n_cond_pos
            # coverage relative to outcome: both / n_out_pos
            coverage = both / n_out_pos if n_out_pos else 0.0
            if consistency >= self.consistency_threshold and coverage >= self.coverage_threshold:
                sufficient.append({
                    "condition_set": [cond],
                    "consistency": round(consistency, 3),
                    "coverage": round(coverage, 3),
                })

        # narrative
        md = [
            f"# QCA Summary — outcome: `{outcome}`",
            "",
            f"**Conditions analysed:** {', '.join(conditions)}",
            f"**Studies (cases):** {len(df)}",
            f"**Cases with outcome present:** {n_out_pos}",
            "",
            "## Necessary conditions",
            "",
        ]
        if necessary:
            for n in necessary:
                md.append(
                    f"- `{n['condition']}` — consistency={n['consistency']}, "
                    f"coverage={n['coverage']}"
                )
        else:
            md.append("_(no condition met the necessary-condition threshold)_")
        md.append("")
        md.append("## Sufficient conditions")
        md.append("")
        if sufficient:
            for s in sufficient:
                md.append(
                    f"- `{' & '.join(s['condition_set'])}` — consistency={s['consistency']}, "
                    f"coverage={s['coverage']}"
                )
        else:
            md.append("_(no condition met the sufficient-condition threshold)_")
        md.append("")
        md.append("## Truth table")
        md.append("")
        md.append(_df_to_markdown(truth))

        return QCAResult(
            outcome=outcome,
            conditions=list(conditions),
            truth_table=truth,
            necessary_conditions=necessary,
            sufficient_conditions=sufficient,
            summary_text="\n".join(md),
        )

    @staticmethod
    def _resolve_value(form: Any, name: str) -> Any:
        """Resolve a value from a form by attribute or raw-dict key."""
        # direct attribute
        if hasattr(form, name):
            return getattr(form, name)
        # raw dict on form
        raw = getattr(form, "raw", None)
        if isinstance(raw, dict) and name in raw:
            return raw[name]
        # form.results.effect_sizes lookup by outcome name
        results = getattr(form, "results", None)
        if results is not None:
            es_list = getattr(results, "effect_sizes", None) or []
            for es in es_list:
                es_outcome = (
                    es.get("outcome") if isinstance(es, dict)
                    else getattr(es, "outcome", None)
                )
                if es_outcome == name:
                    if isinstance(es, dict):
                        # any non-null numeric field means "outcome present"
                        for k in ("mean", "events", "hazard_ratio"):
                            if es.get(k) is not None:
                                return 1
                        return 0
                    else:
                        for k in ("mean", "events", "hazard_ratio"):
                            if getattr(es, k, None) is not None:
                                return 1
                        return 0
        return None

    @staticmethod
    def _to_bool(value: Any) -> int:
        """Coerce an arbitrary value to a 0/1 integer."""
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return 1 if value != 0 else 0
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "y", "present", "high", "t"}:
                return 1
            if v in {"0", "false", "no", "n", "absent", "low", "f", ""}:
                return 0
            # any non-empty string = present
            return 1
        if isinstance(value, (list, dict)):
            return 1 if len(value) > 0 else 0
        return 0


# ---------------------------------------------------------------------------
# SWiM (Synthesis Without Meta-analysis) reporting checklist
# ---------------------------------------------------------------------------

class SWiMReportingChecklist:
    """SWiM (Synthesis Without Meta-analysis) reporting checklist.

    Nine items per the SWiM guideline (Campbell et al., BMJ 2020).
    Each item is recorded as a dict with keys ``item_number``,
    ``description``, ``reported`` (bool), and ``location_in_report``.
    """

    DEFAULT_ITEMS: List[Dict[str, Any]] = [
        {
            "item_number": 1,
            "description": (
                "Describe the rationale for including a synthesis without "
                "meta-analysis in the systematic review."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 2,
            "description": (
                "Describe the process used to group studies for synthesis."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 3,
            "description": (
                "Describe the standardised metric and transformation methods "
                "used."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 4,
            "description": (
                "Describe the methods used to tabulate or visually display "
                "results of individual studies and synthesis."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 5,
            "description": (
                "Describe the methods used to synthesise results across "
                "studies (narrative or tabular)."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 6,
            "description": (
                "Describe the methods used to prioritise results for "
                "synthesis and summary."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 7,
            "description": (
                "Describe the methods used to integrate the results of the "
                "synthesis with information from other sources."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 8,
            "description": (
                "Describe limitations of the synthesis methods used."
            ),
            "reported": False,
            "location_in_report": "",
        },
        {
            "item_number": 9,
            "description": (
                "Describe the source of funding and conflicts of interest "
                "for the synthesis."
            ),
            "reported": False,
            "location_in_report": "",
        },
    ]

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = [
            {**item} for item in self.DEFAULT_ITEMS
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mark_reported(self, item_number: int, location_in_report: str = "") -> None:
        """Mark a checklist item as reported.

        Args:
            item_number: Item number 1-9.
            location_in_report: Optional section/page reference.

        Raises:
            ValueError: If ``item_number`` is outside 1-9.
        """
        for item in self.items:
            if item["item_number"] == item_number:
                item["reported"] = True
                if location_in_report:
                    item["location_in_report"] = location_in_report
                return
        raise ValueError(f"Unknown SWiM item number: {item_number}")

    def mark_unreported(self, item_number: int) -> None:
        """Mark a checklist item as not reported."""
        for item in self.items:
            if item["item_number"] == item_number:
                item["reported"] = False
                return
        raise ValueError(f"Unknown SWiM item number: {item_number}")

    def completeness(self) -> float:
        """Return the proportion of items reported (0.0 - 1.0)."""
        if not self.items:
            return 0.0
        reported = sum(1 for i in self.items if i["reported"])
        return reported / len(self.items)

    def to_dict(self) -> List[Dict[str, Any]]:
        """Return a JSON-serialisable list of checklist items."""
        return [dict(i) for i in self.items]

    def to_markdown(self) -> str:
        """Return a Markdown rendering of the checklist."""
        lines: List[str] = ["# SWiM Reporting Checklist", ""]
        lines.append("| # | Description | Reported? | Location |")
        lines.append("|---|---|---|---|")
        for item in self.items:
            reported_str = "Yes" if item["reported"] else "No"
            desc = item["description"].replace("\n", " ").replace("|", "\\|")
            loc = (item.get("location_in_report") or "").replace("|", "\\|")
            lines.append(
                f"| {item['item_number']} | {desc} | {reported_str} | {loc} |"
            )
        lines.append("")
        lines.append(
            f"**Completeness: {int(self.completeness() * 100)}% "
            f"({sum(1 for i in self.items if i['reported'])}/{len(self.items)})**"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Synthesizer ABC + Factory
# ---------------------------------------------------------------------------

class Synthesizer(ABC):
    """Abstract base class for all synthesis methods."""

    @abstractmethod
    def synthesize(self, extractions: List[Any]) -> Any:
        """Run the synthesis on a list of extraction forms.

        Args:
            extractions: List of :class:`DataExtractionForm` (or
                duck-typed objects).

        Returns:
            A synthesis-method-specific result object.
        """
        raise NotImplementedError


class _NarrativeSynthesizer(Synthesizer):
    """Adapter wrapping :class:`NarrativeSynthesis` as a Synthesizer."""

    def __init__(self, **kwargs: Any) -> None:
        self._inner = NarrativeSynthesis()

    def synthesize(self, extractions: List[Any]) -> NarrativeSummary:
        return self._inner.synthesize(extractions)


class _QCASynthesizer(Synthesizer):
    """Adapter wrapping :class:`QualitativeComparativeAnalysis`."""

    def __init__(self, outcome: str = "", conditions: Optional[List[str]] = None,
                 **kwargs: Any) -> None:
        self._inner = QualitativeComparativeAnalysis()
        self._outcome = outcome
        self._conditions = list(conditions or [])

    def synthesize(self, extractions: List[Any]) -> QCAResult:
        if not self._outcome or not self._conditions:
            raise ValueError(
                "QCA synthesizer requires `outcome` and `conditions` "
                "keyword arguments."
            )
        return self._inner.run(extractions, self._outcome, self._conditions)


class _MetaAnalysisSynthesizer(Synthesizer):
    """Adapter that delegates to the sibling :mod:`meta_analysis` package."""

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs

    def synthesize(self, extractions: List[Any]) -> Any:
        try:
            from meta_analysis import MetaAnalysis  # type: ignore
        except ImportError as exc:
            raise NotImplementedError(
                "Meta-analysis synthesis requires the `meta_analysis` "
                "package, which is not yet installed in this environment. "
                "Falling back to narrative synthesis is recommended."
            ) from exc
        ma = MetaAnalysis(**self._kwargs)  # pragma: no cover - sibling API
        return ma.run(extractions)  # pragma: no cover


class _NetworkMetaAnalysisSynthesizer(Synthesizer):
    """Adapter that delegates to a sibling NMA implementation."""

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs

    def synthesize(self, extractions: List[Any]) -> Any:
        try:
            from meta_analysis import NetworkMetaAnalysis  # type: ignore
        except ImportError as exc:
            raise NotImplementedError(
                "Network meta-analysis requires the `meta_analysis` "
                "package, which is not yet installed."
            ) from exc
        nma = NetworkMetaAnalysis(**self._kwargs)  # pragma: no cover
        return nma.run(extractions)  # pragma: no cover


class SynthesisFactory:
    """Factory returning a synthesizer for a given :class:`SynthesisMethod`."""

    @staticmethod
    def create(method: Union[str, SynthesisMethod], **kwargs: Any) -> Synthesizer:
        """Create a synthesizer for ``method``.

        Args:
            method: A :class:`SynthesisMethod` member or its string
                value (e.g. ``'narrative'``, ``'meta_analysis'``).
            **kwargs: Method-specific keyword arguments.

        Returns:
            A :class:`Synthesizer` instance.

        Raises:
            ValueError: If ``method`` is not a supported synthesis method.
        """
        if isinstance(method, str):
            method = _coerce_method(method)
        if not isinstance(method, SynthesisMethod):
            raise ValueError(f"Unsupported synthesis method: {method!r}")
        if method == SynthesisMethod.NARRATIVE:
            return _NarrativeSynthesizer(**kwargs)
        if method == SynthesisMethod.NARRATIVE_TABULAR:
            return _NarrativeSynthesizer(**kwargs)
        if method == SynthesisMethod.QUALITATIVE_COMPARATIVE:
            return _QCASynthesizer(**kwargs)
        if method == SynthesisMethod.META_ANALYSIS:
            return _MetaAnalysisSynthesizer(**kwargs)
        if method == SynthesisMethod.NETWORK_META_ANALYSIS:
            return _NetworkMetaAnalysisSynthesizer(**kwargs)
        raise ValueError(f"Unsupported synthesis method: {method!r}")


def _coerce_method(value: str) -> SynthesisMethod:
    """Coerce a string to a :class:`SynthesisMethod`."""
    v = (value or "").strip().lower()
    for m in SynthesisMethod:
        if m.value == v or m.name.lower() == v:
            return m
    raise ValueError(
        f"Unknown SynthesisMethod: {value!r}. "
        f"Available: {[m.value for m in SynthesisMethod]}"
    )
