from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .client import XhsClient
from .config import Settings


T = TypeVar("T")


@dataclass(slots=True)
class _CacheEntry(Generic[T]):
    expires_at: float
    value: T


@dataclass(slots=True)
class PoolRun(Generic[T]):
    value: T
    worker_id: int
    queue_wait_ms: int


class AsyncTTLCache:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._values: dict[str, _CacheEntry[Any]] = {}
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._coalesced = 0

    async def get_or_create(
        self,
        key: str,
        ttl_seconds: float,
        factory: Callable[[], Awaitable[T]],
    ) -> tuple[T, str]:
        if not self.enabled or ttl_seconds <= 0:
            return await factory(), "disabled"

        now = time.monotonic()
        leader = False
        async with self._lock:
            entry = self._values.get(key)
            if entry and entry.expires_at > now:
                self._hits += 1
                return copy.deepcopy(entry.value), "cache_hit"
            if entry:
                self._values.pop(key, None)

            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(factory())
                self._inflight[key] = task
                self._misses += 1
                leader = True
            else:
                self._coalesced += 1

        try:
            value = await asyncio.shield(task)
        except BaseException:
            if leader:
                async with self._lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)
            raise

        if leader:
            async with self._lock:
                self._values[key] = _CacheEntry(
                    expires_at=time.monotonic() + ttl_seconds,
                    value=copy.deepcopy(value),
                )
                if self._inflight.get(key) is task:
                    self._inflight.pop(key, None)
            cache_state = "cache_miss"
        else:
            cache_state = "singleflight"
        return copy.deepcopy(value), cache_state

    async def clear(self) -> None:
        async with self._lock:
            self._values.clear()

    async def snapshot(self) -> dict[str, int | bool]:
        async with self._lock:
            now = time.monotonic()
            expired = [key for key, entry in self._values.items() if entry.expires_at <= now]
            for key in expired:
                self._values.pop(key, None)
            return {
                "enabled": self.enabled,
                "entries": len(self._values),
                "inflight": len(self._inflight),
                "hits": self._hits,
                "misses": self._misses,
                "coalesced": self._coalesced,
            }


class SessionPool:
    """Async dispatcher over isolated, single-request XHS session workers."""

    def __init__(self, settings: Settings, clients: list[XhsClient] | None = None) -> None:
        self.settings = settings
        if clients is None:
            cookies = settings.cookie_strings()
            clients = [XhsClient(settings, cookie_string=value) for value in cookies]
        if not clients:
            raise ValueError("SessionPool requires at least one client")
        self.clients = clients[: settings.worker_count]
        self._queue: asyncio.Queue[tuple[int, XhsClient]] | None = None
        self._queue_init_lock = asyncio.Lock()
        self._metrics_lock = asyncio.Lock()
        self._active = 0
        self._queued = 0
        self._peak_active = 0
        self._completed = 0
        self._failed = 0

    async def _get_queue(self) -> asyncio.Queue[tuple[int, XhsClient]]:
        if self._queue is not None:
            return self._queue
        async with self._queue_init_lock:
            if self._queue is None:
                queue: asyncio.Queue[tuple[int, XhsClient]] = asyncio.Queue()
                for worker_id, client in enumerate(self.clients, start=1):
                    queue.put_nowait((worker_id, client))
                self._queue = queue
        return self._queue

    async def run(self, operation: Callable[[XhsClient], T]) -> PoolRun[T]:
        queue = await self._get_queue()
        queued_at = time.monotonic()
        async with self._metrics_lock:
            self._queued += 1
        worker_id, client = await queue.get()
        wait_ms = round((time.monotonic() - queued_at) * 1000)
        async with self._metrics_lock:
            self._queued -= 1
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
        try:
            value = await asyncio.to_thread(operation, client)
        except BaseException:
            async with self._metrics_lock:
                self._failed += 1
            raise
        else:
            async with self._metrics_lock:
                self._completed += 1
            return PoolRun(value=value, worker_id=worker_id, queue_wait_ms=wait_ms)
        finally:
            async with self._metrics_lock:
                self._active -= 1
            queue.put_nowait((worker_id, client))

    async def snapshot(self) -> dict[str, int]:
        async with self._metrics_lock:
            return {
                "configured_workers": self.settings.worker_count,
                "effective_workers": len(self.clients),
                "active": self._active,
                "queued": self._queued,
                "peak_active": self._peak_active,
                "completed": self._completed,
                "failed": self._failed,
            }
