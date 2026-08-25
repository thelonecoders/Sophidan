"""Protocol templates and registration for systematic reviews.

This module defines :class:`SystematicReviewProtocol`, a dataclass-based
container describing the *a priori* plan for a systematic review —
research question, PICO framework, eligibility criteria, search
strategy, planned risk-of-bias tool and synthesis method, registration
metadata (PROSPERO ID), authors, version, and audit timestamps.

Four protocol templates are pre-populated via
:meth:`SystematicReviewProtocol.from_template`:

* ``cochrane``     — Cochrane Handbook systematic-review skeleton
* ``campbell``     — Campbell Collaboration skeleton
* ``jbi``          — JBI (Joanna Briggs Institute) skeleton
* ``prisma_2020``  — bare PRISMA 2020 skeleton

A protocol can be serialised to YAML / JSON, validated against a
minimal required-fields rule, and version-upgraded. Version upgrades
archive the previous state into a ``snapshots/`` directory next to the
protocol file.

The module is intentionally free of any third-party import at module
scope: ``yaml`` / ``json`` / date utilities are imported lazily inside
the methods that use them, so simply importing this module never
raises even in a minimal Python environment.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import json as _json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PICO helper
# ---------------------------------------------------------------------------

@dataclass
class PICOFramework:
    """Population / Intervention / Comparator / Outcome framework.

    A simple structured container used by the protocol's
    ``pico_framework`` field. All four components are optional strings
    so that partial PICOs (e.g. no comparator for diagnostic reviews)
    can be expressed.
    """

    population: str = ""
    intervention: str = ""
    comparator: str = ""
    outcome: str = ""
    #: Optional study-design component (PICO-S extension).
    study_design: str = ""
    #: Optional timing component (PICOT extension).
    timing: str = ""
    #: Optional setting component.
    setting: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict of this PICO."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PICOFramework":
        """Build a :class:`PICOFramework` from a (possibly partial) dict."""
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in dict(data).items() if k in valid}
        return cls(**filtered)

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        parts = [
            f"Population: {self.population}",
            f"Intervention: {self.intervention}",
            f"Comparator: {self.comparator}",
            f"Outcome: {self.outcome}",
        ]
        if self.study_design:
            parts.append(f"Study design: {self.study_design}")
        if self.timing:
            parts.append(f"Timing: {self.timing}")
        if self.setting:
            parts.append(f"Setting: {self.setting}")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# Eligibility criteria
# ---------------------------------------------------------------------------

@dataclass
class EligibilityCriteria:
    """Inclusion / exclusion criteria container."""

    inclusion: List[str] = field(default_factory=list)
    exclusion: List[str] = field(default_factory=list)
    #: Free-text notes on how criteria were operationalised.
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EligibilityCriteria":
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in dict(data).items() if k in valid}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "cochrane": {
        "title": "Cochrane Systematic Review (untitled)",
        "research_question": "<State the research question in PICO format>",
        "pico_framework": PICOFramework(
            population="<population>",
            intervention="<intervention>",
            comparator="<comparator or placebo>",
            outcome="<primary outcome>",
            study_design="RCTs only",
        ).to_dict(),
        "objectives": [
            "To assess the effects of <intervention> for <population> "
            "compared with <comparator> on <outcome>.",
        ],
        "eligibility_criteria": EligibilityCriteria(
            inclusion=[
                "RCTs (parallel-group or cross-over)",
                "Population: <population>",
                "Intervention: <intervention>",
                "Comparator: <comparator, placebo, or no treatment>",
                "Outcome: <primary outcome>",
            ],
            exclusion=[
                "Non-randomised studies",
                "Conference abstracts / posters only",
                "Non-English language (if applicable)",
            ],
        ).to_dict(),
        "information_sources": [
            "Cochrane Central Register of Controlled Trials (CENTRAL)",
            "MEDLINE (Ovid)",
            "Embase (Ovid)",
            "ClinicalTrials.gov",
            "WHO ICTRP",
            "Hand-searching of reference lists",
        ],
        "search_strategy": {
            "MEDLINE": "<place MEDLINE search string here>",
            "Embase": "<place Embase search string here>",
            "CENTRAL": "<place CENTRAL search string here>",
        },
        "search_date_range": "From inception to <date of search>",
        "data_extraction_template": "cochrane",
        "risk_of_bias_tool": "CochraneRoB2",
        "synthesis_method": "META_ANALYSIS",
        "registration": "",
        "authors": [],
        "version": "0.1.0",
    },
    "campbell": {
        "title": "Campbell Systematic Review (untitled)",
        "research_question": "<State the research question>",
        "pico_framework": PICOFramework(
            population="<population>",
            intervention="<intervention / programme>",
            comparator="<comparator>",
            outcome="<outcome>",
            study_design="Randomised and quasi-experimental designs",
        ).to_dict(),
        "objectives": [
            "To assess the effects of <intervention> for <population>.",
        ],
        "eligibility_criteria": EligibilityCriteria(
            inclusion=[
                "Randomised and quasi-experimental studies",
                "Population: <population>",
                "Intervention: <intervention>",
            ],
            exclusion=[
                "Pure observational studies without comparator",
            ],
        ).to_dict(),
        "information_sources": [
            "Campbell Collaboration's CEL",
            "MEDLINE",
            "Embase",
            "PsycINFO",
            "ERIC (where relevant)",
            "Web of Science",
        ],
        "search_strategy": {
            "MEDLINE": "<placeholder>",
            "Embase": "<placeholder>",
        },
        "search_date_range": "From inception to <date>",
        "data_extraction_template": "jbi",
        "risk_of_bias_tool": "ROBINS_I",
        "synthesis_method": "NARRATIVE_TABULAR",
        "registration": "",
        "authors": [],
        "version": "0.1.0",
    },
    "jbi": {
        "title": "JBI Systematic Review (untitled)",
        "research_question": "<State the research question (PCC for scoping / PICO for effectiveness)>",
        "pico_framework": PICOFramework(
            population="<population>",
            intervention="<phenomenon of interest / intervention>",
            comparator="<comparator>",
            outcome="<outcome>",
            study_design="<study designs of interest>",
        ).to_dict(),
        "objectives": [
            "To synthesise the best available evidence on <topic>.",
        ],
        "eligibility_criteria": EligibilityCriteria(
            inclusion=[
                "Studies meeting the PICO/PCC criteria",
                "Published peer-reviewed primary studies",
            ],
            exclusion=[
                "Secondary sources (other reviews) unless used for hand-searching",
            ],
        ).to_dict(),
        "information_sources": [
            "JBI Database of Systematic Reviews",
            "MEDLINE",
            "Embase",
            "CINAHL",
            "Scopus",
            "Web of Science",
        ],
        "search_strategy": {
            "MEDLINE": "<placeholder>",
            "Embase": "<placeholder>",
            "CINAHL": "<placeholder>",
        },
        "search_date_range": "From inception to <date>",
        "data_extraction_template": "jbi",
        "risk_of_bias_tool": "JBI_Critical_Appraisal",
        "synthesis_method": "NARRATIVE",
        "registration": "",
        "authors": [],
        "version": "0.1.0",
    },
    "prisma_2020": {
        "title": "PRISMA 2020 Systematic Review (untitled)",
        "research_question": "<State the research question>",
        "pico_framework": PICOFramework().to_dict(),
        "objectives": [],
        "eligibility_criteria": EligibilityCriteria().to_dict(),
        "information_sources": [
            "MEDLINE",
            "Embase",
            "Cochrane CENTRAL",
            "Web of Science",
            "Scopus",
        ],
        "search_strategy": {},
        "search_date_range": "",
        "data_extraction_template": "cochrane",
        "risk_of_bias_tool": "CochraneRoB2",
        "synthesis_method": "NARRATIVE_TABULAR",
        "registration": "",
        "authors": [],
        "version": "0.1.0",
    },
}


# ---------------------------------------------------------------------------
# SystematicReviewProtocol
# ---------------------------------------------------------------------------

@dataclass
class SystematicReviewProtocol:
    """Container for a systematic-review protocol.

    Attributes:
        title: Human-readable review title.
        research_question: The primary research question, ideally in
            PICO format.
        pico_framework: Structured PICO/PICOS container.
        objectives: List of review objectives.
        eligibility_criteria: Inclusion / exclusion container.
        information_sources: List of databases and other sources to
            be searched.
        search_strategy: Mapping of database name -> query string.
        search_date_range: Human-readable date-range descriptor.
        data_extraction_template: Name of the extraction-form template
            to use (``cochrane`` / ``jbi``).
        risk_of_bias_tool: Name of the planned RoB tool
            (``CochraneRoB2`` / ``ROBINS_I`` / ``QUADAS2`` /
            ``NewcastleOttawaScale``).
        synthesis_method: Name of the planned synthesis method
            (see :class:`systematic_review.synthesis.SynthesisMethod`).
        registration: PROSPERO registration ID (or empty).
        authors: List of author names.
        version: Semantic version string (e.g. ``1.0.0``).
        created_at: ISO-8601 UTC timestamp of creation.
        updated_at: ISO-8601 UTC timestamp of last update.
    """

    title: str = ""
    research_question: str = ""
    pico_framework: PICOFramework = field(default_factory=PICOFramework)
    objectives: List[str] = field(default_factory=list)
    eligibility_criteria: EligibilityCriteria = field(default_factory=EligibilityCriteria)
    information_sources: List[str] = field(default_factory=list)
    search_strategy: Dict[str, str] = field(default_factory=dict)
    search_date_range: str = ""
    data_extraction_template: str = "cochrane"
    risk_of_bias_tool: str = "CochraneRoB2"
    synthesis_method: str = "NARRATIVE_TABULAR"
    registration: str = ""
    authors: List[str] = field(default_factory=list)
    version: str = "0.1.0"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_template(cls, template_name: str = "cochrane") -> "SystematicReviewProtocol":
        """Build a protocol pre-populated from a named template.

        Args:
            template_name: One of ``cochrane``, ``campbell``, ``jbi``,
                ``prisma_2020``.

        Returns:
            A populated :class:`SystematicReviewProtocol`.

        Raises:
            ValueError: If ``template_name`` is not recognised.
        """
        key = (template_name or "").strip().lower()
        if key not in _TEMPLATES:
            raise ValueError(
                f"Unknown protocol template: {template_name!r}. "
                f"Available: {sorted(_TEMPLATES)}"
            )
        data = _json.loads(_json.dumps(_TEMPLATES[key]))  # deep copy
        pico = PICOFramework.from_dict(data.pop("pico_framework", {}))
        elig = EligibilityCriteria.from_dict(data.pop("eligibility_criteria", {}))
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            pico_framework=pico,
            eligibility_criteria=elig,
            created_at=now,
            updated_at=now,
            **data,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict of this protocol."""
        data = asdict(self) if False else {
            "title": self.title,
            "research_question": self.research_question,
            "pico_framework": self.pico_framework.to_dict(),
            "objectives": list(self.objectives),
            "eligibility_criteria": self.eligibility_criteria.to_dict(),
            "information_sources": list(self.information_sources),
            "search_strategy": dict(self.search_strategy),
            "search_date_range": self.search_date_range,
            "data_extraction_template": self.data_extraction_template,
            "risk_of_bias_tool": self.risk_of_bias_tool,
            "synthesis_method": self.synthesis_method,
            "registration": self.registration,
            "authors": list(self.authors),
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystematicReviewProtocol":
        """Reconstruct a :class:`SystematicReviewProtocol` from a dict."""
        d = dict(data)
        pico = PICOFramework.from_dict(d.pop("pico_framework", {}))
        elig = EligibilityCriteria.from_dict(d.pop("eligibility_criteria", {}))
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid}
        return cls(pico_framework=pico, eligibility_criteria=elig, **filtered)

    def to_json(self, path: str) -> str:
        """Write this protocol to ``path`` as JSON and return the path.

        Args:
            path: Filesystem path. Parent directories are created.

        Returns:
            The ``path`` argument, for chaining.
        """
        path = os.fspath(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            _json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        logger.info("Wrote protocol JSON to %s", path)
        return path

    def to_yaml(self, path: str) -> str:
        """Write this protocol to ``path`` as YAML and return the path.

        Falls back to writing JSON if PyYAML is not available.

        Args:
            path: Filesystem path. Parent directories are created.

        Returns:
            The ``path`` argument.
        """
        path = os.fspath(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        try:
            import yaml  # type: ignore
        except ImportError:  # pragma: no cover - defensive
            logger.warning(
                "PyYAML not available; falling back to JSON at %s", path
            )
            return self.to_json(path if path.endswith(".json") else path + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.to_dict(), fh, sort_keys=False, allow_unicode=True)
        logger.info("Wrote protocol YAML to %s", path)
        return path

    @classmethod
    def from_file(cls, path: str) -> "SystematicReviewProtocol":
        """Load a protocol from a JSON or YAML file (auto-detected)."""
        path = os.fspath(path)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if path.lower().endswith((".yaml", ".yml")):
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(text)
            except ImportError:  # pragma: no cover
                raise RuntimeError(
                    "PyYAML is required to load YAML protocol files"
                )
        else:
            data = _json.loads(text)
        return cls.from_dict(data or {})

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> List[str]:
        """Return a list of missing required fields (empty = valid).

        The required-field list intentionally mirrors the minimum
        information needed for a PRISMA-compliant protocol.

        Returns:
            A list of human-readable strings describing each missing /
            incomplete required field. An empty list means the
            protocol passes minimum completeness.
        """
        missing: List[str] = []
        if not self.title or self.title.startswith("<"):
            missing.append("title is missing or still a placeholder")
        if not self.research_question or self.research_question.startswith("<"):
            missing.append("research_question is missing or still a placeholder")
        if not self.pico_framework.population:
            missing.append("pico_framework.population is missing")
        if not self.pico_framework.intervention:
            missing.append("pico_framework.intervention is missing")
        if not self.pico_framework.outcome:
            missing.append("pico_framework.outcome is missing")
        if not self.objectives:
            missing.append("objectives list is empty")
        if not self.eligibility_criteria.inclusion:
            missing.append("eligibility_criteria.inclusion is empty")
        if not self.eligibility_criteria.exclusion:
            missing.append("eligibility_criteria.exclusion is empty")
        if not self.information_sources:
            missing.append("information_sources list is empty")
        if not self.search_strategy:
            missing.append("search_strategy mapping is empty")
        if not self.search_date_range:
            missing.append("search_date_range is missing")
        if not self.risk_of_bias_tool:
            missing.append("risk_of_bias_tool is missing")
        if not self.synthesis_method:
            missing.append("synthesis_method is missing")
        if not self.authors:
            missing.append("authors list is empty")
        return missing

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    def version_up(
        self, snapshot_dir: Optional[str] = None, note: str = ""
    ) -> str:
        """Bump the protocol's semantic version and archive the prior state.

        The previous protocol state is written to a ``snapshots/``
        directory located either at ``snapshot_dir`` (if given) or next
        to the directory implied by the current ``__module__``. The
        snapshot filename embeds the prior version and a UTC timestamp.

        Versioning rule:

            * ``MAJOR.MINOR.PATCH`` → bump PATCH by 1 by default.
            * If ``note`` is exactly ``"major"`` / ``"minor"``, bump
              the corresponding component and zero the lower ones.

        Args:
            snapshot_dir: Optional directory in which to write the
                snapshot. Defaults to ``./snapshots``.
            note: Optional bump hint (``"major"`` / ``"minor"`` /
                anything else = patch).

        Returns:
            The new version string.
        """
        prior_version = self.version
        new_version = self._bump_version(self.version, note)
        # archive prior state
        target_dir = os.path.abspath(snapshot_dir or "snapshots")
        os.makedirs(target_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_prior = prior_version.replace(".", "_")
        snap_path = os.path.join(
            target_dir, f"protocol_v{safe_prior}_{ts}.json"
        )
        # snapshot the PRE-state (before bumping in-memory)
        prior_data = self.to_dict()
        prior_data["version"] = prior_version
        with open(snap_path, "w", encoding="utf-8") as fh:
            _json.dump(prior_data, fh, indent=2, ensure_ascii=False)
        logger.info(
            "Archived protocol snapshot v%s -> %s", prior_version, snap_path
        )
        # bump in-memory
        self.version = new_version
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return new_version

    @staticmethod
    def _bump_version(version: str, note: str) -> str:
        """Return a bumped semantic version string."""
        note = (note or "").strip().lower()
        try:
            major, minor, patch = (int(x) for x in version.split("."))
        except Exception:
            logger.warning(
                "Unparseable version %r; resetting to 0.1.0", version
            )
            return "0.1.0"
        if note == "major":
            major += 1
            minor = 0
            patch = 0
        elif note == "minor":
            minor += 1
            patch = 0
        else:
            patch += 1
        return f"{major}.{minor}.{patch}"

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def is_registered(self) -> bool:
        """Return ``True`` if a PROSPERO ID is set."""
        return bool(self.registration and self.registration.strip())

    def register(self, prospero_id: str) -> None:
        """Set the PROSPERO registration ID."""
        self.registration = (prospero_id or "").strip()
        self.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info("Protocol registered as PROSPERO %s", self.registration)

    def add_author(self, name: str) -> None:
        """Append an author (no-op if already present)."""
        name = (name or "").strip()
        if name and name not in self.authors:
            self.authors.append(name)
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"SystematicReviewProtocol(title={self.title!r}, "
            f"version={self.version!r}, registered={self.is_registered()})"
        )
