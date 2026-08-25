"""REST endpoints for the ``/api/ma`` (meta-analysis) resource.

Wraps the v2.0.0 :mod:`meta_analysis` package: effect-size computation,
pooling (Fixed/Random/DL/REML/MH/Peto), forest/funnel plots, subgroup
analysis, sensitivity (leave-one-out, cumulative), network
meta-analysis, and PDF/DOCX report generation.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import base64
import logging
import tempfile
import os
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

ma_bp = Blueprint("ma", __name__, url_prefix="/api/ma")


def _bad_request(msg: str):
    return jsonify({"error": "bad_request", "message": msg}), 400


@ma_bp.route("/effect-size", methods=["POST"])
def effect_size():
    """Compute a single effect size from intervention + control data.

    Body: ``{"type": str, "intervention": {...}, "control": {...}}``.
    """
    payload = request.get_json(silent=True) or {}
    es_type = (payload.get("type") or "SMD").upper()
    intervention = payload.get("intervention") or {}
    control = payload.get("control") or {}
    try:
        from meta_analysis.effect_sizes import (
            ContinuousGroup, EffectSizeCalculator,
        )
        # Continuous path: n/mean/sd in each arm.
        if es_type in ("MD", "SMD"):
            gi = ContinuousGroup(int(intervention.get("n", 0)),
                                 float(intervention.get("mean", 0)),
                                 float(intervention.get("sd", 0)))
            gc = ContinuousGroup(int(control.get("n", 0)),
                                 float(control.get("mean", 0)),
                                 float(control.get("sd", 0)))
            es = EffectSizeCalculator.from_continuous(gi, gc, type=es_type)
        elif es_type in ("OR", "RR", "RD"):
            # Dichotomous path: events/total in each arm.
            es = EffectSizeCalculator.from_dichotomous(
                int(intervention.get("events", 0)), int(intervention.get("total", 0)),
                int(control.get("events", 0)),    int(control.get("total", 0)),
                type=es_type,
            )
        elif es_type == "HR":
            # Hazard-ratio path: requires pre-computed HR + CI.
            from meta_analysis.effect_sizes import EffectSize, EffectSizeType
            hr = float(payload.get("hr", intervention.get("hr", 0.0)) or 0.0)
            ci_lo = float(payload.get("ci_lower", intervention.get("ci_lower", hr)) or hr)
            ci_hi = float(payload.get("ci_upper", intervention.get("ci_upper", hr)) or hr)
            es = EffectSizeCalculator.from_hazard_ratio(hr, ci_lo, ci_hi)
        else:
            return _bad_request(f"unknown effect-size type: {es_type}")
        return jsonify({"effect_size": es.to_dict() if hasattr(es, "to_dict") else str(es)})
    except Exception as exc:
        logger.exception("/api/ma/effect-size failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@ma_bp.route("/pool", methods=["POST"])
def pool():
    """Pool a list of effect sizes.

    Body: ``{"effect_sizes": [...], "method": str}`` where ``method`` is one
    of ``FIXED``, ``DL``, ``REML``, ``MH``, ``PETO``, ``ML``, ``EB``.
    """
    payload = request.get_json(silent=True) or {}
    es_list_payload = payload.get("effect_sizes") or []
    method_str = (payload.get("method") or "DL").upper()
    try:
        from meta_analysis.effect_sizes import EffectSize, EffectSizeType
        from meta_analysis.pooling import PoolingEngine, PoolingMethod
        # Reconstruct EffectSize objects from dicts.
        es_list = []
        for es_dict in es_list_payload:
            if isinstance(es_dict, EffectSize):
                es_list.append(es_dict)
                continue
            if not isinstance(es_dict, dict):
                continue
            t = es_dict.get("type", "SMD")
            try:
                t_enum = EffectSizeType[t] if isinstance(t, str) else t
            except KeyError:
                t_enum = EffectSizeType.SMD
            es_list.append(EffectSize(
                type=t_enum,
                value=float(es_dict.get("value", 0.0)),
                se=float(es_dict.get("se", 0.0)) or None,
                variance=float(es_dict.get("variance", 0.0)) or None,
                ci_lower=float(es_dict.get("ci_lower", 0.0)) or None,
                ci_upper=float(es_dict.get("ci_upper", 0.0)) or None,
                study_id=es_dict.get("study_id", ""),
                study_name=es_dict.get("study_name", ""),
                events_intervention=es_dict.get("events_intervention"),
                total_intervention=es_dict.get("total_intervention"),
                events_control=es_dict.get("events_control"),
                total_control=es_dict.get("total_control"),
            ))
        method_map = {
            "FIXED": PoolingMethod.FIXED,
            "IV":    PoolingMethod.IV,
            "DL":    PoolingMethod.DL,
            "RANDOM": PoolingMethod.RANDOM,
            "REML":  PoolingMethod.REML,
            "ML":    PoolingMethod.ML,
            "EB":    PoolingMethod.EB,
            "MH":    PoolingMethod.MH,
            "PETO":  PoolingMethod.PETO,
        }
        method = method_map.get(method_str, PoolingMethod.DL)
        result = PoolingEngine.pool(es_list, method=method)
        return jsonify({"result": result.to_dict() if hasattr(result, "to_dict") else str(result)})
    except Exception as exc:
        logger.exception("/api/ma/pool failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


def _render_plot(kind: str, payload: dict):
    """Helper: build + render a forest or funnel plot, return base64 bytes."""
    from meta_analysis.effect_sizes import EffectSize, EffectSizeType
    from meta_analysis.forest_plot import ForestPlot
    from meta_analysis.funnel_plot import FunnelPlot
    es_list_payload = payload.get("effect_sizes") or []
    es_list = []
    for es_dict in es_list_payload:
        if isinstance(es_dict, EffectSize):
            es_list.append(es_dict)
            continue
        if not isinstance(es_dict, dict):
            continue
        t = es_dict.get("type", "SMD")
        try:
            t_enum = EffectSizeType[t] if isinstance(t, str) else t
        except KeyError:
            t_enum = EffectSizeType.SMD
        es_list.append(EffectSize(
            type=t_enum,
            value=float(es_dict.get("value", 0.0)),
            se=float(es_dict.get("se", 0.0)) or None,
            variance=float(es_dict.get("variance", 0.0)) or None,
            ci_lower=float(es_dict.get("ci_lower", 0.0)) or None,
            ci_upper=float(es_dict.get("ci_upper", 0.0)) or None,
            study_id=es_dict.get("study_id", ""),
            study_name=es_dict.get("study_name", ""),
        ))
    pooled_dict = payload.get("pooled")
    pooled = None
    if isinstance(pooled_dict, dict):
        try:
            t = pooled_dict.get("type", es_list[0].type if es_list else EffectSizeType.SMD)
            t_enum = EffectSizeType[t] if isinstance(t, str) else t
            pooled = EffectSize(
                type=t_enum,
                value=float(pooled_dict.get("value", 0.0)),
                se=float(pooled_dict.get("se", 0.0)) or None,
                variance=float(pooled_dict.get("variance", 0.0)) or None,
                ci_lower=float(pooled_dict.get("ci_lower", 0.0)) or None,
                ci_upper=float(pooled_dict.get("ci_upper", 0.0)) or None,
            )
        except Exception as exc:
            logger.debug("pooled effect-size build failed: %s", exc)
    fmt = (payload.get("format") or "png").strip().lower()
    if kind == "forest":
        fp = ForestPlot(es_list, pooled=pooled, title=payload.get("title", ""))
    else:
        fp = FunnelPlot(es_list, pooled=pooled)
    path = tempfile.mktemp(suffix=f".{fmt}")
    fp.save(path, format=fmt)
    with open(path, "rb") as fh:
        content = base64.b64encode(fh.read()).decode("ascii")
    try:
        os.remove(path)
    except OSError:
        pass
    return content, fmt


@ma_bp.route("/forest-plot", methods=["POST"])
def forest_plot():
    """Render a forest plot and return the encoded image bytes.

    Body: ``{"effect_sizes": [...], "pooled": {...}?, "format": "png"|"svg"|"pdf"?}``.
    """
    payload = request.get_json(silent=True) or {}
    try:
        content, fmt = _render_plot("forest", payload)
        return jsonify({"format": fmt, "content_b64": content})
    except Exception as exc:
        logger.exception("/api/ma/forest-plot failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@ma_bp.route("/funnel-plot", methods=["POST"])
def funnel_plot():
    """Render a funnel plot and return the encoded image bytes."""
    payload = request.get_json(silent=True) or {}
    try:
        content, fmt = _render_plot("funnel", payload)
        return jsonify({"format": fmt, "content_b64": content})
    except Exception as exc:
        logger.exception("/api/ma/funnel-plot failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@ma_bp.route("/subgroup", methods=["POST"])
def subgroup():
    """Run a subgroup analysis.

    Body: ``{"effect_sizes": [...], "subgroups": [str, ...]}`` — the
    ``subgroups`` list must align index-by-index with ``effect_sizes``.
    """
    payload = request.get_json(silent=True) or {}
    es_list_payload = payload.get("effect_sizes") or []
    subgroups = payload.get("subgroups") or []
    try:
        from meta_analysis.effect_sizes import EffectSize, EffectSizeType
        from meta_analysis.subgroup import SubgroupAnalysis
        # Reconstruct EffectSize objects.
        es_list = []
        for es_dict in es_list_payload:
            if isinstance(es_dict, EffectSize):
                es_list.append(es_dict)
                continue
            if not isinstance(es_dict, dict):
                continue
            t = es_dict.get("type", "SMD")
            try:
                t_enum = EffectSizeType[t] if isinstance(t, str) else t
            except KeyError:
                t_enum = EffectSizeType.SMD
            es_list.append(EffectSize(
                type=t_enum,
                value=float(es_dict.get("value", 0.0)),
                se=float(es_dict.get("se", 0.0)) or None,
                variance=float(es_dict.get("variance", 0.0)) or None,
            ))
        result = SubgroupAnalysis().analyze(es_list, subgroups)
        return jsonify({"result": result.to_dict() if hasattr(result, "to_dict") else str(result)})
    except Exception as exc:
        logger.exception("/api/ma/subgroup failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@ma_bp.route("/sensitivity", methods=["POST"])
def sensitivity():
    """Run a leave-one-out or cumulative sensitivity analysis.

    Body: ``{"effect_sizes": [...], "type": "leave_one_out"|"cumulative"}``.
    """
    payload = request.get_json(silent=True) or {}
    kind = (payload.get("type") or "leave_one_out").strip().lower()
    es_list_payload = payload.get("effect_sizes") or []
    try:
        from meta_analysis.effect_sizes import EffectSize, EffectSizeType
        from meta_analysis.subgroup import SensitivityAnalysis
        es_list = []
        for es_dict in es_list_payload:
            if isinstance(es_dict, EffectSize):
                es_list.append(es_dict)
                continue
            if not isinstance(es_dict, dict):
                continue
            t = es_dict.get("type", "SMD")
            try:
                t_enum = EffectSizeType[t] if isinstance(t, str) else t
            except KeyError:
                t_enum = EffectSizeType.SMD
            es_list.append(EffectSize(
                type=t_enum,
                value=float(es_dict.get("value", 0.0)),
                se=float(es_dict.get("se", 0.0)) or None,
                variance=float(es_dict.get("variance", 0.0)) or None,
            ))
        if kind == "cumulative":
            results = SensitivityAnalysis.cumulative(es_list)
        else:
            results = SensitivityAnalysis.leave_one_out(es_list)
        return jsonify({
            "type": kind,
            "results": [r.to_dict() if hasattr(r, "to_dict") else str(r) for r in (results or [])],
        })
    except Exception as exc:
        logger.exception("/api/ma/sensitivity failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@ma_bp.route("/nma", methods=["POST"])
def nma():
    """Run a network meta-analysis over the supplied comparisons.

    Body: ``{"comparisons": [{"study_id": str, "treatment_a": str,
    "treatment_b": str, "effect_size": float, "se": float, "n_total": int?}]}``.
    """
    payload = request.get_json(silent=True) or {}
    comparisons_payload = payload.get("comparisons") or []
    try:
        from meta_analysis.network_meta import (
            NetworkMetaAnalysis, TreatmentComparison,
        )
        comparisons = []
        for c in comparisons_payload:
            try:
                comparisons.append(TreatmentComparison(
                    study_id=c.get("study_id", ""),
                    treatment_a=c.get("treatment_a", ""),
                    treatment_b=c.get("treatment_b", ""),
                    effect_size=float(c.get("effect_size", 0.0)),
                    se=float(c.get("se", 0.0)),
                    n_total=int(c.get("n_total", 0) or 0),
                ))
            except Exception as exc:
                logger.debug("Comparison build failed: %s", exc)
        nma_obj = NetworkMetaAnalysis(comparisons)
        result = nma_obj.consistency_model()
        return jsonify({
            "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
        })
    except Exception as exc:
        logger.exception("/api/ma/nma failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@ma_bp.route("/report", methods=["POST"])
def report():
    """Generate a PDF or DOCX meta-analysis report.

    Body: ``{"meta_result": {...}, "effect_sizes": [...], "study_data": {...},
    "format": "pdf"|"docx"}``.
    """
    payload = request.get_json(silent=True) or {}
    fmt = (payload.get("format") or "pdf").strip().lower()
    try:
        from meta_analysis.report import MetaAnalysisReport
        # The endpoint currently accepts the structured payload and forwards
        # it to MetaAnalysisReport.generate(); for non-trivial use the caller
        # is expected to round-trip the result via /api/ma/pool first.
        report_obj = MetaAnalysisReport(
            meta_result=payload.get("meta_result"),
            effect_sizes=payload.get("effect_sizes") or [],
            study_data=payload.get("study_data") or {},
        )
        path = tempfile.mktemp(suffix=f".{fmt}")
        report_obj.generate(path, format=fmt)
        with open(path, "rb") as fh:
            content = base64.b64encode(fh.read()).decode("ascii")
        try:
            os.remove(path)
        except OSError:
            pass
        return jsonify({"format": fmt, "content_b64": content})
    except Exception as exc:
        logger.exception("/api/ma/report failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502
