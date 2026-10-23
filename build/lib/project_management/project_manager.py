"""High-level project management for the Academic Research Suite.

Wraps the SQLAlchemy :class:`database.models.ProjectModel` row in a plain
dataclass (:class:`Project`) that the UI layer can manipulate without
touching SQLAlchemy directly, and exposes :class:`ProjectManager` for
lifecycle / membership operations.

Qt signals are exposed via a thin :class:`SignalHub` that tries PyQt5
first and falls back to PySide2 via :mod:`qtpy`. When no Qt binding is
available, ``SignalHub`` becomes a no-op shim so the rest of the module
remains importable in headless environments.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database.connection import DatabaseConnection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qt signal shim — abstracts PyQt5 / PySide2 via qtpy.
# ---------------------------------------------------------------------------
def _make_signal_hub() -> Any:
    """Build a Qt signals hub if any Qt binding is importable.

    Returns ``None`` (after logging a one-shot info message) when no Qt
    binding is available — in that case callers must check for ``None``
    before emitting.
    """
    try:
        from qtpy.QtCore import QObject, Signal  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.info("qtpy/Qt unavailable — ProjectManager signals disabled. (%s)", exc)
        return None

    class _SignalHub(QObject):  # type: ignore[misc]
        """Qt signals emitted by :class:`ProjectManager`."""

        project_created = Signal(int)   # project_id
        project_updated = Signal(int)   # project_id
        project_deleted = Signal(int)   # project_id (already deleted)

    return _SignalHub()


# ---------------------------------------------------------------------------
# Plain-dataclass view of a Project (UI-facing).
# ---------------------------------------------------------------------------
@dataclass
class Project:
    """Plain-dataclass view of a :class:`database.models.ProjectModel`.

    The UI layer manipulates these rather than SQLAlchemy instances to
    avoid accidental detached-instance errors.
    """

    id: Optional[int] = None
    name: str = ""
    description: str = ""
    color: str = "#3B82F6"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    paper_ids: List[int] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model(cls, model: Any) -> "Project":
        """Build a :class:`Project` from a :class:`ProjectModel` row."""
        return cls(
            id=model.id,
            name=model.name,
            description=model.description or "",
            color=model.color or "#3B82F6",
            created_at=model.created_at,
            updated_at=model.updated_at,
            paper_ids=[p.id for p in (model.papers or [])],
            settings=dict(model.settings or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "paper_ids": list(self.paper_ids),
            "settings": dict(self.settings),
        }


# ---------------------------------------------------------------------------
# ProjectManager
# ---------------------------------------------------------------------------
class ProjectManager:
    """CRUD + membership ops for research projects.

    All mutations are persisted via the shared
    :class:`database.connection.DatabaseConnection` singleton. Optional Qt
    signals are emitted on the ``SignalHub`` (when Qt is importable).
    """

    def __init__(self, db: Optional[DatabaseConnection] = None) -> None:
        """Initialise the manager.

        Args:
            db: Optional :class:`DatabaseConnection`. If ``None``, the
                default singleton is used.
        """
        self.db: DatabaseConnection = db or DatabaseConnection()
        # Lazily-created signals hub. May be ``None`` in headless mode.
        self._signal_hub: Any = _make_signal_hub()

    # ------------------------------------------------------------------
    # Signal helpers
    # ------------------------------------------------------------------
    @property
    def signals(self) -> Any:
        """Return the :class:`SignalHub` (or ``None`` in headless mode)."""
        return self._signal_hub

    def _emit(self, name: str, project_id: int) -> None:
        """Emit a Qt signal if a signal hub is available."""
        hub = self._signal_hub
        if hub is None:
            return
        try:
            sig = getattr(hub, name)
            sig.emit(project_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to emit %s: %s", name, exc)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create_project(self, name: str, description: str = "",
                       color: str = "#3B82F6",
                       settings: Optional[Dict[str, Any]] = None) -> Project:
        """Create a new project and persist it.

        Args:
            name: Project name (must be unique).
            description: Optional longer description.
            color: Hex color string for UI badges.
            settings: Optional arbitrary settings dict.

        Returns:
            The freshly created :class:`Project`.

        Raises:
            ValueError: If ``name`` is empty.
        """
        if not name or not name.strip():
            raise ValueError("Project name cannot be empty.")
        from database.models import ProjectModel
        with self.db.get_db() as session:
            existing = session.query(ProjectModel).filter_by(name=name).first()
            if existing is not None:
                raise ValueError(f"A project named {name!r} already exists.")
            model = ProjectModel(
                name=name.strip(),
                description=description,
                color=color,
                settings=settings or {},
            )
            session.add(model)
            session.flush()
            project = Project.from_model(model)
            project_id = model.id
        self._emit("project_created", project_id)
        logger.info("Created project %r (id=%s).", name, project_id)
        return project

    def delete_project(self, project_id: int) -> bool:
        """Delete a project (cascades to paper associations + snapshots).

        Returns:
            ``True`` if the project was found and deleted, ``False`` if no
            project with the given id existed.
        """
        from database.models import ProjectModel
        with self.db.get_db() as session:
            model = session.get(ProjectModel, project_id)
            if model is None:
                logger.warning("delete_project: id=%s not found.", project_id)
                return False
            session.delete(model)
        self._emit("project_deleted", project_id)
        logger.info("Deleted project id=%s.", project_id)
        return True

    def rename_project(self, project_id: int, new_name: str) -> Project:
        """Rename a project.

        Args:
            project_id: Existing project id.
            new_name: New name (must be unique).

        Returns:
            The updated :class:`Project`.

        Raises:
            ValueError: If ``new_name`` is empty or already taken.
        """
        if not new_name or not new_name.strip():
            raise ValueError("Project name cannot be empty.")
        from database.models import ProjectModel
        with self.db.get_db() as session:
            clash = session.query(ProjectModel).filter(
                ProjectModel.name == new_name.strip(),
                ProjectModel.id != project_id,
            ).first()
            if clash is not None:
                raise ValueError(f"Name {new_name!r} is already taken.")
            model = session.get(ProjectModel, project_id)
            if model is None:
                raise KeyError(f"Project id={project_id} not found.")
            model.name = new_name.strip()
            session.flush()
            project = Project.from_model(model)
        self._emit("project_updated", project_id)
        return project

    def list_projects(self, query: Optional[str] = None) -> List[Project]:
        """Return all projects, most-recently-updated first.

        Args:
            query: Optional case-insensitive substring filter applied to
                the project ``name`` / ``description``. When ``None`` or
                empty, all projects are returned.
        """
        from database.models import ProjectModel
        session = self.db.get_session()
        try:
            q = session.query(ProjectModel).order_by(
                ProjectModel.updated_at.desc(),
            )
            if query:
                like = f"%{query.strip()}%"
                q = q.filter(
                    (ProjectModel.name.ilike(like))
                    | (ProjectModel.description.ilike(like))
                )
            rows = q.all()
            return [Project.from_model(r) for r in rows]
        finally:
            self.db._session_factory.remove()

    def update_project(self, project_id: int,
                       payload: Dict[str, Any]) -> Optional[Project]:
        """Apply a partial update to a project from a dict payload.

        Recognised keys: ``name``, ``description``, ``color``,
        ``settings``. Unknown keys are ignored.

        Args:
            project_id: Existing project id.
            payload: Dict of fields to set.

        Returns:
            The updated :class:`Project`, or ``None`` if the project
            does not exist.
        """
        from database.models import ProjectModel
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        with self.db.get_db() as session:
            model = session.get(ProjectModel, project_id)
            if model is None:
                return None
            if "name" in payload and payload["name"]:
                new_name = str(payload["name"]).strip()
                clash = session.query(ProjectModel).filter(
                    ProjectModel.name == new_name,
                    ProjectModel.id != project_id,
                ).first()
                if clash is not None:
                    raise ValueError(f"Name {new_name!r} is already taken.")
                model.name = new_name
            if "description" in payload:
                model.description = str(payload.get("description") or "")
            if "color" in payload and payload["color"]:
                model.color = str(payload["color"])
            if "settings" in payload and payload["settings"] is not None:
                model.settings = dict(payload["settings"])
            session.flush()
            project = Project.from_model(model)
        self._emit("project_updated", project_id)
        return project

    def get_project(self, project_id: int) -> Project:
        """Return a single :class:`Project` by id.

        Raises:
            KeyError: If the project does not exist.
        """
        from database.models import ProjectModel
        session = self.db.get_session()
        try:
            model = session.get(ProjectModel, project_id)
            if model is None:
                raise KeyError(f"Project id={project_id} not found.")
            return Project.from_model(model)
        finally:
            self.db._session_factory.remove()

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------
    def add_papers(self, project_id: int, paper_ids: List[int]) -> None:
        """Attach papers to a project (idempotent — duplicates are ignored)."""
        from database.models import ProjectModel, PaperModel
        if not paper_ids:
            return
        with self.db.get_db() as session:
            project = session.get(ProjectModel, project_id)
            if project is None:
                raise KeyError(f"Project id={project_id} not found.")
            existing = {p.id for p in project.papers}
            new_ids = [pid for pid in paper_ids if pid not in existing]
            if not new_ids:
                return
            papers = session.query(PaperModel).filter(
                PaperModel.id.in_(new_ids),
            ).all()
            found = {p.id for p in papers}
            missing = set(new_ids) - found
            if missing:
                logger.warning(
                    "add_papers: skipping missing paper ids %s.", sorted(missing),
                )
            for p in papers:
                project.papers.append(p)
            session.flush()
        self._emit("project_updated", project_id)
        logger.info("Added %d paper(s) to project id=%s.", len(papers), project_id)

    def remove_papers(self, project_id: int, paper_ids: List[int]) -> None:
        """Detach papers from a project (idempotent)."""
        from database.models import ProjectModel, PaperModel
        if not paper_ids:
            return
        with self.db.get_db() as session:
            project = session.get(ProjectModel, project_id)
            if project is None:
                raise KeyError(f"Project id={project_id} not found.")
            to_remove = [p for p in project.papers if p.id in set(paper_ids)]
            for p in to_remove:
                project.papers.remove(p)
            session.flush()
        self._emit("project_updated", project_id)
        logger.info("Removed %d paper(s) from project id=%s.",
                    len(to_remove), project_id)

    def get_papers(self, project_id: int) -> List[Any]:
        """Return the :class:`PaperModel` instances attached to a project."""
        from database.models import ProjectModel
        session = self.db.get_session()
        try:
            project = session.get(ProjectModel, project_id)
            if project is None:
                raise KeyError(f"Project id={project_id} not found.")
            return list(project.papers)
        finally:
            self.db._session_factory.remove()

    # ------------------------------------------------------------------
    # Membership aliases (used by the web routes and the desktop UI).
    # ------------------------------------------------------------------
    def add_papers_to_project(self, project_id: int,
                              paper_ids: List[int]) -> int:
        """Alias for :meth:`add_papers` that returns the count of newly
        attached papers (used by the REST ``/api/projects/<id>/papers``
        POST handler).
        """
        from database.models import ProjectModel, PaperModel
        if not paper_ids:
            return 0
        added = 0
        with self.db.get_db() as session:
            project = session.get(ProjectModel, project_id)
            if project is None:
                raise KeyError(f"Project id={project_id} not found.")
            existing = {p.id for p in project.papers}
            new_ids = [pid for pid in paper_ids if pid not in existing]
            if not new_ids:
                return 0
            papers = session.query(PaperModel).filter(
                PaperModel.id.in_(new_ids),
            ).all()
            for p in papers:
                project.papers.append(p)
                added += 1
            session.flush()
        self._emit("project_updated", project_id)
        logger.info("Attached %d paper(s) to project id=%s.", added, project_id)
        return added

    def remove_paper_from_project(self, project_id: int,
                                  paper_id: int) -> bool:
        """Detach a single paper from a project.

        Returns:
            ``True`` if the paper was attached and has been removed,
            ``False`` otherwise.
        """
        from database.models import ProjectModel
        with self.db.get_db() as session:
            project = session.get(ProjectModel, project_id)
            if project is None:
                return False
            for p in list(project.papers):
                if p.id == paper_id:
                    project.papers.remove(p)
                    session.flush()
                    self._emit("project_updated", project_id)
                    return True
        return False

    # ------------------------------------------------------------------
    # Snapshot / comparison delegates (lazy import to avoid cycles).
    # ------------------------------------------------------------------
    def _snapshot_manager(self):
        """Return a lazily-instantiated :class:`SnapshotManager`."""
        from project_management.snapshots import SnapshotManager
        return SnapshotManager(self.db)

    def list_snapshots(self, project_id: int) -> List[Any]:
        """Return all snapshots for a project (delegates to
        :class:`project_management.snapshots.SnapshotManager`).
        """
        return self._snapshot_manager().list_snapshots(project_id)

    def create_snapshot(self, project_id: int,
                       payload: Any) -> Any:
        """Create a project snapshot from a dict payload.

        ``payload`` may be a dict with ``name``/``description`` keys, a
        plain ``str`` (treated as the snapshot name), or ``None``
        (auto-generated name).
        """
        if isinstance(payload, dict):
            name = payload.get("name") or payload.get("label") or "Snapshot"
            description = payload.get("description")
        elif isinstance(payload, str) and payload.strip():
            name = payload.strip()
            description = None
        else:
            name = "Snapshot"
            description = None
        return self._snapshot_manager().create_snapshot(
            project_id, name, description,
        )

    def compare_projects(self, project_a_id: int,
                         project_b_id: int) -> Any:
        """Compare two projects (delegates to
        :class:`project_management.comparison.ProjectComparison`).
        """
        from project_management.comparison import ProjectComparison
        return ProjectComparison(self.db).compare(project_a_id, project_b_id)

    # ------------------------------------------------------------------
    # Cross-project search
    # ------------------------------------------------------------------
    def search_across_projects(self, query: str) -> Dict[int, List[Any]]:
        """Run a free-text search across every project.

        Args:
            query: Free-text search string.

        Returns:
            Dict mapping ``project_id`` -> list of matching
            :class:`PaperModel` instances.
        """
        from database.search import FullTextSearch
        fts = FullTextSearch(self.db)
        hits = fts.search(query, limit=200)
        # Group hits by the projects they belong to.
        hit_ids = {p.id for p in hits}
        if not hit_ids:
            return {}
        out: Dict[int, List[Any]] = {}
        for project in self.list_projects():
            session = self.db.get_session()
            try:
                from database.models import PaperModel
                papers = session.query(PaperModel).filter(
                    PaperModel.id.in_(hit_ids),
                    PaperModel.projects.any(id=project.id),
                ).all()
                if papers:
                    out[project.id] = papers
            finally:
                self.db._session_factory.remove()
        return out


__all__ = ["Project", "ProjectManager"]
