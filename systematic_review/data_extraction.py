"""Structured data-extraction forms for systematic reviews.

This module defines the data structures used to capture extracted
information from each included study and a manager that aggregates
extraction forms across a systematic review.

The form layout follows the Cochrane Handbook / JBI standard:

* Bibliographic fields (study_id, study_title, authors, year, journal,
  study_design, country, setting, funding, conflicts_of_interest)
* Population (n_total, n_intervention, n_control, age_mean, age_sd,
  pct_female, ethnicity, inclusion_criteria, exclusion_criteria)
* Intervention (name, description, duration, dose, frequency,
  delivery_mode, comparator_name, comparator_description)
* Outcomes (primary_outcomes, secondary_outcomes — each an
  :class:`OutcomeSpec`)
* Results (effect_sizes — each an :class:`EffectSize`, follow_up_period,
  dropouts, adverse_events)

Two pre-populated templates are provided via
:meth:`DataExtractionForm.from_template`:

* ``cochrane`` — Cochrane-style effectiveness review extraction form
* ``jbi``      — JBI mixed-methods / quasi-experimental extraction form
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import json as _json
import logging
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Outcome & effect-size specifications
# ---------------------------------------------------------------------------

class OutcomeMeasureType(Enum):
    """Type of outcome measure."""

    CONTINUOUS = "continuous"
    DICHOTOMOUS = "dichotomous"
    ORDINAL = "ordinal"
    TIME_TO_EVENT = "time_to_event"

    @classmethod
    def from_value(cls, value: Union[str, "OutcomeMeasureType"]) -> "OutcomeMeasureType":
        if isinstance(value, cls):
            return value
        v = str(value).strip().lower()
        for m in cls:
            if m.value == v or m.name.lower() == v:
                return m
        raise ValueError(f"Unknown OutcomeMeasureType: {value!r}")


@dataclass
class OutcomeSpec:
    """Specification of a single outcome.

    Attributes:
        name: Outcome name (e.g. ``'mortality at 30 days'``).
        measure_type: One of ``continuous`` / ``dichotomous`` /
            ``ordinal`` / ``time_to_event``.
        unit: Unit of measurement (e.g. ``'mmHg'``, ``'log-odds'``).
        time_point: When the outcome was measured (e.g. ``'12 weeks'``).
        favor_treatment_better: If ``True``, lower values favour the
            treatment (e.g. blood pressure); if ``False``, higher values
            favour treatment (e.g. survival).
    """

    name: str = ""
    measure_type: Union[str, OutcomeMeasureType] = OutcomeMeasureType.CONTINUOUS
    unit: str = ""
    time_point: str = ""
    favor_treatment_better: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.measure_type, OutcomeMeasureType):
            self.measure_type = OutcomeMeasureType.from_value(self.measure_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "measure_type": (
                self.measure_type.value
                if isinstance(self.measure_type, OutcomeMeasureType)
                else self.measure_type
            ),
            "unit": self.unit,
            "time_point": self.time_point,
            "favor_treatment_better": self.favor_treatment_better,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutcomeSpec":
        d = dict(data)
        if "measure_type" in d and not isinstance(
            d["measure_type"], OutcomeMeasureType
        ):
            d["measure_type"] = OutcomeMeasureType.from_value(d["measure_type"])
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid}
        return cls(**filtered)


@dataclass
class EffectSize:
    """A single extracted effect-size / arm result.

    The fields populated depend on the outcome measure type:

    * **Continuous** (``measure_type == 'continuous'``): fill
      ``group``, ``n``, ``mean``, ``sd``.
    * **Dichotomous**: fill ``group``, ``events``, ``total``.
    * **Time-to-event**: fill ``hazard_ratio``, ``ci_lower``, ``ci_upper``
      (``group`` may be omitted or set to ``'overall'``).

    Attributes:
        outcome: Outcome name this effect size applies to.
        group: ``'intervention'`` or ``'control'`` (or ``'overall'`` for
            time-to-event / network-meta-analysis contrasts).
        n: Number of participants in the arm (continuous).
        mean: Mean of the continuous outcome in the arm.
        sd: Standard deviation of the outcome in the arm.
        events: Number of events in the arm (dichotomous).
        total: Number of participants in the arm (dichotomous).
        hazard_ratio: Hazard ratio (time-to-event).
        ci_lower: Lower bound of the 95% CI for the effect.
        ci_upper: Upper bound of the 95% CI for the effect.
    """

    outcome: str = ""
    group: str = "intervention"
    n: Optional[int] = None
    mean: Optional[float] = None
    sd: Optional[float] = None
    events: Optional[int] = None
    total: Optional[int] = None
    hazard_ratio: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EffectSize":
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in dict(data).items() if k in valid}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Population / Intervention / Results containers
# ---------------------------------------------------------------------------

@dataclass
class PopulationData:
    """Population characteristics extracted from a study."""

    n_total: Optional[int] = None
    n_intervention: Optional[int] = None
    n_control: Optional[int] = None
    age_mean: Optional[float] = None
    age_sd: Optional[float] = None
    pct_female: Optional[float] = None
    ethnicity: str = ""
    inclusion_criteria: List[str] = field(default_factory=list)
    exclusion_criteria: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PopulationData":
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in dict(data).items() if k in valid}
        return cls(**filtered)


@dataclass
class InterventionData:
    """Intervention & comparator descriptions extracted from a study."""

    name: str = ""
    description: str = ""
    duration: str = ""
    dose: str = ""
    frequency: str = ""
    delivery_mode: str = ""
    comparator_name: str = ""
    comparator_description: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InterventionData":
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in dict(data).items() if k in valid}
        return cls(**filtered)


@dataclass
class ResultsData:
    """Quantitative results extracted from a study."""

    effect_sizes: List[EffectSize] = field(default_factory=list)
    follow_up_period: str = ""
    dropouts: Optional[int] = None
    adverse_events: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "effect_sizes": [es.to_dict() for es in self.effect_sizes],
            "follow_up_period": self.follow_up_period,
            "dropouts": self.dropouts,
            "adverse_events": list(self.adverse_events),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResultsData":
        d = dict(data)
        es_raw = d.pop("effect_sizes", []) or []
        effect_sizes = [
            EffectSize.from_dict(es) if isinstance(es, dict) else es
            for es in es_raw
        ]
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid}
        return cls(effect_sizes=effect_sizes, **filtered)


# ---------------------------------------------------------------------------
# DataExtractionForm
# ---------------------------------------------------------------------------

_EXTRACTION_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "cochrane": {
        "study_design": "RCT (parallel-group)",
        "population": PopulationData(
            inclusion_criteria=[
                "<insert study-level inclusion criteria>",
            ],
            exclusion_criteria=[
                "<insert study-level exclusion criteria>",
            ],
        ).to_dict(),
        "intervention": InterventionData(
            name="<intervention name>",
            comparator_name="<comparator name>",
        ).to_dict(),
        "primary_outcomes": [
            OutcomeSpec(
                name="<primary outcome>",
                measure_type=OutcomeMeasureType.CONTINUOUS,
                unit="<unit>",
                time_point="<time point>",
                favor_treatment_better=True,
            ).to_dict(),
        ],
        "secondary_outcomes": [],
    },
    "jbi": {
        "study_design": "Quasi-experimental",
        "population": PopulationData(
            inclusion_criteria=["<study-level criteria>"],
            exclusion_criteria=[],
        ).to_dict(),
        "intervention": InterventionData(
            name="<intervention / phenomenon of interest>",
            comparator_name="<comparator>",
        ).to_dict(),
        "primary_outcomes": [
            OutcomeSpec(
                name="<primary outcome>",
                measure_type=OutcomeMeasureType.ORDINAL,
            ).to_dict(),
        ],
        "secondary_outcomes": [],
    },
}


@dataclass
class DataExtractionForm:
    """Structured data-extraction form for a single included study.

    Attributes:
        study_id: Stable study identifier.
        study_title: Full title.
        authors: List of author names.
        year: Publication year.
        journal: Journal name.
        study_design: Free-text study-design descriptor.
        country: Country (or countries) of study.
        setting: Setting (e.g. ``'hospital'``, ``'community'``).
        funding: Funding sources.
        conflicts_of_interest: Reported CoI statements.
        population: :class:`PopulationData`.
        intervention: :class:`InterventionData`.
        primary_outcomes: List of :class:`OutcomeSpec`.
        secondary_outcomes: List of :class:`OutcomeSpec`.
        results: :class:`ResultsData`.
        notes: Free-text reviewer notes.
    """

    # Bibliographic
    study_id: str = ""
    study_title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: str = ""
    study_design: str = ""
    country: str = ""
    setting: str = ""
    funding: str = ""
    conflicts_of_interest: str = ""

    # Population
    population: PopulationData = field(default_factory=PopulationData)

    # Intervention
    intervention: InterventionData = field(default_factory=InterventionData)

    # Outcomes
    primary_outcomes: List[OutcomeSpec] = field(default_factory=list)
    secondary_outcomes: List[OutcomeSpec] = field(default_factory=list)

    # Results
    results: ResultsData = field(default_factory=ResultsData)

    # Reviewer notes
    notes: str = ""

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_template(cls, template: str = "cochrane") -> "DataExtractionForm":
        """Build a pre-populated extraction form from a named template.

        Args:
            template: ``'cochrane'`` or ``'jbi'``.

        Returns:
            A populated :class:`DataExtractionForm`.

        Raises:
            ValueError: If ``template`` is not recognised.
        """
        key = (template or "").strip().lower()
        if key not in _EXTRACTION_TEMPLATES:
            raise ValueError(
                f"Unknown extraction template: {template!r}. "
                f"Available: {sorted(_EXTRACTION_TEMPLATES)}"
            )
        data = _json.loads(_json.dumps(_EXTRACTION_TEMPLATES[key]))
        pop = PopulationData.from_dict(data.pop("population", {}))
        inter = InterventionData.from_dict(data.pop("intervention", {}))
        prim = [OutcomeSpec.from_dict(o) for o in data.pop("primary_outcomes", [])]
        sec = [OutcomeSpec.from_dict(o) for o in data.pop("secondary_outcomes", [])]
        return cls(
            population=pop,
            intervention=inter,
            primary_outcomes=prim,
            secondary_outcomes=sec,
            **data,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict of this form."""
        return {
            "study_id": self.study_id,
            "study_title": self.study_title,
            "authors": list(self.authors),
            "year": self.year,
            "journal": self.journal,
            "study_design": self.study_design,
            "country": self.country,
            "setting": self.setting,
            "funding": self.funding,
            "conflicts_of_interest": self.conflicts_of_interest,
            "population": self.population.to_dict(),
            "intervention": self.intervention.to_dict(),
            "primary_outcomes": [o.to_dict() for o in self.primary_outcomes],
            "secondary_outcomes": [o.to_dict() for o in self.secondary_outcomes],
            "results": self.results.to_dict(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataExtractionForm":
        """Reconstruct a :class:`DataExtractionForm` from a dict."""
        d = dict(data)
        pop = PopulationData.from_dict(d.pop("population", {}) or {})
        inter = InterventionData.from_dict(d.pop("intervention", {}) or {})
        results = ResultsData.from_dict(d.pop("results", {}) or {})
        prim = [OutcomeSpec.from_dict(o) for o in d.pop("primary_outcomes", []) or []]
        sec = [OutcomeSpec.from_dict(o) for o in d.pop("secondary_outcomes", []) or []]
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid}
        return cls(
            population=pop,
            intervention=inter,
            results=results,
            primary_outcomes=prim,
            secondary_outcomes=sec,
            **filtered,
        )

    def to_yaml(self, path: str) -> str:
        """Write this form to ``path`` as YAML (falls back to JSON)."""
        path = os.fspath(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        try:
            import yaml  # type: ignore
        except ImportError:  # pragma: no cover
            logger.warning(
                "PyYAML not available; writing JSON instead at %s", path
            )
            alt = path if path.endswith(".json") else path + ".json"
            with open(alt, "w", encoding="utf-8") as fh:
                _json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            return alt
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.to_dict(), fh, sort_keys=False, allow_unicode=True)
        return path


# ---------------------------------------------------------------------------
# DataExtractor
# ---------------------------------------------------------------------------

class DataExtractor:
    """Aggregator that holds extraction forms for many studies.

    Provides lookup, validation, and DataFrame conversion.
    """

    #: Field paths required for "complete" extraction.
    REQUIRED_FIELDS: List[str] = [
        "study_id",
        "study_title",
        "authors",
        "year",
        "study_design",
        "population.n_total",
        "intervention.name",
        "intervention.comparator_name",
        "primary_outcomes",
        "results.effect_sizes",
    ]

    def __init__(self) -> None:
        self._extractions: Dict[str, DataExtractionForm] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_extraction(self, study_id: str, form: DataExtractionForm) -> None:
        """Register a :class:`DataExtractionForm` for ``study_id``.

        Args:
            study_id: Stable study identifier.
            form: The extraction form. Its ``study_id`` field is set
                to ``study_id`` if it was empty.
        """
        sid = (study_id or "").strip()
        if not sid:
            raise ValueError("study_id must not be empty")
        if not form.study_id:
            form.study_id = sid
        self._extractions[sid] = form
        logger.info("Added extraction for study %s", sid)

    def get_extraction(self, study_id: str) -> Optional[DataExtractionForm]:
        """Return the extraction form for ``study_id`` (or ``None``)."""
        return self._extractions.get(study_id)

    def remove_extraction(self, study_id: str) -> bool:
        """Remove the extraction form for ``study_id``."""
        return self._extractions.pop(study_id, None) is not None

    def __len__(self) -> int:
        return len(self._extractions)

    def __contains__(self, study_id: object) -> bool:
        return isinstance(study_id, str) and study_id in self._extractions

    @property
    def extractions(self) -> List[DataExtractionForm]:
        """Return a list of all stored forms."""
        return list(self._extractions.values())

    # ------------------------------------------------------------------
    # DataFrame conversion
    # ------------------------------------------------------------------

    def to_dataframe(self):
        """Return a wide-form :class:`pandas.DataFrame` of all forms."""
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pandas is required for to_dataframe()") from exc
        rows: List[Dict[str, Any]] = []
        for form in self._extractions.values():
            row: Dict[str, Any] = {
                "study_id": form.study_id,
                "study_title": form.study_title,
                "authors": "; ".join(form.authors),
                "year": form.year,
                "journal": form.journal,
                "study_design": form.study_design,
                "country": form.country,
                "setting": form.setting,
                "n_total": form.population.n_total,
                "n_intervention": form.population.n_intervention,
                "n_control": form.population.n_control,
                "age_mean": form.population.age_mean,
                "age_sd": form.population.age_sd,
                "pct_female": form.population.pct_female,
                "intervention_name": form.intervention.name,
                "comparator_name": form.intervention.comparator_name,
                "duration": form.intervention.duration,
                "dose": form.intervention.dose,
                "n_primary_outcomes": len(form.primary_outcomes),
                "n_secondary_outcomes": len(form.secondary_outcomes),
                "n_effect_sizes": len(form.results.effect_sizes),
                "follow_up_period": form.results.follow_up_period,
                "dropouts": form.results.dropouts,
                "n_adverse_events": len(form.results.adverse_events),
                "funding": form.funding,
                "conflicts_of_interest": form.conflicts_of_interest,
                "notes": form.notes,
            }
            rows.append(row)
        df = pd.DataFrame(rows)
        return df

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_completeness(self) -> Dict[str, List[str]]:
        """Return a mapping of ``study_id -> list of missing field paths``.

        A field is "missing" when it is ``None`` / empty string / empty
        list, depending on its type.
        """
        out: Dict[str, List[str]] = {}
        for sid, form in self._extractions.items():
            missing = self._missing_fields(form)
            if missing:
                out[sid] = missing
        return out

    def _missing_fields(self, form: DataExtractionForm) -> List[str]:
        """Return the list of required fields that are missing on ``form``."""
        missing: List[str] = []
        d = form.to_dict()
        for path in self.REQUIRED_FIELDS:
            value: Any = d
            try:
                for part in path.split("."):
                    if isinstance(value, dict):
                        value = value.get(part)
                    elif isinstance(value, list):
                        # if path traverses a list (rare here), fail
                        value = None
                        break
                    else:
                        value = None
                        break
            except Exception:  # pragma: no cover
                value = None
            if value is None or value == "" or (
                isinstance(value, (list, dict)) and len(value) == 0
            ):
                missing.append(path)
        return missing
