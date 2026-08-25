"""Publication reporting checklists aligned with the EQUATOR Network.

The EQUATOR Network (https://www.equator-network.org) is the canonical
registry of reporting guidelines for health research. This module
provides:

* :class:`ReportingChecklist` — top-level dispatcher:
  :meth:`equator_network_lookup` returns the canonical EQUATOR URL for a
  given study design; :meth:`get` returns the list of
  :class:`ChecklistItem` for a named checklist; :meth:`to_markdown` and
  :meth:`to_pdf` render items to text or PDF.
* :class:`EquatorChecklists` — classmethods returning
  ``List[ChecklistItem]`` for each of CONSORT, STROBE, PRISMA, STARD,
  TRIPOD, SPIRIT, SQUIRE, CHEERS, TREND, COREQ.

This is the *reporting-checklist* companion to
:mod:`research_lifecycle.quality_assessment`, which focuses on
*methodological quality / RoB*. Both are needed for a publication-ready
project: quality assessment is internal to the review process, while
reporting checklists are submitted alongside the manuscript.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------
@dataclass
class ChecklistItem:
    """A single reporting-checklist item.

    Attributes:
        id: Item identifier (e.g. ``"consort_1_title"``).
        section: Section the item belongs to (e.g. ``"Title"``,
            ``"Methods"``).
        description: Short human-readable description.
        location_in_report: Optional location string filled by the
            author (e.g. ``"p. 3, ¶2"``).
        reported: Whether the item has been reported (default False).
    """

    id: str
    section: str
    description: str
    location_in_report: str = ""
    reported: bool = False


# ---------------------------------------------------------------------------
# EQUATOR Network URLs
# ---------------------------------------------------------------------------
# Each URL points to the canonical EQUATOR Network reporting-guideline
# page. These are stable long-term URLs that authors can cite from their
# protocol and manuscript.
EQUATOR_URLS: Dict[str, str] = {
    "consort": "https://www.equator-network.org/reporting-guidelines/consort/",
    "strobe": "https://www.equator-network.org/reporting-guidelines/strobe/",
    "prisma": "https://www.equator-network.org/reporting-guidelines/prisma/",
    "stard": "https://www.equator-network.org/reporting-guidelines/stard/",
    "tripod": "https://www.equator-network.org/reporting-guidelines/tripod-statement/",
    "spirit": "https://www.equator-network.org/reporting-guidelines/spirit-2013-statement-defining-standard-protocol-items-for-clinical-trials/",
    "squire": "https://www.equator-network.org/reporting-guidelines/squire/",
    "cheers": "https://www.equator-network.org/reporting-guidelines/cheers/",
    "trend": "https://www.equator-network.org/reporting-guidelines/trend-statement/",
    "coreq": "https://www.equator-network.org/reporting-guidelines/coreq/",
}


# ---------------------------------------------------------------------------
# EquatorChecklists
# ---------------------------------------------------------------------------
class EquatorChecklists:
    """Factory of EQUATOR-aligned reporting checklists.

    Each classmethod returns a :class:`List[ChecklistItem]`.
    """

    # ------------------------------------------------------------------
    # CONSORT — RCTs
    # ------------------------------------------------------------------
    @staticmethod
    def consort() -> List[ChecklistItem]:
        """Return the 25-item CONSORT 2010 checklist."""
        items = [
            ("Title and abstract", "1a", "Title identifies the study as an RCT"),
            ("Title and abstract", "1b", "Structured abstract per journal style"),
            ("Introduction", "2a", "Scientific background and rationale"),
            ("Introduction", "2b", "Specific objectives or hypotheses"),
            ("Methods", "3", "Trial design"),
            ("Methods", "4a", "Eligibility criteria"),
            ("Methods", "4b", "Settings and locations"),
            ("Methods", "5", "Interventions with sufficient detail for replication"),
            ("Methods", "6a", "Completely defined pre-specified primary and secondary outcomes"),
            ("Methods", "6b", "Any post-hoc outcome changes"),
            ("Methods", "7a", "How sample size was determined"),
            ("Methods", "7b", "Interim analyses and stopping guidelines"),
            ("Methods", "8a", "Method of random sequence generation"),
            ("Methods", "8b", "Type of randomisation"),
            ("Methods", "9", "Mechanism of allocation concealment"),
            ("Methods", "10", "Who generated/enrolled/assigned"),
            ("Methods", "11a", "Blinding of participants and personnel"),
            ("Methods", "11b", "Blinding of outcome assessors"),
            ("Methods", "12a", "Statistical methods for primary outcomes"),
            ("Methods", "12b", "Methods for additional analyses"),
            ("Results", "13a", "Flow diagram of participant flow"),
            ("Results", "13b", "Losses and exclusions after randomisation"),
            ("Results", "14a", "Recruitment dates"),
            ("Results", "14b", "Why trial ended or was stopped"),
            ("Results", "15", "Baseline table of clinical characteristics"),
        ]
        return [
            ChecklistItem(
                id=f"consort_{code}", section=section,
                description=desc,
            )
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # STROBE — observational
    # ------------------------------------------------------------------
    @staticmethod
    def strobe() -> List[ChecklistItem]:
        """Return the 22-item STROBE checklist."""
        items = [
            ("Title and abstract", "1", "Indicate study design in title/abstract"),
            ("Introduction", "2", "Background / rationale"),
            ("Introduction", "3", "Objectives / hypotheses"),
            ("Methods", "4", "Study design"),
            ("Methods", "5", "Setting"),
            ("Methods", "6", "Participants"),
            ("Methods", "7", "Variables"),
            ("Methods", "8", "Data sources / measurement"),
            ("Methods", "9", "Bias"),
            ("Methods", "10", "Study size"),
            ("Methods", "11", "Quantitative variables"),
            ("Methods", "12", "Statistical methods"),
            ("Results", "13", "Participants"),
            ("Results", "14", "Descriptive data"),
            ("Results", "15", "Outcome data"),
            ("Results", "16", "Main results"),
            ("Results", "17", "Other analyses"),
            ("Discussion", "18", "Key results"),
            ("Discussion", "19", "Limitations"),
            ("Discussion", "20", "Interpretation"),
            ("Discussion", "21", "Generalisability"),
            ("Other", "22", "Funding"),
        ]
        return [
            ChecklistItem(id=f"strobe_{code}", section=section, description=desc)
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # PRISMA — systematic reviews
    # ------------------------------------------------------------------
    @staticmethod
    def prisma() -> List[ChecklistItem]:
        """Return the 27-item PRISMA 2020 checklist."""
        items = [
            ("Title", "1", "Identify as systematic review"),
            ("Abstract", "2", "Structured abstract per PRISMA abstract"),
            ("Introduction", "3", "Rationale in context of existing knowledge"),
            ("Introduction", "4", "Objectives using PICO(S)"),
            ("Methods", "5", "Eligibility criteria"),
            ("Methods", "6", "Information sources including dates"),
            ("Methods", "7", "Full search strategies"),
            ("Methods", "8", "Selection process"),
            ("Methods", "9", "Data collection process"),
            ("Methods", "10", "Data items"),
            ("Methods", "11", "Risk of bias methods per study design"),
            ("Methods", "12", "Effect measures"),
            ("Methods", "13", "Synthesis preparation"),
            ("Methods", "14", "Synthesis methods"),
            ("Methods", "15", "Heterogeneity assessment"),
            ("Methods", "16", "Reporting bias assessment"),
            ("Methods", "17", "Certainty assessment"),
            ("Results", "18", "Study selection results + flow diagram"),
            ("Results", "19", "Study characteristics"),
            ("Results", "20", "Risk-of-bias results"),
            ("Results", "21", "Individual study results"),
            ("Results", "22", "Synthesis results"),
            ("Results", "23", "Reporting-bias results"),
            ("Results", "24", "Certainty of evidence"),
            ("Discussion", "25", "Interpretation"),
            ("Discussion", "26", "Limitations of evidence and review"),
            ("Other", "27", "Registration, protocol, funding, COI"),
        ]
        return [
            ChecklistItem(id=f"prisma_{code}", section=section, description=desc)
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # STARD — diagnostic accuracy
    # ------------------------------------------------------------------
    @staticmethod
    def stard() -> List[ChecklistItem]:
        """Return the 30-item STARD 2015 checklist for diagnostic accuracy studies."""
        items = [
            ("Title", "1", "Identify as diagnostic accuracy study"),
            ("Abstract", "2", "Structured abstract"),
            ("Introduction", "3", "Background and rationale"),
            ("Introduction", "4", "Research questions / hypotheses"),
            ("Methods", "5", "Participants"),
            ("Methods", "6", "Eligibility"),
            ("Methods", "7", "Sample size justification"),
            ("Methods", "8", "Index test(s)"),
            ("Methods", "9", "Reference standard"),
            ("Methods", "10", "Index and reference test blinding"),
            ("Methods", "11", "Test methods"),
            ("Methods", "12", "Analysis"),
            ("Results", "13", "Participant flow"),
            ("Results", "14", "Baseline characteristics"),
            ("Results", "15", "Index test results"),
            ("Results", "16", "Reference standard results"),
            ("Results", "17", "Estimates of diagnostic accuracy"),
            ("Results", "18", "Subgroup / sensitivity analyses"),
            ("Results", "19", "Indeterminate results"),
            ("Results", "20", "Missing results"),
            ("Results", "21", "Adverse events"),
            ("Discussion", "22", "Clinical applicability"),
            ("Discussion", "23", "Limitations"),
            ("Other", "24", "Registration"),
            ("Other", "25", "Protocol availability"),
            ("Other", "26", "Funding"),
            ("Other", "27", "Data sharing"),
            ("Other", "28", "Ethics"),
            ("Other", "29", "Author contributions"),
            ("Other", "30", "Conflict of interest"),
        ]
        return [
            ChecklistItem(id=f"stard_{code}", section=section, description=desc)
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # TRIPOD — prediction models
    # ------------------------------------------------------------------
    @staticmethod
    def tripod() -> List[ChecklistItem]:
        """Return the 22-item TRIPOD checklist for prediction models."""
        items = [
            ("Title and abstract", "1", "Identify as development / validation of prediction model"),
            ("Introduction", "2", "Background and clinical motivation"),
            ("Introduction", "3", "Research objectives and model type"),
            ("Methods", "4a", "Source of data"),
            ("Methods", "4b", "Dates of recruitment and follow-up"),
            ("Methods", "5", "Setting and participants"),
            ("Methods", "6", "Outcome definition"),
            ("Methods", "7", "Predictors definition and measurement"),
            ("Methods", "8", "Sample size and missing data"),
            ("Methods", "9", "Statistical analysis"),
            ("Methods", "10", "Risk groups"),
            ("Methods", "11", "Development vs validation"),
            ("Results", "12", "Participants flow"),
            ("Results", "13", "Baseline characteristics"),
            ("Results", "14", "Model development"),
            ("Results", "15", "Model specification"),
            ("Results", "16", "Performance — discrimination and calibration"),
            ("Results", "17", "Model updating"),
            ("Discussion", "18", "Interpretation"),
            ("Discussion", "19", "Limitations"),
            ("Discussion", "20", "Implications and use"),
            ("Other", "21", "Supplementary info"),
            ("Other", "22", "Funding and COI"),
        ]
        return [
            ChecklistItem(id=f"tripod_{code}", section=section, description=desc)
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # SPIRIT — RCT protocols
    # ------------------------------------------------------------------
    @staticmethod
    def spirit() -> List[ChecklistItem]:
        """Return the 33-item SPIRIT 2013 checklist for RCT protocols."""
        sections_methods = [
            ("Title", "1", "Descriptive title identifying design descriptor"),
            ("Registration", "2a", "Trial identifier and registry name"),
            ("Registration", "2b", "Full protocol access"),
            ("Versions", "3", "Protocol version and amendment history"),
            ("Funding", "4", "Funding sources"),
            ("Roles and responsibilities", "5a", "Sponsor / funder roles"),
            ("Roles and responsibilities", "5b", "Trial steering committee"),
            ("Roles and responsibilities", "5c", "Data management committee"),
            ("Introduction: background", "6a", "Background and rationale"),
            ("Introduction: background", "6b", "Explanation for choice of comparators"),
            ("Objectives", "7", "Specific objectives / hypotheses"),
            ("Trial design", "8", "Trial design including allocation ratio"),
            ("Study setting", "9", "Trial setting"),
            ("Eligibility criteria", "10", "Who is eligible to participate"),
            ("Interventions", "11a", "Intervention descriptions"),
            ("Interventions", "11b", "Criteria for discontinuation"),
            ("Interventions", "11c", "Strategies to improve adherence"),
            ("Interventions", "11d", "Relevant concomitant care"),
            ("Outcomes", "12", "Primary, secondary, exploratory outcomes"),
            ("Participant timeline", "13", "Schedule of enrolment, interventions, assessments"),
            ("Sample size", "14", "Estimated sample size and justification"),
            ("Recruitment", "15", "Recruitment strategies"),
            ("Allocation: sequence", "16a", "Random sequence generation"),
            ("Allocation: concealment", "16b", "Allocation concealment mechanism"),
            ("Allocation: implementation", "16c", "Who generates, enrolls, assigns"),
            ("Blinding", "17a", "Who is blinded"),
            ("Blinding", "17b", "If blinded, how and when unblinding"),
            ("Data collection", "18a", "Plans for assessment and data collection"),
            ("Data collection", "18b", "Plans to promote retention"),
            ("Data collection", "18c", "Participant exit strategies"),
            ("Statistical methods", "20a", "Statistical methods for primary/secondary outcomes"),
            ("Statistical methods", "20b", "Interim analyses"),
            ("Statistical methods", "21", "Harms / data monitoring committee"),
        ]
        return [
            ChecklistItem(id=f"spirit_{code}", section=section, description=desc)
            for section, code, desc in sections_methods
        ]

    # ------------------------------------------------------------------
    # SQUIRE — quality improvement
    # ------------------------------------------------------------------
    @staticmethod
    def squire() -> List[ChecklistItem]:
        """Return the 18-item SQUIRE 2.0 checklist for quality-improvement studies."""
        items = [
            ("Title", "1", "Indicate QI nature of project"),
            ("Abstract", "2", "Structured abstract"),
            ("Introduction: problem", "3", "Description of problem"),
            ("Introduction: available knowledge", "4", "Summary of available knowledge"),
            ("Introduction: rationale", "5", "Rationale for intervention"),
            ("Introduction: aims", "6", "Specific aims"),
            ("Methods: context", "7", "Context of intervention"),
            ("Methods: interventions", "8", "Description of intervention(s)"),
            ("Methods: study of intervention", "9", "Approach to studying intervention"),
            ("Methods: measures", "10", "Measures used"),
            ("Methods: analysis", "11", "Analysis approach"),
            ("Methods: ethical considerations", "12", "Ethical aspects"),
            ("Results", "13", "Results: initial steps"),
            ("Results", "14", "Results associated with intervention"),
            ("Results", "15", "Summary of process measures"),
            ("Discussion: summary", "16", "Nature of association"),
            ("Discussion: interpretation", "17", "Comparison with prior work"),
            ("Discussion: limitations", "18", "Limitations and sustainability"),
        ]
        return [
            ChecklistItem(id=f"squire_{code}", section=section, description=desc)
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # CHEERS — health economic evaluation
    # ------------------------------------------------------------------
    @staticmethod
    def cheers() -> List[ChecklistItem]:
        """Return the 24-item CHEERS 2022 checklist for health economic evaluation."""
        items = [
            ("Title", "1", "Title identifies as economic evaluation"),
            ("Abstract", "2", "Structured abstract"),
            ("Background", "3", "Research question and policy context"),
            ("Background", "4", "Rationale for chosen comparator"),
            ("Methods: target population", "5", "Population and setting"),
            ("Methods: perspective", "6", "Perspective and why chosen"),
            ("Methods: comparators", "7", "Comparators described"),
            ("Methods: time horizon", "8", "Time horizon and discount rate"),
            ("Methods: choice of outcomes", "9", "Choice of health outcomes"),
            ("Methods: measurement", "10", "Measurement of effectiveness"),
            ("Methods: valuation", "11", "Measurement and valuation of preference-based outcomes"),
            ("Methods: costs", "12", "Estimation of resources and costs"),
            ("Methods: currency", "13", "Currency, price date, conversion"),
            ("Methods: analytic model", "14", "Choice of model"),
            ("Methods: analytic decisions", "15", "Analytic decisions and rationale"),
            ("Results: study parameters", "16", "Characterising uncertainty and heterogeneity"),
            ("Results: study characteristics", "17", "Study parameters / data sources"),
            ("Results", "18", "Summary of effectiveness results"),
            ("Results", "19", "Summary of cost results"),
            ("Results", "20", "Summary of incremental results"),
            ("Results", "21", "Characterising uncertainty"),
            ("Results", "22", "Characterising heterogeneity"),
            ("Discussion: findings", "23", "Study findings, limitations, and generalisability"),
            ("Other", "24", "Source of funding and conflicts of interest"),
        ]
        return [
            ChecklistItem(id=f"cheers_{code}", section=section, description=desc)
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # TREND — non-randomised evaluations
    # ------------------------------------------------------------------
    @staticmethod
    def trend() -> List[ChecklistItem]:
        """Return the 22-item TREND checklist for non-randomised evaluations."""
        items = [
            ("Title and abstract", "1", "Title indicates intervention evaluation"),
            ("Introduction: background", "2", "Background and rationale"),
            ("Introduction: theory", "3", "Theory of intervention"),
            ("Introduction: hypotheses", "4", "Hypotheses / research questions"),
            ("Methods: participants", "5", "Participants and setting"),
            ("Methods: interventions", "6", "Intervention described"),
            ("Methods: design", "7", "Study design"),
            ("Methods: measures", "8", "Outcome measures"),
            ("Methods: analysis", "9", "Statistical analysis"),
            ("Methods: bias", "10", "Addressing biases"),
            ("Methods: other", "11", "Other information"),
            ("Results: sample", "12", "Sample characteristics"),
            ("Results: outcome", "13", "Outcome estimation"),
            ("Results: ancillary", "14", "Ancillary analyses"),
            ("Results: harms", "15", "Adverse events"),
            ("Discussion: interpretation", "16", "Interpretation"),
            ("Discussion: evidence", "17", "Evidence base"),
            ("Discussion: limitations", "18", "Limitations"),
            ("Discussion: generalisability", "19", "Generalisability"),
            ("Discussion: ethics", "20", "Ethical considerations"),
            ("Discussion: funding", "21", "Funding"),
            ("Discussion: dissemination", "22", "Dissemination plan"),
        ]
        return [
            ChecklistItem(id=f"trend_{code}", section=section, description=desc)
            for section, code, desc in items
        ]

    # ------------------------------------------------------------------
    # COREQ — qualitative research
    # ------------------------------------------------------------------
    @staticmethod
    def coreq() -> List[ChecklistItem]:
        """Return the 32-item COREQ checklist for qualitative research."""
        # COREQ is grouped into 3 domains with 32 items; we collapse to
        # one row per item.
        items = [
            ("Domain 1: Research team", "1", "Interviewer/facilitator characteristics"),
            ("Domain 1: Research team", "2", "Interviewer credentials / training"),
            ("Domain 1: Research team", "3", "Relationship with participants established"),
            ("Domain 1: Research team", "4", "Participant knowledge of interviewer"),
            ("Domain 1: Research team", "5", "Interviewer characteristics reported"),
            ("Domain 1: Research team", "6", "Researcher reflexivity stated"),
            ("Domain 1: Research team", "7", "Researcher assumptions / biases stated"),
            ("Domain 2: Study design", "8", "Methodological orientation stated"),
            ("Domain 2: Study design", "9", "Sampling method described"),
            ("Domain 2: Study design", "10", "Method of approach described"),
            ("Domain 2: Study design", "11", "Sample size stated"),
            ("Domain 2: Study design", "12", "Non-participation described"),
            ("Domain 2: Study design", "13", "Setting of data collection"),
            ("Domain 2: Study design", "14", "Presence of non-participants"),
            ("Domain 2: Study design", "15", "Description of sample"),
            ("Domain 2: Study design", "16", "Interview guide described"),
            ("Domain 2: Study design", "17", "Repeat interviews stated"),
            ("Domain 2: Study design", "18", "Audio / visual recording"),
            ("Domain 2: Study design", "19", "Field notes described"),
            ("Domain 2: Study design", "20", "Duration of interviews"),
            ("Domain 2: Study design", "21", "Data saturation discussed"),
            ("Domain 2: Study design", "22", "Transcripts returned to participants"),
            ("Domain 3: Analysis", "23", "Number of data coders"),
            ("Domain 3: Analysis", "24", "Description of coding tree"),
            ("Domain 3: Analysis", "25", "Derivation of themes"),
            ("Domain 3: Analysis", "26", "Software described"),
            ("Domain 3: Analysis", "27", "Participant verification"),
            ("Domain 3: Analysis", "28", "Quotes / illustrations provided"),
            ("Domain 3: Analysis", "29", "Consistency between data and findings"),
            ("Domain 3: Analysis", "30", "Clarity of major themes"),
            ("Domain 3: Analysis", "31", "Clarity of minor themes"),
            ("Domain 3: Reporting", "32", "Funding and COI disclosure"),
        ]
        return [
            ChecklistItem(id=f"coreq_{code}", section=section, description=desc)
            for section, code, desc in items
        ]


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------
class ReportingChecklist:
    """Top-level dispatcher for EQUATOR reporting checklists.

    Wraps :class:`EquatorChecklists` with lookup-by-design, a
    ``get(name)`` accessor and Markdown / PDF rendering helpers.
    """

    # Map study design → recommended checklist name.
    _DESIGN_TO_CHECKLIST: Dict[str, str] = {
        "rct": "consort",
        "randomised controlled trial": "consort",
        "randomized controlled trial": "consort",
        "cohort": "strobe",
        "case-control": "strobe",
        "cross-sectional": "strobe",
        "observational": "strobe",
        "systematic review": "prisma",
        "systematic_review": "prisma",
        "scoping review": "prisma",
        "diagnostic accuracy": "stard",
        "prediction model": "tripod",
        "prediction": "tripod",
        "rct protocol": "spirit",
        "protocol": "spirit",
        "quality improvement": "squire",
        "health economic": "cheers",
        "economic evaluation": "cheers",
        "non-randomised": "trend",
        "non-randomized evaluation": "trend",
        "qualitative": "coreq",
    }

    @classmethod
    def available_checklists(cls) -> List[str]:
        """Return the names of every available checklist."""
        return sorted(EQUATOR_URLS.keys())

    @classmethod
    def equator_network_lookup(cls, study_design: str) -> str:
        """Return the EQUATOR Network URL for ``study_design``.

        Args:
            study_design: Either a checklist name (e.g. ``"consort"``)
                or a study-design phrase (e.g. ``"rct"``,
                ``"systematic review"``).

        Returns:
            The canonical EQUATOR URL.

        Raises:
            KeyError: If no matching checklist is found.
        """
        key = (study_design or "").strip().lower()
        if key in EQUATOR_URLS:
            return EQUATOR_URLS[key]
        if key in cls._DESIGN_TO_CHECKLIST:
            return EQUATOR_URLS[cls._DESIGN_TO_CHECKLIST[key]]
        # Fuzzy: try substring match against design phrases.
        for phrase, ck in cls._DESIGN_TO_CHECKLIST.items():
            if phrase in key or key in phrase:
                return EQUATOR_URLS[ck]
        raise KeyError(
            f"No EQUATOR checklist found for {study_design!r}. "
            f"Available: {cls.available_checklists()}"
        )

    @classmethod
    def get(cls, name: str) -> List[ChecklistItem]:
        """Look up a checklist by name (case-insensitive).

        Args:
            name: Checklist name — either the canonical checklist name
                (e.g. ``"consort"``) or a study-design phrase that
                :meth:`equator_network_lookup` recognises.

        Returns:
            The corresponding :class:`List[ChecklistItem]`.

        Raises:
            KeyError: If the name is unknown.
        """
        key = (name or "").strip().lower()
        if key not in EQUATOR_URLS and key in cls._DESIGN_TO_CHECKLIST:
            key = cls._DESIGN_TO_CHECKLIST[key]
        mapping = {
            "consort": EquatorChecklists.consort,
            "strobe": EquatorChecklists.strobe,
            "prisma": EquatorChecklists.prisma,
            "stard": EquatorChecklists.stard,
            "tripod": EquatorChecklists.tripod,
            "spirit": EquatorChecklists.spirit,
            "squire": EquatorChecklists.squire,
            "cheers": EquatorChecklists.cheers,
            "trend": EquatorChecklists.trend,
            "coreq": EquatorChecklists.coreq,
        }
        if key not in mapping:
            raise KeyError(
                f"Unknown checklist: {name!r}. "
                f"Available: {cls.available_checklists()}"
            )
        return mapping[key]()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    @staticmethod
    def to_markdown(items: List[ChecklistItem]) -> str:
        """Render ``items`` as a Markdown table.

        The table has columns: Reported, ID, Section, Description,
        Location.
        """
        lines = [
            "| Reported | ID | Section | Description | Location |",
            "|---|---|---|---|---|",
        ]
        for it in items:
            mark = "x" if it.reported else " "
            desc = it.description.replace("|", "\\|")
            loc = (it.location_in_report or "").replace("|", "\\|")
            lines.append(
                f"| [{mark}] | {it.id} | {it.section} | {desc} | {loc} |"
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def to_pdf(items: List[ChecklistItem], path: str) -> str:
        """Render ``items`` to a PDF file (lazy ``reportlab`` import).

        Returns:
            The absolute path of the written file.
        """
        try:
            from reportlab.lib.pagesizes import A4  # type: ignore[import]
            from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import]
            from reportlab.lib.units import cm  # type: ignore[import]
            from reportlab.platypus import (  # type: ignore[import]
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
            from reportlab.lib import colors  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ImportError(
                "reportlab is required for ReportingChecklist.to_pdf; "
                "install with: pip install reportlab"
            ) from exc
        import os

        abs_path = os.path.abspath(path)
        doc = SimpleDocTemplate(
            abs_path, pagesize=A4,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
            title="Reporting checklist",
        )
        styles = getSampleStyleSheet()
        story = [Paragraph("Reporting Checklist", styles["Title"]), Spacer(1, 0.4 * cm)]
        data = [["Reported", "ID", "Section", "Description", "Location"]]
        for it in items:
            data.append([
                "x" if it.reported else "",
                it.id,
                it.section,
                it.description,
                it.location_in_report,
            ])
        col_widths = [1.5 * cm, 2.5 * cm, 3 * cm, 7 * cm, 3.5 * cm]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ])
        )
        story.append(table)
        doc.build(story)
        return abs_path


__all__ = [
    "ChecklistItem",
    "EquatorChecklists",
    "ReportingChecklist",
    "EQUATOR_URLS",
]
