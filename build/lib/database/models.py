"""SQLAlchemy 2.0 declarative models for the Academic Research Suite.

Defines the canonical schema for papers, authors, keywords, fields of study,
citation references, projects, snapshots, proxies, vector embeddings and
query history. Every model exposes ``to_dict()`` / ``from_dict()`` helpers
so it can be serialised to JSON or REST payloads without external marshallers.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:  # Heavy / optional dep — keep module importable even when SQLAlchemy missing.
    from sqlalchemy import (
        Column,
        Integer,
        String,
        Text,
        DateTime,
        ForeignKey,
        Table,
        LargeBinary,
        Index,
        UniqueConstraint,
    )
    from sqlalchemy.orm import (
        DeclarativeBase,
        relationship,
        Mapped,
        mapped_column,
    )
    from sqlalchemy import JSON
    _HAS_SQLALCHEMY = True
except Exception as exc:  # pragma: no cover - import guard
    _HAS_SQLALCHEMY = False
    _IMPORT_ERROR: Optional[Exception] = exc
    logging.getLogger(__name__).warning(
        "SQLAlchemy unavailable — models.py operating in stub mode: %s", exc,
    )

logger = logging.getLogger(__name__)


def _ensure_sqlalchemy() -> None:
    """Raise an informative error if SQLAlchemy is missing at runtime.

    This lets the module be imported in environments without SQLAlchemy
    (e.g. documentation builds) while still failing loudly if a caller
    actually tries to use the ORM.
    """
    if not _HAS_SQLALCHEMY:
        raise ImportError(
            "SQLAlchemy is required for database.models but could not be "
            f"imported: {_IMPORT_ERROR!r}. Install it via "
            "`pip install SQLAlchemy>=2.0`."
        )


# ---------------------------------------------------------------------------
# Declarative base — created lazily so the module imports cleanly even when
# SQLAlchemy is not installed (the heavy dep is only needed at runtime).
# ---------------------------------------------------------------------------
if _HAS_SQLALCHEMY:

    class Base(DeclarativeBase):
        """Project-wide declarative base for SQLAlchemy 2.0 models."""

        type_annotation_map = {Dict[str, Any]: JSON, List[int]: JSON}

else:  # pragma: no cover - stub base for import-only environments

    class Base:  # type: ignore[no-redef]
        """Stub base — install SQLAlchemy to enable ORM functionality."""

        metadata = None


# ---------------------------------------------------------------------------
# Association table: papers <-> projects (many-to-many).
# ---------------------------------------------------------------------------
if _HAS_SQLALCHEMY:
    paper_project_assoc = Table(
        "paper_project_assoc",
        Base.metadata,
        Column("paper_id", Integer, ForeignKey("papers.id", ondelete="CASCADE"),
               primary_key=True),
        Column("project_id", Integer, ForeignKey("projects.id", ondelete="CASCADE"),
               primary_key=True),
        Column("added_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        Column("notes", Text, nullable=True),
    )

    paper_author_assoc = Table(
        "paper_author_assoc",
        Base.metadata,
        Column("paper_id", Integer, ForeignKey("papers.id", ondelete="CASCADE"),
               primary_key=True),
        Column("author_id", Integer, ForeignKey("authors.id", ondelete="CASCADE"),
               primary_key=True),
        Column("author_order", Integer, default=0),
    )

    paper_keyword_assoc = Table(
        "paper_keyword_assoc",
        Base.metadata,
        Column("paper_id", Integer, ForeignKey("papers.id", ondelete="CASCADE"),
               primary_key=True),
        Column("keyword_id", Integer, ForeignKey("keywords.id", ondelete="CASCADE"),
               primary_key=True),
    )

    paper_field_assoc = Table(
        "paper_field_assoc",
        Base.metadata,
        Column("paper_id", Integer, ForeignKey("papers.id", ondelete="CASCADE"),
               primary_key=True),
        Column("field_id", Integer, ForeignKey("fields_of_study.id", ondelete="CASCADE"),
               primary_key=True),
    )


def _utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Core ORM models.
# ---------------------------------------------------------------------------
if _HAS_SQLALCHEMY:

    class PaperModel(Base):
        """A single academic paper / publication."""

        __tablename__ = "papers"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        title: Mapped[str] = mapped_column(Text, nullable=False)
        abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
        doi: Mapped[Optional[str]] = mapped_column(String(255), unique=True,
                                                    nullable=True, index=True)
        url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True,
                                                       index=True)
        citations_count: Mapped[int] = mapped_column(Integer, default=0)
        publisher: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
        journal: Mapped[Optional[str]] = mapped_column(String(255), nullable=True,
                                                        index=True)
        volume: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        issue: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        pages: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        language: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
        paper_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow,
                                                     onupdate=_utcnow)

        # Relationships
        authors: Mapped[List["AuthorModel"]] = relationship(
            secondary=paper_author_assoc, back_populates="papers", lazy="selectin",
        )
        keywords: Mapped[List["KeywordModel"]] = relationship(
            secondary=paper_keyword_assoc, back_populates="papers", lazy="selectin",
        )
        fields_of_study: Mapped[List["FieldOfStudyModel"]] = relationship(
            secondary=paper_field_assoc, back_populates="papers", lazy="selectin",
        )
        references: Mapped[List["ReferenceModel"]] = relationship(
            primaryjoin="PaperModel.id==ReferenceModel.citing_paper_id",
            foreign_keys="ReferenceModel.citing_paper_id",
            cascade="all, delete-orphan", lazy="selectin",
        )
        projects: Mapped[List["ProjectModel"]] = relationship(
            secondary=paper_project_assoc, back_populates="papers", lazy="selectin",
        )

        __table_args__ = (
            Index("ix_papers_title", "title"),
        )

        def to_dict(self) -> Dict[str, Any]:
            """Serialise the paper to a plain dict (JSON-safe)."""
            return {
                "id": self.id,
                "title": self.title,
                "abstract": self.abstract,
                "year": self.year,
                "doi": self.doi,
                "url": self.url,
                "source": self.source,
                "citations_count": self.citations_count,
                "publisher": self.publisher,
                "journal": self.journal,
                "volume": self.volume,
                "issue": self.issue,
                "pages": self.pages,
                "language": self.language,
                "paper_type": self.paper_type,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "authors": [a.to_dict() for a in (self.authors or [])],
                "keywords": [k.to_dict() for k in (self.keywords or [])],
                "fields_of_study": [f.to_dict() for f in (self.fields_of_study or [])],
                "project_ids": [p.id for p in (self.projects or [])],
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "PaperModel":
            """Build a PaperModel from a dict (ignoring nested relations)."""
            ignore = {"authors", "keywords", "fields_of_study", "project_ids",
                      "references", "projects"}
            cols = {k: v for k, v in data.items() if k not in ignore}
            # created_at/updated_at may be ISO strings from JSON
            for ts_field in ("created_at", "updated_at"):
                v = cols.get(ts_field)
                if isinstance(v, str):
                    cols[ts_field] = datetime.fromisoformat(v)
            return cls(**cols)

        def __repr__(self) -> str:  # pragma: no cover - debug aid
            return f"<PaperModel id={self.id} title={self.title!r}>"

    class AuthorModel(Base):
        """An author of one or more papers."""

        __tablename__ = "authors"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
        orcid: Mapped[Optional[str]] = mapped_column(String(19), unique=True,
                                                      nullable=True)
        affiliation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

        papers: Mapped[List["PaperModel"]] = relationship(
            secondary=paper_author_assoc, back_populates="authors", lazy="selectin",
        )

        def to_dict(self) -> Dict[str, Any]:
            """Serialise the author to a plain dict."""
            return {
                "id": self.id,
                "name": self.name,
                "orcid": self.orcid,
                "affiliation": self.affiliation,
                "country": self.country,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "AuthorModel":
            """Build an AuthorModel from a dict."""
            cols = dict(data)
            v = cols.get("created_at")
            if isinstance(v, str):
                cols["created_at"] = datetime.fromisoformat(v)
            return cls(**cols)

        def __repr__(self) -> str:  # pragma: no cover
            return f"<AuthorModel id={self.id} name={self.name!r}>"

    class KeywordModel(Base):
        """A keyword / topic tag attached to papers."""

        __tablename__ = "keywords"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        term: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

        papers: Mapped[List["PaperModel"]] = relationship(
            secondary=paper_keyword_assoc, back_populates="keywords", lazy="selectin",
        )

        def to_dict(self) -> Dict[str, Any]:
            return {"id": self.id, "term": self.term}

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "KeywordModel":
            return cls(**{k: v for k, v in data.items() if k in {"id", "term"}})

    class FieldOfStudyModel(Base):
        """A high-level field of study (e.g. 'Computer Science')."""

        __tablename__ = "fields_of_study"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

        papers: Mapped[List["PaperModel"]] = relationship(
            secondary=paper_field_assoc, back_populates="fields_of_study",
            lazy="selectin",
        )

        def to_dict(self) -> Dict[str, Any]:
            return {"id": self.id, "name": self.name}

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "FieldOfStudyModel":
            return cls(**{k: v for k, v in data.items() if k in {"id", "name"}})

    class ReferenceModel(Base):
        """A single citation edge: ``citing_paper`` -> ``cited_doi``.

        Composite primary key so each edge is unique. ``cited_doi`` is a
        plain string (the cited paper may not be in our DB).
        """

        __tablename__ = "references"

        citing_paper_id: Mapped[int] = mapped_column(
            Integer, ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True,
        )
        cited_doi: Mapped[str] = mapped_column(String(255), primary_key=True,
                                                index=True)

        def to_dict(self) -> Dict[str, Any]:
            return {"citing_paper_id": self.citing_paper_id,
                    "cited_doi": self.cited_doi}

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "ReferenceModel":
            return cls(**{k: v for k, v in data.items()
                          if k in {"citing_paper_id", "cited_doi"}})

    class ProjectModel(Base):
        """A user-defined project grouping a set of papers."""

        __tablename__ = "projects"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
        description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow,
                                                     onupdate=_utcnow)
        color: Mapped[str] = mapped_column(String(32), default="#3B82F6")
        settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

        papers: Mapped[List["PaperModel"]] = relationship(
            secondary=paper_project_assoc, back_populates="projects", lazy="selectin",
        )
        snapshots: Mapped[List["SnapshotModel"]] = relationship(
            back_populates="project", cascade="all, delete-orphan", lazy="selectin",
        )

        def to_dict(self) -> Dict[str, Any]:
            return {
                "id": self.id,
                "name": self.name,
                "description": self.description,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "color": self.color,
                "settings": self.settings or {},
                "paper_ids": [p.id for p in (self.papers or [])],
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "ProjectModel":
            cols = dict(data)
            cols.pop("paper_ids", None)
            cols.pop("snapshots", None)
            for ts_field in ("created_at", "updated_at"):
                v = cols.get(ts_field)
                if isinstance(v, str):
                    cols[ts_field] = datetime.fromisoformat(v)
            if "settings" in cols and isinstance(cols["settings"], str):
                cols["settings"] = json.loads(cols["settings"])
            return cls(**cols)

    class PaperProjectAssoc(Base):
        """Explicit ORM view of the paper_project_assoc association table.

        Useful for direct queries that need to inspect the ``added_at`` or
        ``notes`` columns of the link itself.
        """

        __table__ = paper_project_assoc

        def to_dict(self) -> Dict[str, Any]:
            return {
                "paper_id": self.paper_id,
                "project_id": self.project_id,
                "added_at": self.added_at.isoformat() if self.added_at else None,
                "notes": self.notes,
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "PaperProjectAssoc":
            cols = dict(data)
            v = cols.get("added_at")
            if isinstance(v, str):
                cols["added_at"] = datetime.fromisoformat(v)
            return cls(**cols)

    class SnapshotModel(Base):
        """A point-in-time snapshot of a project's state."""

        __tablename__ = "snapshots"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        project_id: Mapped[int] = mapped_column(
            Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
            index=True,
        )
        name: Mapped[str] = mapped_column(String(255), nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
        snapshot_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

        project: Mapped["ProjectModel"] = relationship(back_populates="snapshots")

        def to_dict(self) -> Dict[str, Any]:
            return {
                "id": self.id,
                "project_id": self.project_id,
                "name": self.name,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "snapshot_data": self.snapshot_data or {},
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "SnapshotModel":
            cols = dict(data)
            v = cols.get("created_at")
            if isinstance(v, str):
                cols["created_at"] = datetime.fromisoformat(v)
            if "snapshot_data" in cols and isinstance(cols["snapshot_data"], str):
                cols["snapshot_data"] = json.loads(cols["snapshot_data"])
            return cls(**cols)

    class ProxyModel(Base):
        """A scraped / configured HTTP/HTTPS/SOCKS proxy with health stats."""

        __tablename__ = "proxies"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        host: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
        port: Mapped[int] = mapped_column(Integer, nullable=False)
        protocol: Mapped[str] = mapped_column(String(16), default="http")
        country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        anonymity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
        score: Mapped[float] = mapped_column(Integer, default=0)
        last_check: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
        success_count: Mapped[int] = mapped_column(Integer, default=0)
        fail_count: Mapped[int] = mapped_column(Integer, default=0)

        __table_args__ = (
            UniqueConstraint("host", "port", "protocol",
                             name="uq_proxy_host_port_protocol"),
        )

        def to_dict(self) -> Dict[str, Any]:
            return {
                "id": self.id,
                "host": self.host,
                "port": self.port,
                "protocol": self.protocol,
                "country": self.country,
                "anonymity": self.anonymity,
                "score": self.score,
                "last_check": self.last_check.isoformat() if self.last_check else None,
                "success_count": self.success_count,
                "fail_count": self.fail_count,
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "ProxyModel":
            cols = dict(data)
            v = cols.get("last_check")
            if isinstance(v, str):
                cols["last_check"] = datetime.fromisoformat(v)
            return cls(**cols)

    class EmbeddingModel(Base):
        """A single chunk embedding for a paper (RAG support)."""

        __tablename__ = "embeddings"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        paper_id: Mapped[int] = mapped_column(
            Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False,
            index=True,
        )
        model_name: Mapped[str] = mapped_column(String(128), nullable=False)
        chunk_idx: Mapped[int] = mapped_column(Integer, default=0)
        embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
        chunk_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

        def to_dict(self) -> Dict[str, Any]:
            return {
                "id": self.id,
                "paper_id": self.paper_id,
                "model_name": self.model_name,
                "chunk_idx": self.chunk_idx,
                "embedding_size": len(self.embedding) if self.embedding else 0,
                "chunk_text": self.chunk_text,
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "EmbeddingModel":
            # NOTE: ``embedding`` bytes must be supplied by the caller; if only
            # ``embedding_size`` is present (e.g. from to_dict) we leave it empty.
            cols = {k: v for k, v in data.items()
                    if k in {"id", "paper_id", "model_name", "chunk_idx",
                             "embedding", "chunk_text"}}
            return cls(**cols)

    class QueryHistoryModel(Base):
        """A user-issued search query, stored for analytics / re-runs."""

        __tablename__ = "query_history"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        query: Mapped[str] = mapped_column(Text, nullable=False)
        sources: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list)
        filters: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
        result_count: Mapped[int] = mapped_column(Integer, default=0)
        timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow,
                                                     index=True)

        def to_dict(self) -> Dict[str, Any]:
            return {
                "id": self.id,
                "query": self.query,
                "sources": self.sources or [],
                "filters": self.filters or {},
                "result_count": self.result_count,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            }

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "QueryHistoryModel":
            cols = dict(data)
            v = cols.get("timestamp")
            if isinstance(v, str):
                cols["timestamp"] = datetime.fromisoformat(v)
            for jf in ("sources", "filters"):
                if jf in cols and isinstance(cols[jf], str):
                    cols[jf] = json.loads(cols[jf])
            return cls(**cols)

else:  # pragma: no cover - stubs for import-only environments

    class PaperModel:  # type: ignore[no-redef]
        pass

    class AuthorModel:  # type: ignore[no-redef]
        pass

    class KeywordModel:  # type: ignore[no-redef]
        pass

    class FieldOfStudyModel:  # type: ignore[no-redef]
        pass

    class ReferenceModel:  # type: ignore[no-redef]
        pass

    class ProjectModel:  # type: ignore[no-redef]
        pass

    class PaperProjectAssoc:  # type: ignore[no-redef]
        pass

    class SnapshotModel:  # type: ignore[no-redef]
        pass

    class ProxyModel:  # type: ignore[no-redef]
        pass

    class EmbeddingModel:  # type: ignore[no-redef]
        pass

    class QueryHistoryModel:  # type: ignore[no-redef]
        pass


__all__ = [
    "Base",
    "PaperModel",
    "AuthorModel",
    "KeywordModel",
    "FieldOfStudyModel",
    "ReferenceModel",
    "ProjectModel",
    "PaperProjectAssoc",
    "SnapshotModel",
    "ProxyModel",
    "EmbeddingModel",
    "QueryHistoryModel",
    "paper_project_assoc",
    "paper_author_assoc",
    "paper_keyword_assoc",
    "paper_field_assoc",
]
