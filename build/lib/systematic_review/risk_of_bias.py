"""Risk-of-bias (RoB) assessment tools for systematic reviews.

This module provides four standard RoB assessment tools, all derived
from the abstract :class:`RiskOfBiasTool`:

* :class:`CochraneRoB2`        — Cochrane Risk of Bias 2 (RCTs)
* :class:`ROBINS_I`            — ROBINS-I (non-randomised studies)
* :class:`QUADAS2`             — QUADAS-2 (diagnostic accuracy studies)
* :class:`NewcastleOttawaScale` — Newcastle-Ottawa Scale (cohort/case-control)

Each tool implements:

* :meth:`assess(study_data) -> RoBResult`
* :meth:`to_table(results) -> pandas.DataFrame`
* :meth:`to_figure(results) -> matplotlib.figure.Figure`

A :class:`RoBFigureGenerator` provides standard RoB visualisations
(traffic-light heatmap, summary bar chart) used by the Cochrane
Collaboration's review software.

All figures use ``constrained_layout=True`` and the project-wide
matplotlib font fallback ``['Noto Sans SC', 'DejaVu Sans']`` with
``axes.unicode_minus = False``. Heavy deps (matplotlib, pandas, numpy)
are imported lazily inside the methods that need them.
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
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Matplotlib font setup (lazy, idempotent)
# ---------------------------------------------------------------------------

_MPL_INITIALISED = False
_FONT_SANS_SERIF = ["Noto Sans SC", "DejaVu Sans"]


def _init_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (idempotent)."""
    global _MPL_INITIALISED
    if _MPL_INITIALISED:
        return
    try:
        import matplotlib  # noqa: WPS433
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # noqa: WPS433
        plt.rcParams["font.sans-serif"] = _FONT_SANS_SERIF
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["figure.dpi"] = 120
        plt.rcParams["savefig.dpi"] = 120
        _MPL_INITIALISED = True
    except Exception as exc:  # pragma: no cover
        logger.warning("matplotlib init failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Judgement enums
# ---------------------------------------------------------------------------

class Rob2Judgment(Enum):
    """Cochrane RoB 2 per-domain judgement."""

    LOW = "low"
    SOME_CONCERNS = "some_concerns"
    HIGH = "high"
    VERY_HIGH = "very_high"

    @classmethod
    def from_value(cls, value: Union[str, "Rob2Judgment"]) -> "Rob2Judgment":
        if isinstance(value, cls):
            return value
        v = str(value).strip().lower()
        for m in cls:
            if m.value == v or m.name.lower() == v:
                return m
        raise ValueError(f"Unknown Rob2Judgment: {value!r}")


class RobinsIJudgment(Enum):
    """ROBINS-I per-domain judgement."""

    LOW = "low"
    MODERATE = "moderate"
    SERIOUS = "serious"
    CRITICAL = "critical"
    NO_INFORMATION = "no_information"

    @classmethod
    def from_value(cls, value: Union[str, "RobinsIJudgment"]) -> "RobinsIJudgment":
        if isinstance(value, cls):
            return value
        v = str(value).strip().lower()
        for m in cls:
            if m.value == v or m.name.lower() == v:
                return m
        raise ValueError(f"Unknown RobinsIJudgment: {value!r}")


class Quadas2Judgment(Enum):
    """QUADAS-2 risk-of-bias OR applicability judgement."""

    LOW = "low"
    HIGH = "high"
    UNCLEAR = "unclear"

    @classmethod
    def from_value(cls, value: Union[str, "Quadas2Judgment"]) -> "Quadas2Judgment":
        if isinstance(value, cls):
            return value
        v = str(value).strip().lower()
        for m in cls:
            if m.value == v or m.name.lower() == v:
                return m
        raise ValueError(f"Unknown Quadas2Judgment: {value!r}")


# ---------------------------------------------------------------------------
# RoBResult
# ---------------------------------------------------------------------------

@dataclass
class RoBResult:
    """Outcome of a single risk-of-bias assessment.

    Attributes:
        study_id: Identifier of the assessed study.
        study_title: Optional human-readable title.
        tool_name: Name of the tool that produced this result
            (e.g. ``'CochraneRoB2'``).
        domains: Mapping of domain code -> domain result dict. Each
            domain dict is tool-specific but typically contains
            ``judgment``, ``support`` and ``responses`` keys.
        overall_judgment: The tool-specific overall judgement (string
            or :class:`Enum` member).
        support_text: Free-text summary justification.
    """

    study_id: str = ""
    study_title: str = ""
    tool_name: str = ""
    domains: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    overall_judgment: Any = ""
    support_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this result."""
        ov = self.overall_judgment
        if isinstance(ov, Enum):
            ov = ov.value
        return {
            "study_id": self.study_id,
            "study_title": self.study_title,
            "tool_name": self.tool_name,
            "domains": self._serialise_domains(),
            "overall_judgment": ov,
            "support_text": self.support_text,
        }

    def _serialise_domains(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in self.domains.items():
            if not isinstance(v, dict):
                out[k] = v
                continue
            d = dict(v)
            if isinstance(d.get("judgment"), Enum):
                d["judgment"] = d["judgment"].value
            out[k] = d
        return out

    def to_markdown(self) -> str:
        """Return a Markdown rendering of this result."""
        lines: List[str] = []
        title = self.study_title or self.study_id or "(untitled study)"
        lines.append(f"## RoB Assessment — {title}")
        lines.append(f"**Tool:** {self.tool_name}")
        ov = self.overall_judgment
        if isinstance(ov, Enum):
            ov = ov.value
        lines.append(f"**Overall judgment:** {ov}")
        lines.append("")
        lines.append("### Domain judgments")
        for code, dom in self.domains.items():
            if not isinstance(dom, dict):
                lines.append(f"- **{code}**: {dom}")
                continue
            j = dom.get("judgment")
            if isinstance(j, Enum):
                j = j.value
            supp = dom.get("support", "")
            lines.append(f"- **{code}** — judgment: `{j}`")
            if supp:
                lines.append(f"  - support: {supp}")
            resp = dom.get("responses")
            if isinstance(resp, dict) and resp:
                for q, a in resp.items():
                    av = a if isinstance(a, str) else str(a)
                    lines.append(f"  - {q}: {av}")
        if self.support_text:
            lines.append("")
            lines.append(f"**Support:** {self.support_text}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# RiskOfBiasTool ABC
# ---------------------------------------------------------------------------

class RiskOfBiasTool(ABC):
    """Abstract base class for all risk-of-bias assessment tools.

    Subclasses MUST set :attr:`TOOL_NAME` and implement :meth:`assess`.
    """

    #: Short, stable identifier of the tool.
    TOOL_NAME: str = "abstract"

    #: Display name (used as chart title).
    DISPLAY_NAME: str = "Risk of Bias Tool"

    #: Ordered list of domain codes (subclasses override).
    DOMAIN_CODES: Tuple[str, ...] = ()

    @abstractmethod
    def assess(self, study_data: Dict[str, Any]) -> RoBResult:
        """Assess a single study and return a :class:`RoBResult`.

        Args:
            study_data: Tool-specific input dict. At minimum should
                contain ``study_id`` and ``study_title``; per-domain
                judgments are typically provided under a ``domains``
                key.

        Returns:
            A populated :class:`RoBResult`.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    def to_table(self, results: List[RoBResult]):
        """Return a long-form :class:`pandas.DataFrame` of results.

        Columns: ``study_id``, ``study_title``, ``domain``, ``judgment``,
        ``support``.
        """
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pandas is required for to_table()") from exc
        rows: List[Dict[str, Any]] = []
        for r in results:
            for code, dom in r.domains.items():
                if not isinstance(dom, dict):
                    dom = {"judgment": dom}
                j = dom.get("judgment")
                if isinstance(j, Enum):
                    j = j.value
                rows.append({
                    "study_id": r.study_id,
                    "study_title": r.study_title,
                    "domain": code,
                    "judgment": j,
                    "support": dom.get("support", ""),
                })
        df = pd.DataFrame(rows, columns=["study_id", "study_title", "domain",
                                         "judgment", "support"])
        return df

    def to_figure(self, results: List[RoBResult]):
        """Return a default RoB figure (defaults to traffic-light)."""
        return RoBFigureGenerator().traffic_light(results)

    # ------------------------------------------------------------------
    # Helpers shared by concrete tools
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_domains(
        study_data: Dict[str, Any], default_codes: Sequence[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Normalise the ``domains`` field of ``study_data``.

        Accepts either a dict-of-dicts (preferred) or a list of dicts
        with ``code`` keys.
        """
        raw = study_data.get("domains", {}) or {}
        out: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict):
                    out[k] = dict(v)
                else:
                    out[k] = {"judgment": v}
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                code = item.get("code") or item.get("domain")
                if code:
                    out[code] = {
                        k: v for k, v in item.items()
                        if k not in {"code", "domain"}
                    }
        # fill defaults
        for code in default_codes:
            out.setdefault(code, {"judgment": None})
        return out


# ---------------------------------------------------------------------------
# Cochrane Risk of Bias 2 (RCTs)
# ---------------------------------------------------------------------------

class CochraneRoB2(RiskOfBiasTool):
    """Cochrane Risk of Bias 2 — for randomised trials.

    Five domains:

    * D1 — Randomization process
    * D2 — Deviations from the intended interventions
    * D3 — Missing outcome data
    * D4 — Measurement of the outcome
    * D5 — Selection of the reported result

    Overall risk is algorithmic from the per-domain judgments.
    """

    TOOL_NAME = "CochraneRoB2"
    DISPLAY_NAME = "Cochrane Risk of Bias 2"
    DOMAIN_CODES = ("D1", "D2", "D3", "D4", "D5")

    DOMAIN_LABELS: Dict[str, str] = {
        "D1": "Randomization process",
        "D2": "Deviations from intended interventions",
        "D3": "Missing outcome data",
        "D4": "Measurement of the outcome",
        "D5": "Selection of the reported result",
    }

    def assess(self, study_data: Dict[str, Any]) -> RoBResult:
        """Assess a single RCT and return a :class:`RoBResult`.

        The ``study_data['domains']`` dict should map each domain code
        (``'D1'`` ... ``'D5'``) to a dict with ``judgment`` (one of
        ``low`` / ``some_concerns`` / ``high`` / ``very_high``),
        optional ``support`` (free text), and optional ``responses``
        (signalling-question answers).
        """
        sid = study_data.get("study_id", "")
        stitle = study_data.get("study_title", "")
        domains = self._coerce_domains(study_data, self.DOMAIN_CODES)
        # normalise judgments
        judgments: List[Rob2Judgment] = []
        for code in self.DOMAIN_CODES:
            d = domains[code]
            j = d.get("judgment")
            if j is None:
                # default to some_concerns when unspecified
                d["judgment"] = Rob2Judgment.SOME_CONCERNS
                j = d["judgment"]
            elif not isinstance(j, Rob2Judgment):
                j = Rob2Judgment.from_value(j)
                d["judgment"] = j
            judgments.append(j)
        overall = self._overall(judgments)
        support = study_data.get("support_text", "") or self._default_support(
            judgments, overall
        )
        return RoBResult(
            study_id=sid,
            study_title=stitle,
            tool_name=self.TOOL_NAME,
            domains=domains,
            overall_judgment=overall,
            support_text=support,
        )

    @staticmethod
    def _overall(judgments: List[Rob2Judgment]) -> Rob2Judgment:
        """Compute the overall RoB 2 judgement from domain judgements.

        Algorithm (per Cochrane RoB 2 guidance, simplified):

        * Low overall: ALL domains low.
        * Some concerns: at least one domain some_concerns AND none high.
        * High overall: at least one domain high (but not all five high).
        * Very high: ALL five domains high.
        """
        n_low = sum(1 for j in judgments if j == Rob2Judgment.LOW)
        n_some = sum(1 for j in judgments if j == Rob2Judgment.SOME_CONCERNS)
        n_high = sum(1 for j in judgments if j == Rob2Judgment.HIGH)
        n_veryhigh = sum(1 for j in judgments if j == Rob2Judgment.VERY_HIGH)
        n = len(judgments)
        if n == 0:
            return Rob2Judgment.SOME_CONCERNS
        if n_low == n:
            return Rob2Judgment.LOW
        if n_high == 0 and n_veryhigh == 0:
            return Rob2Judgment.SOME_CONCERNS
        if (n_high + n_veryhigh) == n and n_veryhigh >= 1:
            return Rob2Judgment.VERY_HIGH
        return Rob2Judgment.HIGH

    @staticmethod
    def _default_support(judgments: List[Rob2Judgment], overall: Rob2Judgment) -> str:
        """Return a default support string from domain judgments."""
        return (
            f"Overall risk: {overall.value} "
            f"(low={sum(1 for j in judgments if j == Rob2Judgment.LOW)}, "
            f"some_concerns={sum(1 for j in judgments if j == Rob2Judgment.SOME_CONCERNS)}, "
            f"high={sum(1 for j in judgments if j == Rob2Judgment.HIGH)}, "
            f"very_high={sum(1 for j in judgments if j == Rob2Judgment.VERY_HIGH)})"
        )


# ---------------------------------------------------------------------------
# ROBINS-I (non-randomised)
# ---------------------------------------------------------------------------

class ROBINS_I(RiskOfBiasTool):
    """ROBINS-I — for non-randomised studies of interventions.

    Seven domains:

    * D1 — Confounding
    * D2 — Selection of participants
    * D3 — Classification of interventions
    * D4 — Deviations from intended interventions
    * D5 — Missing data
    * D6 — Measurement of outcomes
    * D7 — Selection of the reported result

    Overall risk is the worst (highest-severity) of D1-D3 + D4-D6 + D7,
    matching the ROBINS-I guidance.
    """

    TOOL_NAME = "ROBINS_I"
    DISPLAY_NAME = "ROBINS-I"
    DOMAIN_CODES = ("D1", "D2", "D3", "D4", "D5", "D6", "D7")

    DOMAIN_LABELS: Dict[str, str] = {
        "D1": "Confounding",
        "D2": "Selection of participants",
        "D3": "Classification of interventions",
        "D4": "Deviations from intended interventions",
        "D5": "Missing data",
        "D6": "Measurement of outcomes",
        "D7": "Selection of the reported result",
    }

    _SEVERITY_ORDER: List[RobinsIJudgment] = [
        RobinsIJudgment.LOW,
        RobinsIJudgment.MODERATE,
        RobinsIJudgment.SERIOUS,
        RobinsIJudgment.CRITICAL,
        RobinsIJudgment.NO_INFORMATION,
    ]

    def assess(self, study_data: Dict[str, Any]) -> RoBResult:
        """Assess a single non-randomised study."""
        sid = study_data.get("study_id", "")
        stitle = study_data.get("study_title", "")
        domains = self._coerce_domains(study_data, self.DOMAIN_CODES)
        judgments: List[RobinsIJudgment] = []
        for code in self.DOMAIN_CODES:
            d = domains[code]
            j = d.get("judgment")
            if j is None:
                d["judgment"] = RobinsIJudgment.NO_INFORMATION
                j = d["judgment"]
            elif not isinstance(j, RobinsIJudgment):
                j = RobinsIJudgment.from_value(j)
                d["judgment"] = j
            judgments.append(j)
        overall = self._overall(judgments)
        support = study_data.get("support_text", "") or (
            f"Overall risk: {overall.value} (worst of D1-D7)"
        )
        return RoBResult(
            study_id=sid,
            study_title=stitle,
            tool_name=self.TOOL_NAME,
            domains=domains,
            overall_judgment=overall,
            support_text=support,
        )

    def _overall(self, judgments: List[RobinsIJudgment]) -> RobinsIJudgment:
        """Overall ROBINS-I judgement = worst of pre-intervention (D1-D3),
        at-intervention (D4-D6), and post-intervention (D7) domains.

        Following the ROBINS-I guidance: the overall judgement is the
        worst (highest-severity) domain judgement that is not
        ``NO_INFORMATION``. If all domains are ``NO_INFORMATION``, the
        overall is ``NO_INFORMATION``.
        """
        sev_index = {j: i for i, j in enumerate(self._SEVERITY_ORDER)}
        worst = RobinsIJudgment.LOW
        worst_idx = 0
        all_no_info = True
        for j in judgments:
            if j != RobinsIJudgment.NO_INFORMATION:
                all_no_info = False
                if sev_index[j] > worst_idx:
                    worst_idx = sev_index[j]
                    worst = j
        if all_no_info:
            return RobinsIJudgment.NO_INFORMATION
        return worst


# ---------------------------------------------------------------------------
# QUADAS-2 (diagnostic accuracy)
# ---------------------------------------------------------------------------

class QUADAS2(RiskOfBiasTool):
    """QUADAS-2 — for diagnostic accuracy studies.

    Four domains, each with a *risk of bias* AND an *applicability*
    judgement:

    * Patient selection
    * Index test
    * Reference standard
    * Flow and timing

    (Flow and timing has no applicability concern in QUADAS-2 — we
    store ``applicability='N/A'`` for that domain.)
    """

    TOOL_NAME = "QUADAS2"
    DISPLAY_NAME = "QUADAS-2"
    DOMAIN_CODES = ("D1", "D2", "D3", "D4")

    DOMAIN_LABELS: Dict[str, str] = {
        "D1": "Patient selection",
        "D2": "Index test",
        "D3": "Reference standard",
        "D4": "Flow and timing",
    }

    def assess(self, study_data: Dict[str, Any]) -> RoBResult:
        """Assess a single diagnostic-accuracy study."""
        sid = study_data.get("study_id", "")
        stitle = study_data.get("study_title", "")
        domains = self._coerce_domains(study_data, self.DOMAIN_CODES)
        risk_judgments: List[Quadas2Judgment] = []
        for code in self.DOMAIN_CODES:
            d = domains[code]
            rob = d.get("risk_of_bias") or d.get("judgment")
            if rob is None:
                rob = Quadas2Judgment.UNCLEAR
            elif not isinstance(rob, Quadas2Judgment):
                rob = Quadas2Judgment.from_value(rob)
            d["risk_of_bias"] = rob
            # applicability — N/A for Flow & timing
            if code == "D4":
                d["applicability"] = "N/A"
            else:
                appl = d.get("applicability")
                if appl is None:
                    appl = Quadas2Judgment.UNCLEAR
                elif not isinstance(appl, Quadas2Judgment):
                    appl = Quadas2Judgment.from_value(appl)
                d["applicability"] = appl
            # keep judgment alias for to_table
            d["judgment"] = rob
            risk_judgments.append(rob)
        overall = self._overall(risk_judgments)
        support = study_data.get("support_text", "") or (
            f"Overall risk of bias: {overall.value} (worst of D1-D4)"
        )
        return RoBResult(
            study_id=sid,
            study_title=stitle,
            tool_name=self.TOOL_NAME,
            domains=domains,
            overall_judgment=overall,
            support_text=support,
        )

    @staticmethod
    def _overall(judgments: List[Quadas2Judgment]) -> Quadas2Judgment:
        """Overall = worst (highest-severity) of the four domain RoB."""
        if any(j == Quadas2Judgment.HIGH for j in judgments):
            return Quadas2Judgment.HIGH
        if any(j == Quadas2Judgment.UNCLEAR for j in judgments):
            return Quadas2Judgment.UNCLEAR
        return Quadas2Judgment.LOW


# ---------------------------------------------------------------------------
# Newcastle-Ottawa Scale (cohort & case-control)
# ---------------------------------------------------------------------------

class NewcastleOttawaScale(RiskOfBiasTool):
    """Newcastle-Ottawa Scale — for cohort & case-control studies.

    Eight items grouped into three categories (Selection, Comparability,
    Outcome/Exposure). Each item is worth 1 star (Comparability worth
    up to 2); total maximum = 9 stars. Studies with >=7 stars are
    considered high quality.
    """

    TOOL_NAME = "NewcastleOttawaScale"
    DISPLAY_NAME = "Newcastle-Ottawa Scale"
    #: 8 item codes (S1-S4 selection, C1-C2 comparability, O1-O3 outcome)
    DOMAIN_CODES = (
        "S1", "S2", "S3", "S4",  # selection (1 star each, max 4)
        "C1",  # comparability (up to 2 stars)
        "O1", "O2", "O3",  # outcome (1 star each, max 3)
    )

    #: Max stars per item
    MAX_STARS_PER_ITEM: Dict[str, int] = {
        "S1": 1, "S2": 1, "S3": 1, "S4": 1,
        "C1": 2,
        "O1": 1, "O2": 1, "O3": 1,
    }

    DOMAIN_LABELS: Dict[str, str] = {
        "S1": "Representativeness of the exposed cohort",
        "S2": "Selection of the non-exposed cohort",
        "S3": "Ascertainment of exposure",
        "S4": "Outcome not present at start",
        "C1": "Comparability of cohorts (design / analysis)",
        "O1": "Assessment of outcome",
        "O2": "Follow-up long enough",
        "O3": "Adequacy of follow-up",
    }

    #: Quality band thresholds (by total stars).
    HIGH_QUALITY_THRESHOLD = 7

    def assess(self, study_data: Dict[str, Any]) -> RoBResult:
        """Assess a single cohort / case-control study."""
        sid = study_data.get("study_id", "")
        stitle = study_data.get("study_title", "")
        domains = self._coerce_domains(study_data, self.DOMAIN_CODES)
        total_stars = 0
        for code in self.DOMAIN_CODES:
            d = domains[code]
            stars = d.get("stars")
            if stars is None:
                # allow ``awarded`` alias
                stars = d.get("awarded", 0)
            try:
                stars = int(stars)
            except (TypeError, ValueError):
                stars = 0
            stars = max(0, min(stars, self.MAX_STARS_PER_ITEM[code]))
            d["stars"] = stars
            d["judgment"] = stars  # alias for table
            total_stars += stars
        # NOS doesn't use a categorical judgment, but we map to a
        # simple band so the rest of the framework stays consistent.
        if total_stars >= self.HIGH_QUALITY_THRESHOLD:
            overall_str = "high_quality"
        elif total_stars >= 5:
            overall_str = "moderate_quality"
        else:
            overall_str = "low_quality"
        support = study_data.get("support_text", "") or (
            f"Newcastle-Ottawa total stars: {total_stars}/9 ({overall_str})"
        )
        return RoBResult(
            study_id=sid,
            study_title=stitle,
            tool_name=self.TOOL_NAME,
            domains=domains,
            overall_judgment=overall_str,
            support_text=support,
        )

    @property
    def total_max_stars(self) -> int:
        """Return the maximum possible star count (9)."""
        return sum(self.MAX_STARS_PER_ITEM.values())


# ---------------------------------------------------------------------------
# RoB Figure generator
# ---------------------------------------------------------------------------

class RoBFigureGenerator:
    """Standard RoB visualisations.

    All methods return ``matplotlib.figure.Figure`` objects created
    with ``constrained_layout=True`` and the project font fallback.
    """

    #: Colour map per RoB-2 judgment.
    ROB2_COLORS: Dict[str, str] = {
        "low": "#66c2a5",
        "some_concerns": "#fee08b",
        "high": "#f46d43",
        "very_high": "#a50026",
    }

    ROBINS_I_COLORS: Dict[str, str] = {
        "low": "#66c2a5",
        "moderate": "#fee08b",
        "serious": "#f46d43",
        "critical": "#a50026",
        "no_information": "#bababa",
    }

    QUADAS2_COLORS: Dict[str, str] = {
        "low": "#66c2a5",
        "high": "#f46d43",
        "unclear": "#bababa",
    }

    NOS_COLORS: Dict[str, str] = {
        "high_quality": "#66c2a5",
        "moderate_quality": "#fee08b",
        "low_quality": "#f46d43",
    }

    # ------------------------------------------------------------------
    # Traffic-light (domain x study heatmap)
    # ------------------------------------------------------------------

    def traffic_light(self, results: List[RoBResult]):
        """Build a domain x study traffic-light heatmap.

        Auto-detects the tool by ``results[0].tool_name`` and routes
        to the appropriate colour map.
        """
        return self._traffic_light_generic(results)

    def robins_i_traffic_light(self, results: List[RoBResult]):
        """Build a ROBINS-I specific traffic-light."""
        return self._traffic_light_generic(results, color_map=self.ROBINS_I_COLORS)

    def quadas2_traffic_light(self, results: List[RoBResult]):
        """Build a QUADAS-2 specific traffic-light."""
        return self._traffic_light_generic(results, color_map=self.QUADAS2_COLORS)

    def _traffic_light_generic(
        self,
        results: List[RoBResult],
        color_map: Optional[Dict[str, str]] = None,
    ):
        """Implementation of the traffic-light heatmap."""
        if not results:
            return self._empty_figure("No RoB results to display")
        _init_matplotlib()
        import matplotlib.pyplot as plt
        import numpy as np

        tool_name = results[0].tool_name
        if color_map is None:
            if tool_name == "CochraneRoB2":
                color_map = self.ROB2_COLORS
            elif tool_name == "ROBINS_I":
                color_map = self.ROBINS_I_COLORS
            elif tool_name == "QUADAS2":
                color_map = self.QUADAS2_COLORS
            elif tool_name == "NewcastleOttawaScale":
                color_map = self.NOS_COLORS
            else:
                color_map = self.ROB2_COLORS

        # discover domain codes from the first result (ordered)
        domain_codes = list(results[0].domains.keys()) or list(
            _TOOL_DOMAINS.get(tool_name, [])
        )
        studies = [r.study_id or r.study_title or f"study_{i+1}"
                   for i, r in enumerate(results)]

        n_studies = len(studies)
        n_domains = len(domain_codes)
        # The chart convention: rows = domains (+ Overall), cols = studies.
        # i indexes the Y axis (domain row), j indexes the X axis (study col).
        # Build a matrix grid[i][j] = (color, short_label)
        n_rows = n_domains + 1  # +1 for the Overall row
        n_cols = n_studies
        grid: List[List[Any]] = [[("", "?") for _ in range(n_cols)]
                                  for _ in range(n_rows)]
        for j, r in enumerate(results):
            for i, code in enumerate(domain_codes):
                dom = r.domains.get(code, {})
                if not isinstance(dom, dict):
                    dom = {"judgment": dom}
                if tool_name == "NewcastleOttawaScale":
                    ov = r.overall_judgment
                    if isinstance(ov, Enum):
                        ov = ov.value
                    color = color_map.get(str(ov), "#cccccc")
                    label = (str(ov)[:1].upper()
                             if isinstance(ov, str) and ov else "?")
                else:
                    jval = dom.get("judgment")
                    if isinstance(jval, Enum):
                        jval = jval.value
                    color = color_map.get(str(jval), "#cccccc")
                    label = (str(jval)[:1].upper()
                             if isinstance(jval, str) and jval else "?")
                grid[i][j] = (color, label)
            # Overall row (last row)
            ov = r.overall_judgment
            if isinstance(ov, Enum):
                ov = ov.value
            color = color_map.get(str(ov), "#cccccc")
            label = (str(ov)[:1].upper()
                     if isinstance(ov, str) and ov else "?")
            grid[n_domains][j] = (color, label)
        row_labels = list(domain_codes) + ["Overall"]

        # figure
        fig_width = max(6.0, 0.7 * n_cols + 2.5)
        fig_height = max(3.5, 0.5 * n_rows + 1.5)
        fig, ax = plt.subplots(
            figsize=(fig_width, fig_height), constrained_layout=True
        )
        ax.set_xlim(-0.5, n_cols - 0.5)
        ax.set_ylim(-0.5, n_rows - 0.5)
        ax.invert_yaxis()
        for i in range(n_rows):
            for j in range(n_cols):
                color, label = grid[i][j]
                ax.add_patch(plt.Rectangle(
                    (j - 0.5, i - 0.5), 1, 1,
                    facecolor=color, edgecolor="white", linewidth=1.0
                ))
                ax.text(j, i, label, ha="center", va="center", fontsize=8)
        ax.set_xticks(range(n_cols))
        ax.set_xticklabels(studies, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(n_rows))
        ax.set_yticklabels(row_labels, fontsize=9)
        ax.set_title(f"{tool_name} — Traffic-light plot", fontsize=11)
        # legend
        self._draw_color_legend(ax, color_map)
        # remove spines
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(length=0)
        return fig

    # ------------------------------------------------------------------
    # Summary bar chart
    # ------------------------------------------------------------------

    def summary_bar(self, results: List[RoBResult]):
        """Build a stacked bar chart of judgment proportions per domain.

        Returns a :class:`matplotlib.figure.Figure`.
        """
        if not results:
            return self._empty_figure("No RoB results to display")
        _init_matplotlib()
        import matplotlib.pyplot as plt
        import numpy as np

        tool_name = results[0].tool_name
        if tool_name == "CochraneRoB2":
            color_map = self.ROB2_COLORS
            order = ["low", "some_concerns", "high", "very_high"]
        elif tool_name == "ROBINS_I":
            color_map = self.ROBINS_I_COLORS
            order = ["low", "moderate", "serious", "critical", "no_information"]
        elif tool_name == "QUADAS2":
            color_map = self.QUADAS2_COLORS
            order = ["low", "unclear", "high"]
        elif tool_name == "NewcastleOttawaScale":
            color_map = self.NOS_COLORS
            order = ["high_quality", "moderate_quality", "low_quality"]
        else:
            color_map = self.ROB2_COLORS
            order = list(color_map.keys())

        domain_codes = list(results[0].domains.keys()) or list(
            _TOOL_DOMAINS.get(tool_name, [])
        )
        n_studies = len(results)

        # count per (domain, judgment)
        counts = {code: {j: 0 for j in order} for code in domain_codes}
        for r in results:
            for code in domain_codes:
                dom = r.domains.get(code, {})
                if not isinstance(dom, dict):
                    dom = {"judgment": dom}
                if tool_name == "NewcastleOttawaScale":
                    j = r.overall_judgment
                else:
                    j = dom.get("judgment")
                if isinstance(j, Enum):
                    j = j.value
                j = str(j) if j is not None else "no_information"
                if j in counts[code]:
                    counts[code][j] += 1
                else:
                    # tolerate unknown judgment codes
                    counts[code].setdefault(j, 0)
                    counts[code][j] += 1
                    if j not in order:
                        order = order + [j]

        x_pos = np.arange(len(domain_codes))
        fig_width = max(7.0, 0.9 * len(domain_codes) + 2.5)
        fig, ax = plt.subplots(figsize=(fig_width, 5.0), constrained_layout=True)
        bottom = np.zeros(len(domain_codes))
        for j in order:
            heights = np.array([counts[c].get(j, 0) for c in domain_codes],
                               dtype=float)
            if heights.sum() == 0:
                continue
            pct = heights / max(n_studies, 1) * 100.0
            ax.bar(
                x_pos, pct, bottom=bottom, label=j,
                color=color_map.get(j, "#cccccc"), edgecolor="white",
                linewidth=0.5,
            )
            bottom = bottom + pct

        ax.set_xticks(x_pos)
        ax.set_xticklabels(domain_codes, fontsize=9)
        ax.set_ylabel("% of studies", fontsize=9)
        ax.set_title(f"{tool_name} — Summary (% per domain)", fontsize=11)
        ax.set_ylim(0, 100)
        ax.legend(
            loc="upper center", bbox_to_anchor=(0.5, -0.12),
            ncol=min(len(order), 5), fontsize=8, frameon=False,
        )
        return fig

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _draw_color_legend(self, ax, color_map: Dict[str, str]) -> None:
        """Draw a small color legend above the axes."""
        import matplotlib.pyplot as plt
        labels = list(color_map.keys())
        for i, (label, color) in enumerate(color_map.items()):
            ax.text(
                1.02, 0.95 - i * 0.06, label,
                transform=ax.transAxes, fontsize=7,
                color=color, fontweight="bold",
            )

    def _empty_figure(self, message: str):
        """Return a single-panel figure with a centred message."""
        _init_matplotlib()
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 3), constrained_layout=True)
        ax.text(0.5, 0.5, message, ha="center", va="center",
                transform=ax.transAxes, fontsize=10, color="#555555")
        ax.set_axis_off()
        return fig


_TOOL_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "CochraneRoB2": CochraneRoB2.DOMAIN_CODES,
    "ROBINS_I": ROBINS_I.DOMAIN_CODES,
    "QUADAS2": QUADAS2.DOMAIN_CODES,
    "NewcastleOttawaScale": NewcastleOttawaScale.DOMAIN_CODES,
}
