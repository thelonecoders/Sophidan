"""Workspace state for the Academic Research Suite.

Represents the set of projects currently *open* in the UI (analogous to an
IDE workspace). Persists to ``data/workspace.json`` and supports zip-bundle
export / import that captures every open project and the papers it
references.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from database.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class Workspace:
    """Tracks which projects are currently open and which is active.

    The workspace state itself is persisted as a JSON file under
    ``data/workspace.json`` so it can survive process restarts. The actual
    project / paper rows live in SQLite; this class only tracks references
    to their ids plus a small amount of UI state.
    """

    DEFAULT_PATH = Path("data/workspace.json")
    EXPORT_MARKER = "ars_workspace.json"

    def __init__(self, db: Optional[DatabaseConnection] = None,
                 path: Optional[Path] = None) -> None:
        """Initialise the workspace, loading any persisted state.

        Args:
            db: Optional :class:`DatabaseConnection`. Defaults to the
                singleton.
            path: Path to the workspace JSON file. Defaults to
                :attr:`DEFAULT_PATH`.
        """
        self.db: DatabaseConnection = db or DatabaseConnection()
        self.path: Path = Path(path) if path else self.DEFAULT_PATH
        self.open_project_ids: List[int] = []
        self.active_project_id: Optional[int] = None
        self.recent_project_ids: List[int] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load the workspace JSON file (if it exists)."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load workspace from %s: %s", self.path, exc)
            return
        self.open_project_ids = list(data.get("open_project_ids", []))
        self.active_project_id = data.get("active_project_id")
        self.recent_project_ids = list(data.get("recent_project_ids", []))
        logger.debug("Workspace loaded: %d open, %d recent.",
                     len(self.open_project_ids), len(self.recent_project_ids))

    def save(self) -> None:
        """Persist the workspace JSON file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "open_project_ids": list(self.open_project_ids),
            "active_project_id": self.active_project_id,
            "recent_project_ids": list(self.recent_project_ids),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.debug("Workspace saved to %s.", self.path)

    # ------------------------------------------------------------------
    # Open / close / activate
    # ------------------------------------------------------------------
    def open_project(self, project_id: int) -> None:
        """Mark a project as open in the workspace.

        Raises:
            KeyError: If the project does not exist in the DB.
        """
        from database.models import ProjectModel
        session = self.db.get_session()
        try:
            model = session.get(ProjectModel, project_id)
            if model is None:
                raise KeyError(f"Project id={project_id} not found.")
        finally:
            self.db._session_factory.remove()
        if project_id not in self.open_project_ids:
            self.open_project_ids.append(project_id)
        # Update recents.
        if project_id in self.recent_project_ids:
            self.recent_project_ids.remove(project_id)
        self.recent_project_ids.insert(0, project_id)
        self.recent_project_ids = self.recent_project_ids[:50]
        if self.active_project_id is None:
            self.active_project_id = project_id
        self.save()
        logger.info("Opened project id=%s.", project_id)

    def close_project(self, project_id: int) -> None:
        """Mark a project as closed in the workspace."""
        if project_id in self.open_project_ids:
            self.open_project_ids.remove(project_id)
        if self.active_project_id == project_id:
            self.active_project_id = (
                self.open_project_ids[0] if self.open_project_ids else None
            )
        self.save()
        logger.info("Closed project id=%s.", project_id)

    def set_active(self, project_id: Optional[int]) -> None:
        """Set the active project (or ``None`` for no active project)."""
        if project_id is not None and project_id not in self.open_project_ids:
            raise ValueError(
                f"Project id={project_id} is not open — call open_project() first.",
            )
        self.active_project_id = project_id
        self.save()
        logger.info("Active project set to id=%s.", project_id)

    def recent_projects(self, n: int = 10) -> List[Any]:
        """Return the ``n`` most recently opened projects as ``Project`` views.

        Projects that no longer exist in the DB are silently skipped.
        """
        from project_management.project_manager import Project
        from database.models import ProjectModel
        session = self.db.get_session()
        try:
            out: List[Any] = []
            for pid in self.recent_project_ids[:n]:
                model = session.get(ProjectModel, pid)
                if model is None:
                    continue
                out.append(Project.from_model(model))
            return out
        finally:
            self.db._session_factory.remove()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def open_projects(self) -> List[Any]:
        """Return the currently-open projects as :class:`Project` views."""
        from project_management.project_manager import Project
        from database.models import ProjectModel
        session = self.db.get_session()
        try:
            out: List[Any] = []
            for pid in self.open_project_ids:
                model = session.get(ProjectModel, pid)
                if model is None:
                    continue
                out.append(Project.from_model(model))
            return out
        finally:
            self.db._session_factory.remove()

    # ------------------------------------------------------------------
    # Zip export / import
    # ------------------------------------------------------------------
    def export_workspace(self, path: Path | str) -> Path:
        """Bundle every open project + its papers into a single zip.

        The zip contains:

        * ``ars_workspace.json`` — the workspace state.
        * ``projects/<id>.json`` — one file per open project (settings +
          paper_ids).
        * ``papers/<id>.json`` — every paper referenced by any open project
          (deduplicated).

        Args:
            path: Destination zip file path.

        Returns:
            The resolved destination :class:`Path`.
        """
        from database.models import ProjectModel, PaperModel
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        session = self.db.get_session()
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                ws_payload: Dict[str, Any] = {
                    "open_project_ids": list(self.open_project_ids),
                    "active_project_id": self.active_project_id,
                    "recent_project_ids": list(self.recent_project_ids),
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "schema_version": 1,
                }
                zf.writestr(self.EXPORT_MARKER,
                            json.dumps(ws_payload, indent=2))
                paper_ids_seen: set = set()
                for pid in self.open_project_ids:
                    model = session.get(ProjectModel, pid)
                    if model is None:
                        continue
                    project_data = model.to_dict()
                    zf.writestr(f"projects/{pid}.json",
                                json.dumps(project_data, indent=2,
                                           default=str))
                    for paper in model.papers:
                        if paper.id in paper_ids_seen:
                            continue
                        paper_ids_seen.add(paper.id)
                        zf.writestr(f"papers/{paper.id}.json",
                                    json.dumps(paper.to_dict(), indent=2,
                                               default=str))
        finally:
            self.db._session_factory.remove()
        logger.info("Exported workspace to %s (%d papers).",
                    dest, len(paper_ids_seen))
        return dest

    def import_workspace(self, path: Path | str) -> None:
        """Restore workspace state from a zip produced by :meth:`export_workspace`.

        Re-creates the projects and papers in the current DB (upserts by
        ``doi`` for papers, by ``name`` for projects). Open projects are
        replaced with the imported set.

        Args:
            path: Source zip file path.
        """
        from database.models import (
            ProjectModel, PaperModel, AuthorModel, KeywordModel,
        )
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"Workspace zip not found: {src}")
        with zipfile.ZipFile(src, "r") as zf:
            names = zf.namelist()
            if self.EXPORT_MARKER not in names:
                raise ValueError(
                    f"Not an ARS workspace export: missing {self.EXPORT_MARKER}",
                )
            ws_payload = json.loads(zf.read(self.EXPORT_MARKER))
            paper_files = [n for n in names if n.startswith("papers/")
                           and n.endswith(".json")]
            project_files = [n for n in names if n.startswith("projects/")
                              and n.endswith(".json")]
            with self.db.get_db() as session:
                # Upsert papers first (by DOI).
                paper_id_map: Dict[int, int] = {}
                for fn in paper_files:
                    data = json.loads(zf.read(fn))
                    old_id = data.get("id")
                    doi = data.get("doi")
                    paper = None
                    if doi:
                        paper = session.query(PaperModel).filter_by(doi=doi).first()
                    if paper is None:
                        paper = PaperModel()
                        session.add(paper)
                    # Update columns.
                    for col in ("title", "abstract", "year", "doi", "url",
                                 "source", "citations_count", "publisher",
                                 "journal", "volume", "issue", "pages",
                                 "language", "paper_type"):
                        if col in data and data[col] is not None:
                            setattr(paper, col, data[col])
                    # Authors (upsert by name).
                    new_authors = []
                    for ad in data.get("authors", []):
                        nm = ad.get("name")
                        if not nm:
                            continue
                        au = session.query(AuthorModel).filter_by(name=nm).first()
                        if au is None:
                            au = AuthorModel(name=nm, orcid=ad.get("orcid"),
                                             affiliation=ad.get("affiliation"),
                                             country=ad.get("country"))
                            session.add(au)
                        new_authors.append(au)
                    paper.authors = new_authors
                    # Keywords (upsert by term).
                    new_kws = []
                    for kd in data.get("keywords", []):
                        term = kd.get("term")
                        if not term:
                            continue
                        kw = session.query(KeywordModel).filter_by(term=term).first()
                        if kw is None:
                            kw = KeywordModel(term=term)
                            session.add(kw)
                        new_kws.append(kw)
                    paper.keywords = new_kws
                    session.flush()
                    if old_id is not None:
                        paper_id_map[old_id] = paper.id
                # Upsert projects (by name).
                new_open_ids: List[int] = []
                for fn in project_files:
                    data = json.loads(zf.read(fn))
                    name = data.get("name")
                    if not name:
                        continue
                    project = session.query(ProjectModel).filter_by(name=name).first()
                    if project is None:
                        project = ProjectModel(name=name)
                        session.add(project)
                    project.description = data.get("description") or ""
                    project.color = data.get("color") or "#3B82F6"
                    project.settings = data.get("settings") or {}
                    # Resolve paper ids via the map.
                    target_paper_ids = [
                        paper_id_map.get(pid, pid)
                        for pid in data.get("paper_ids", [])
                    ]
                    target_papers = session.query(PaperModel).filter(
                        PaperModel.id.in_(target_paper_ids),
                    ).all() if target_paper_ids else []
                    project.papers = target_papers
                    session.flush()
                    new_open_ids.append(project.id)
                self.open_project_ids = new_open_ids
                self.active_project_id = ws_payload.get("active_project_id")
                self.recent_project_ids = list(
                    ws_payload.get("recent_project_ids", []),
                ) + new_open_ids
        self.save()
        logger.info("Imported workspace from %s (%d projects).",
                    src, len(new_open_ids))


__all__ = ["Workspace"]
