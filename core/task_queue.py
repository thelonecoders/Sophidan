"""Thread-pool task queue with structured futures.

This module exposes:

* :class:`TaskStatus` — enum for the lifecycle of a :class:`Task`.
* :class:`Task` — a dataclass capturing everything the orchestrator/UI needs
  to know about a piece of background work.
* :class:`TaskQueue` — a thin wrapper around
  :class:`concurrent.futures.ThreadPoolExecutor` providing :py:meth:`enqueue`,
  :py:meth:`wait_all`, :py:meth:`cancel`, :py:meth:`results`.

The queue is fully thread-safe and uses only the Python standard library, so
the module imports cleanly in any environment.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import enum
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------
class TaskStatus(enum.Enum):
    """Lifecycle states for a :class:`Task`."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------
@dataclass
class Task:
    """A unit of background work.

    Attributes:
        id: Unique identifier (auto-generated UUID4 hex string).
        name: Human-readable name (used in UI lists).
        callable: The function to execute.
        args: Positional arguments forwarded to ``callable``.
        kwargs: Keyword arguments forwarded to ``callable``.
        status: Current :class:`TaskStatus`.
        progress: Integer 0-100 progress percentage.
        result: Return value once completed.
        error: Exception instance on failure, else ``None``.
        started_at: Epoch seconds when the task started running.
        finished_at: Epoch seconds when the task reached a terminal state.
        future: The underlying :class:`concurrent.futures.Future` (if any).
    """

    name: str
    callable: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    result: Any = None
    error: Optional[BaseException] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    future: Optional[Future] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict (for UI / IPC)."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "result": repr(self.result) if self.result is not None else None,
            "error": repr(self.error) if self.error is not None else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------
class TaskQueue:
    """A thread-safe queue backed by a :class:`ThreadPoolExecutor`.

    Example:
        >>> q = TaskQueue(max_workers=4)
        >>> t = q.enqueue("compute", lambda x: x * 2, 21)
        >>> q.wait_all()
        >>> t.result
        42
    """

    def __init__(self, max_workers: int = 4) -> None:
        """Initialize the queue.

        Args:
            max_workers: Maximum number of worker threads.
        """
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="ars-task",
        )
        self._lock = threading.RLock()
        self._tasks: Dict[str, Task] = {}

    # ------------------------------------------------------------------ enqueue
    def enqueue(
        self,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Task:
        """Schedule ``fn`` for execution and return the associated :class:`Task`.

        Args:
            name: Human-readable task name.
            fn: The callable to run.
            *args: Positional arguments forwarded to ``fn``.
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            The :class:`Task` instance (already queued).
        """
        task = Task(name=name, callable=fn, args=args, kwargs=kwargs)
        future = self._executor.submit(self._run, task)
        task.future = future
        with self._lock:
            self._tasks[task.id] = task
        logger.info("Enqueued task %s (%s)", task.id, task.name)
        return task

    # ------------------------------------------------------------------ runner
    def _run(self, task: Task) -> Any:
        """Internal: actually execute the task and update its lifecycle."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        try:
            result = task.callable(*task.args, **task.kwargs)
        except Exception as exc:
            task.error = exc
            task.status = TaskStatus.FAILED
            task.finished_at = time.time()
            logger.error("Task %s (%s) failed: %s", task.id, task.name, exc)
            raise
        else:
            task.result = result
            task.progress = 100
            task.status = TaskStatus.COMPLETED
            task.finished_at = time.time()
            logger.info("Task %s (%s) completed", task.id, task.name)
            return result

    # ------------------------------------------------------------------ ops
    def cancel(self, task_id: str) -> bool:
        """Attempt to cancel a task.

        Tasks that have not started running yet are cancelled directly; tasks
        that are already running cannot be interrupted but are marked as
        ``CANCELLED`` once they finish (best-effort).

        Args:
            task_id: The :attr:`Task.id` to cancel.

        Returns:
            ``True`` if the task was cancelled before it started running.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.future is None:
                return False
            cancelled = task.future.cancel()
            if cancelled:
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
            return cancelled

    def wait_all(self, timeout: Optional[float] = None) -> None:
        """Block until every submitted task has reached a terminal state.

        Args:
            timeout: Maximum wait in seconds, or ``None`` for unbounded.
        """
        with self._lock:
            futures = [t.future for t in self._tasks.values() if t.future is not None]
        from concurrent.futures import wait, FIRST_EXCEPTION, ALL_COMPLETED

        wait(futures, timeout=timeout, return_when=ALL_COMPLETED)

    def results(self) -> Dict[str, Any]:
        """Return a mapping ``{task_id: result}`` for completed tasks."""
        with self._lock:
            return {
                tid: t.result
                for tid, t in self._tasks.items()
                if t.status == TaskStatus.COMPLETED
            }

    # ------------------------------------------------------------------ introspection
    def get(self, task_id: str) -> Optional[Task]:
        """Return the :class:`Task` for ``task_id``, or ``None``."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_all(self) -> List[Task]:
        """Return a snapshot list of every task ever submitted."""
        with self._lock:
            return list(self._tasks.values())

    def list_by_status(self, status: TaskStatus) -> List[Task]:
        """Return all tasks in a given status."""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == status]

    def list_active(self) -> List[Task]:
        """Return all tasks that are pending or currently running."""
        with self._lock:
            return [
                t
                for t in self._tasks.values()
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ]

    # ------------------------------------------------------------------ shutdown
    def shutdown(self, wait: bool = True) -> None:
        """Shut down the underlying executor.

        Args:
            wait: If ``True``, block until all running tasks finish.
        """
        try:
            self._executor.shutdown(wait=wait, cancel_futures=True)
        except TypeError:  # pragma: no cover - Python <3.9 fallback
            self._executor.shutdown(wait=wait)


__all__ = ["TaskStatus", "Task", "TaskQueue"]
