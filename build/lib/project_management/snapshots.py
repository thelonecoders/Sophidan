"""Project snapshots — point-in-time snapshots + diffing.

A :class:`Snapshot` captures the state of a project (its paper ids plus a
small metadata snapshot of every paper) at a given moment. Snapshots are
stored in the ``snapshots`` table as JSON blobs so they survive DB
restarts and can be exported alongside the project.

The :class:`SnapshotManager` supports:

* Creating named snapshots.
* Listing / deleting snapshots.
* Restoring a project to a previous snapshot (paper set is replaced).
* Comparing two snapshots (added / removed / changed).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from database.connection import DatabaseConnection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plain-dataclass views.
# ---------------------------------------------------------------------------
@dataclass
class Snapshot:
    """Plain-dataclass view of a :class:`database.models.SnapshotModel`.

    Attributes:
        id: Snapshot id (None until persisted).
        project_id: Owning project id.
        name: User-facing name.
        description: Optional longer description.
        created_at: Creation timestamp (UTC).
        paper_ids: Ordered list of paper ids captured at snapshot time.
        metadata_snapshot: Per-paper metadata (title, year, doi, ...).
    """

    id: Optional[int] = None
    project_id: Optional[int] = None
    name: str = ""
    description: str = ""
    created_at: Optional[datetime] = None
    paper_ids: List[int] = field(default_factory=list)
    metadata_snapshot: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model(cls, model: Any) -> "Snapshot":
        """Build a :class:`Snapshot` from a :class:`SnapshotModel` row."""
        data = dict(model.snapshot_data or {})
        return cls(
            id=model.id,
            project_id=model.project_id,
            name=model.name,
            description=data.get("description", "") or "",
            created_at=model.created_at,
            paper_ids=list(data.get("paper_ids", []) or []),
            metadata_snapshot=dict(data.get("metadata_snapshot", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "paper_ids": list(self.paper_ids),
            "metadata_snapshot": dict(self.metadata_snapshot),
        }


@dataclass
class SnapshotDiff:
    """Difference between two snapshots.

    Attributes:
        added_paper_ids: Paper ids present in B but not A.
        removed_paper_ids: Paper ids present in A but not B.
        changed_metadata: Paper ids whose captured metadata differs between
            A and B (with ``before`` and ``after`` dicts per id).
    """

    added_paper_ids: List[int] = field(default_factory=list)
    removed_paper_ids: List[int] = field(default_factory=list)
    changed_metadata: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "added_paper_ids": list(self.added_paper_ids),
            "removed_paper_ids": list(self.removed_paper_ids),
            "changed_metadata": {
                str(k): dict(v) for k, v in self.changed_metadata.items()
            },
        }

    def summary(self) -> str:
        """Return a one-line human summary of the diff."""
        return (
            f"+{len(self.added_paper_ids)} added, "
            f"-{len(self.removed_paper_ids)} removed, "
            f"~{len(self.changed_metadata)} changed"
        )


# ---------------------------------------------------------------------------
# Manager.
# ---------------------------------------------------------------------------
class SnapshotManager:
    """Create, list, restore and diff project snapshots."""

    def __init__(self, db: Optional[DatabaseConnection] = None) -> None:
        """Initialise the manager.

        Args:
            db: Optional :class:`DatabaseConnection`. Defaults to the
                singleton.
        """
        self.db: DatabaseConnection = db or DatabaseConnection()

    # ------------------------------------------------------------------
    # Snapshot creation
    # ------------------------------------------------------------------
    def create_snapshot(self, project_id: int, name: str,
                        description: Optional[str] = None) -> Snapshot:
        """Capture the current state of a project as a named snapshot.

        Args:
            project_id: Project to snapshot.
            name: Snapshot name (need not be unique).
            description: Optional longer description.

        Returns:
            The freshly-created :class:`Snapshot`.

        Raises:
            KeyError: If the project does not exist.
        """
        from database.models import ProjectModel, SnapshotModel
        with self.db.get_db() as session:
            project = session.get(ProjectModel, project_id)
            if project is None:
                raise KeyError(f"Project id={project_id} not found.")
            paper_ids = [p.id for p in project.papers]
            meta_snapshot: Dict[str, Any] = {}
            for p in project.papers:
                meta_snapshot[str(p.id)] = {
                    "title": p.title,
                    "year": p.year,
                    "doi": p.doi,
                    "source": p.source,
                    "journal": p.journal,
                    "citations_count": p.citations_count,
                }
            model = SnapshotModel(
                project_id=project_id,
                name=name,
                snapshot_data={
                    "description": description or "",
                    "paper_ids": paper_ids,
                    "metadata_snapshot": meta_snapshot,
                },
            )
            session.add(model)
            session.flush()
            snapshot = Snapshot.from_model(model)
            snap_id = model.id
        logger.info("Created snapshot %r (id=%s) of project id=%s (%d papers).",
                    name, snap_id, project_id, len(paper_ids))
        return snapshot

    def list_snapshots(self, project_id: int) -> List[Snapshot]:
        """List all snapshots of a project, newest first."""
        from database.models import SnapshotModel
        session = self.db.get_session()
        try:
            rows = session.query(SnapshotModel).filter(
                SnapshotModel.project_id == project_id,
            ).order_by(SnapshotModel.created_at.desc()).all()
            return [Snapshot.from_model(r) for r in rows]
        finally:
            self.db._session_factory.remove()

    def delete_snapshot(self, snapshot_id: int) -> None:
        """Delete a snapshot by id."""
        from database.models import SnapshotModel
        with self.db.get_db() as session:
            model = session.get(SnapshotModel, snapshot_id)
            if model is None:
                logger.warning("delete_snapshot: id=%s not found.", snapshot_id)
                return
            session.delete(model)
        logger.info("Deleted snapshot id=%s.", snapshot_id)

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------
    def restore_snapshot(self, snapshot_id: int) -> Snapshot:
        """Restore a project's paper set to the snapshot's state.

        Replaces the project's current ``papers`` collection with the
        snapshot's ``paper_ids``. Papers that no longer exist in the DB are
        silently skipped (the snapshot itself is not modified).

        Args:
            snapshot_id: Snapshot to restore.

        Returns:
            The :class:`Snapshot` that was restored.

        Raises:
            KeyError: If the snapshot (or its project) no longer exists.
        """
        from database.models import SnapshotModel, ProjectModel, PaperModel
        with self.db.get_db() as session:
            snap = session.get(SnapshotModel, snapshot_id)
            if snap is None:
                raise KeyError(f"Snapshot id={snapshot_id} not found.")
            project = session.get(ProjectModel, snap.project_id)
            if project is None:
                raise KeyError(
                    f"Project id={snap.project_id} (snapshot={snapshot_id}) no "
                    "longer exists.",
                )
            target_ids = list((snap.snapshot_data or {}).get("paper_ids", []) or [])
            if not target_ids:
                project.papers = []
            else:
                papers = session.query(PaperModel).filter(
                    PaperModel.id.in_(target_ids),
                ).all()
                project.papers = papers
                missing = set(target_ids) - {p.id for p in papers}
                if missing:
                    logger.warning(
                        "restore_snapshot: %d paper(s) in snapshot no longer "
                        "exist; skipped: %s", len(missing), sorted(missing),
                    )
            view = Snapshot.from_model(snap)
        logger.info("Restored snapshot id=%s into project id=%s (%d papers).",
                    snapshot_id, view.project_id, len(view.paper_ids))
        return view

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def compare_snapshots(self, snap_a_id: int, snap_b_id: int) -> SnapshotDiff:
        """Compute the diff between two snapshots.

        ``A`` is treated as the *before* state and ``B`` as the *after*
        state, so added = B - A and removed = A - B.

        Args:
            snap_a_id: First ("before") snapshot id.
            snap_b_id: Second ("after") snapshot id.

        Returns:
            A :class:`SnapshotDiff`.

        Raises:
            KeyError: If either snapshot does not exist.
        """
        from database.models import SnapshotModel
        session = self.db.get_session()
        try:
            a = session.get(SnapshotModel, snap_a_id)
            if a is None:
                raise KeyError(f"Snapshot id={snap_a_id} not found.")
            b = session.get(SnapshotModel, snap_b_id)
            if b is None:
                raise KeyError(f"Snapshot id={snap_b_id} not found.")
            a_ids: Set[int] = set(
                (a.snapshot_data or {}).get("paper_ids", []) or [],
            )
            b_ids: Set[int] = set(
                (b.snapshot_data or {}).get("paper_ids", []) or [],
            )
            added = sorted(b_ids - a_ids)
            removed = sorted(a_ids - b_ids)
            common = a_ids & b_ids
            a_meta = (a.snapshot_data or {}).get("metadata_snapshot", {}) or {}
            b_meta = (b.snapshot_data or {}).get("metadata_snapshot", {}) or {}
            changed: Dict[int, Dict[str, Any]] = {}
            for pid in common:
                before = a_meta.get(str(pid), {}) or {}
                after = b_meta.get(str(pid), {}) or {}
                if before != after:
                    changed[pid] = {"before": before, "after": after}
            return SnapshotDiff(
                added_paper_ids=added,
                removed_paper_ids=removed,
                changed_metadata=changed,
            )
        finally:
            self.db._session_factory.remove()


__all__ = ["Snapshot", "SnapshotDiff", "SnapshotManager"]
