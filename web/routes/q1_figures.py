"""REST endpoints for the ``/api/figures`` resource.

Wraps the v2.0.0 :mod:`q1_figures` package: publication-grade figure
generation across 15 plot types, 6 journal styles (Nature / Science /
Cell / NEJM / Lancet / JAMA), 3 column widths, 3 DPI options, and 4
output formats (PNG/SVG/PDF/TIFF).

Every endpoint accepts JSON plot data plus style/size/format params
and returns ``send_file`` of the rendered image bytes.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import io
import logging
import os
import tempfile
from typing import Any, Callable

from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)

figures_bp = Blueprint("figures", __name__, url_prefix="/api/figures")


def _bad_request(msg: str):
    return jsonify({"error": "bad_request", "message": msg}), 400


def _common_params() -> dict:
    """Pull journal/size/dpi/format params from the request body."""
    payload = request.get_json(silent=True) or {}
    return {
        "journal": payload.pop("journal", "Nature"),
        "size":    payload.pop("size", "single"),
        "dpi":     int(payload.pop("dpi", 300) or 300),
        "format":  payload.pop("format", "png").lower(),
        "title":   payload.pop("title", ""),
        "data":    payload,
    }


def _render_sendfile(builder: Callable[[str, dict], None]) -> Any:
    """Build a temp file via ``builder(path, params)`` then return send_file."""
    params = _common_params()
    fmt = params["format"]
    if fmt not in ("png", "svg", "pdf", "tiff"):
        return _bad_request("format must be one of png|svg|pdf|tiff")
    try:
        suffix = f".{fmt}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            path = tmp.name
        builder(path, params)
        with open(path, "rb") as fh:
            buf = io.BytesIO(fh.read())
        try:
            os.remove(path)
        except OSError:
            pass
        mimetype = {
            "png":  "image/png",
            "svg":  "image/svg+xml",
            "pdf":  "application/pdf",
            "tiff": "image/tiff",
        }.get(fmt, "application/octet-stream")
        return send_file(buf, mimetype=mimetype, as_attachment=True,
                         download_name=f"figure.{fmt}")
    except Exception as exc:
        logger.exception("/api/figures render failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


# ----------------------------------------------------------------- Forest / Funnel

def _build_effect_sizes(data: dict) -> list:
    """Reconstruct a list of :class:`EffectSize` from JSON dicts."""
    from meta_analysis.effect_sizes import EffectSize, EffectSizeType
    es_list = []
    for d in data.get("effect_sizes", []):
        t = d.get("type", "SMD")
        try:
            t_enum = EffectSizeType[t] if isinstance(t, str) else t
        except KeyError:
            t_enum = EffectSizeType.SMD
        es_list.append(EffectSize(
            type=t_enum,
            value=float(d.get("value", 0.0)),
            se=float(d.get("se", 0.0)) or None,
            variance=float(d.get("variance", 0.0)) or None,
            ci_lower=float(d.get("ci_lower", 0.0)) or None,
            ci_upper=float(d.get("ci_upper", 0.0)) or None,
            study_id=d.get("study_id", ""),
            study_name=d.get("study_name", ""),
        ))
    return es_list


def _build_pooled(data: dict, es_list: list):
    """Reconstruct the optional pooled :class:`EffectSize`."""
    from meta_analysis.effect_sizes import EffectSize, EffectSizeType
    pooled_dict = data.get("pooled")
    if not isinstance(pooled_dict, dict) or not es_list:
        return None
    t = pooled_dict.get("type", es_list[0].type)
    t_enum = EffectSizeType[t] if isinstance(t, str) else t
    return EffectSize(
        type=t_enum,
        value=float(pooled_dict.get("value", 0.0)),
        se=float(pooled_dict.get("se", 0.0)) or None,
        variance=float(pooled_dict.get("variance", 0.0)) or None,
        ci_lower=float(pooled_dict.get("ci_lower", 0.0)) or None,
        ci_upper=float(pooled_dict.get("ci_upper", 0.0)) or None,
    )


def _forest_builder(path: str, params: dict) -> None:
    from meta_analysis.forest_plot import ForestPlot
    data = params["data"]
    es_list = _build_effect_sizes(data)
    pooled = _build_pooled(data, es_list)
    ForestPlot(es_list, pooled=pooled, title=params.get("title", "")).save(
        path, format=params["format"],
    )


def _funnel_builder(path: str, params: dict) -> None:
    from meta_analysis.funnel_plot import FunnelPlot
    data = params["data"]
    es_list = _build_effect_sizes(data)
    pooled = _build_pooled(data, es_list)
    FunnelPlot(es_list, pooled=pooled).save(path, format=params["format"])


@figures_bp.route("/forest", methods=["POST"])
def forest():
    """Render a forest plot.

    Body: ``{"effect_sizes": [...], "pooled": {...}?, "journal": str,
    "dpi": int, "format": str}``.
    """
    return _render_sendfile(_forest_builder)


@figures_bp.route("/funnel", methods=["POST"])
def funnel():
    """Render a funnel plot."""
    return _render_sendfile(_funnel_builder)


# ----------------------------------------------------------------- Generic plot helpers

def _generic_statistical_plot(plot_method: str):
    """Build a builder closure for a :class:`StatisticalPlots` method."""
    def builder(path: str, params: dict) -> None:
        from q1_figures.statistical_plots import StatisticalPlots
        data = params["data"]
        fn = getattr(StatisticalPlots, plot_method, None)
        if fn is None:
            raise ValueError(f"StatisticalPlots has no method {plot_method!r}")
        fig = fn(**data) if isinstance(data, dict) else fn(data)
        if fig is None:
            raise RuntimeError(f"{plot_method} returned no figure")
        fig.savefig(path, format=params["format"], dpi=params.get("dpi", 300),
                    constrained_layout=True)
    return builder


def _generic_data_plot(plot_method: str):
    def builder(path: str, params: dict) -> None:
        from q1_figures.data_plots import Q1DataPlots
        data = params["data"]
        fn = getattr(Q1DataPlots, plot_method, None)
        if fn is None:
            raise ValueError(f"Q1DataPlots has no method {plot_method!r}")
        fig = fn(**data) if isinstance(data, dict) else fn(data)
        if fig is None:
            raise RuntimeError(f"{plot_method} returned no figure")
        fig.savefig(path, format=params["format"], dpi=params.get("dpi", 300),
                    constrained_layout=True)
    return builder


def _generic_network_plot(plot_method: str):
    def builder(path: str, params: dict) -> None:
        from q1_figures.network_plots import Q1NetworkPlots
        data = params["data"]
        fn = getattr(Q1NetworkPlots, plot_method, None)
        if fn is None:
            raise ValueError(f"Q1NetworkPlots has no method {plot_method!r}")
        fig = fn(**data) if isinstance(data, dict) else fn(data)
        if fig is None:
            raise RuntimeError(f"{plot_method} returned no figure")
        fig.savefig(path, format=params["format"], dpi=params.get("dpi", 300),
                    constrained_layout=True)
    return builder


@figures_bp.route("/volcano", methods=["POST"])
def volcano():
    return _render_sendfile(_generic_statistical_plot("volcano_plot"))


@figures_bp.route("/manhattan", methods=["POST"])
def manhattan():
    return _render_sendfile(_generic_statistical_plot("manhattan_plot"))


@figures_bp.route("/qq", methods=["POST"])
def qq():
    return _render_sendfile(_generic_statistical_plot("qq_plot"))


@figures_bp.route("/kaplan-meier", methods=["POST"])
def kaplan_meier():
    return _render_sendfile(_generic_statistical_plot("kaplan_meier"))


@figures_bp.route("/roc", methods=["POST"])
def roc():
    return _render_sendfile(_generic_statistical_plot("roc_curve"))


@figures_bp.route("/pr-curve", methods=["POST"])
def pr_curve():
    return _render_sendfile(_generic_statistical_plot("pr_curve"))


@figures_bp.route("/boxplot", methods=["POST"])
def boxplot():
    return _render_sendfile(_generic_statistical_plot("boxplot"))


@figures_bp.route("/violin", methods=["POST"])
def violin():
    return _render_sendfile(_generic_statistical_plot("violinplot"))


@figures_bp.route("/raincloud", methods=["POST"])
def raincloud():
    return _render_sendfile(_generic_statistical_plot("raincloud_plot"))


@figures_bp.route("/heatmap", methods=["POST"])
def heatmap():
    return _render_sendfile(_generic_data_plot("heatmap"))


@figures_bp.route("/network", methods=["POST"])
def network():
    return _render_sendfile(_generic_network_plot("network_figure"))


@figures_bp.route("/sankey", methods=["POST"])
def sankey():
    return _render_sendfile(_generic_network_plot("sankey_diagram"))


@figures_bp.route("/multi-panel", methods=["POST"])
def multi_panel():
    """Render a multi-panel figure.

    Body: ``{"panels": [{"type": str, "data": {...}}, ...], "rows": int,
    "cols": int, "journal": str, "dpi": int, "format": str}``.
    """
    def builder(path: str, params: dict) -> None:
        from q1_figures.multi_panel import MultiPanelFigure
        data = params["data"]
        mp = MultiPanelFigure(rows=int(data.get("rows", 1)),
                              cols=int(data.get("cols", 1)))
        for p in data.get("panels", []):
            mp.add_panel(row=int(p.get("row", 0)), col=int(p.get("col", 0)))
        mp.save(path, format=params["format"], dpi=params.get("dpi", 300))
    return _render_sendfile(builder)


@figures_bp.route("/palettes", methods=["GET"])
def palettes():
    """List the available journal palettes."""
    try:
        from q1_figures.palettes import JournalPalettes
        names = JournalPalettes.all_names()
        return jsonify({"palettes": list(names)})
    except Exception as exc:
        logger.exception("/api/figures/palettes failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502
