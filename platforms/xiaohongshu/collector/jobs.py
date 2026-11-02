from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .service import CollectorService


TERMINAL_EVENT_STATES = {"success", "cache_hit", "singleflight", "error"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_requests(options: dict[str, Any]) -> int:
    pages = int(options.get("pages", 1))
    notes = int(options.get("note_limit", 1))
    total = pages
    if options.get("include_details"):
        total += notes
    if options.get("include_authors"):
        total += notes
    if options.get("include_comments"):
        total += notes * int(options.get("comment_pages", 1))
    if options.get("use_gpt") and not options.get("include_details"):
        total += notes
    if options.get("save"):
        total += 1
    return max(1, total)


@dataclass(slots=True)
class CollectorJob:
    id: str
    options: dict[str, Any]
    expected_requests: int
    status: str = "queued"
    stage: str = "queued"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    created_monotonic: float = field(default_factory=time.monotonic)
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def add_event(self, event: dict[str, Any]) -> None:
        async with self._lock:
            existing = next((item for item in self.events if item.get("id") == event.get("id")), None)
            if existing is None:
                self.events.append(dict(event))
                if len(self.events) > 600:
                    self.events = self.events[-600:]
            else:
                existing.update(event)
            self.stage = str(event.get("stage") or self.stage)
            self.updated_at = _utc_now()

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            completed = sum(1 for event in self.events if event.get("status") in TERMINAL_EVENT_STATES)
            failed = sum(1 for event in self.events if event.get("status") == "error")
            running = sum(1 for event in self.events if event.get("status") == "running")
            total = max(self.expected_requests, completed)
            if self.status in {"completed", "failed", "cancelled"}:
                total = max(1, completed)
            return {
                "job_id": self.id,
                "status": self.status,
                "stage": self.stage,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "progress": {
                    "completed": completed,
                    "total": total,
                    "failed": failed,
                    "running": running,
                    "percent": 100 if self.status == "completed" else min(99, round(completed / total * 100)),
                },
                "events": [dict(event) for event in self.events],
                "result": self.result,
                "error": self.error,
            }


class CollectorJobManager:
    def __init__(self, retention_seconds: float = 3600.0) -> None:
        self.retention_seconds = retention_seconds
        self._jobs: dict[str, CollectorJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def create(self, service: CollectorService, options: dict[str, Any]) -> dict[str, Any]:
        await self._cleanup()
        job = CollectorJob(
            id=uuid4().hex,
            options=dict(options),
            expected_requests=estimate_requests(options),
        )
        async with self._lock:
            self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job, service))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return await job.snapshot()

    async def get(self, job_id: str) -> dict[str, Any]:
        async with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return await job.snapshot()

    async def _run(self, job: CollectorJob, service: CollectorService) -> None:
        job.status = "running"
        job.stage = "search"
        job.started_at = _utc_now()
        job.updated_at = job.started_at
        try:
            job.result = await service.collect_keyword(**job.options, trace=job.add_event)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.error = "Collector job was cancelled"
            raise
        except BaseException as exc:
            job.status = "failed"
            job.error = (str(exc) or exc.__class__.__name__)[:500]
        else:
            job.status = "completed"
            job.stage = "completed"
        finally:
            job.finished_at = _utc_now()
            job.updated_at = job.finished_at

    async def _cleanup(self) -> None:
        cutoff = time.monotonic() - self.retention_seconds
        async with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.created_monotonic < cutoff and job.status in {"completed", "failed", "cancelled"}
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)
