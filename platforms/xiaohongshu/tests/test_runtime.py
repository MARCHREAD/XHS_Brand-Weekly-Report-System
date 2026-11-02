import asyncio
import threading
import time
from pathlib import Path

from collector.config import Settings
from collector.runtime import AsyncTTLCache, SessionPool


def test_session_pool_runs_one_operation_per_worker(tmp_path: Path) -> None:
    settings = Settings(cookie_file=tmp_path / "missing", worker_count=2)
    clients = [object(), object()]
    pool = SessionPool(settings, clients)  # type: ignore[arg-type]
    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def work(client):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.04)
        with lock:
            state["active"] -= 1
        return id(client)

    async def scenario() -> None:
        results = await asyncio.gather(*(pool.run(work) for _ in range(6)))
        assert len({result.worker_id for result in results}) == 2
        snapshot = await pool.snapshot()
        assert snapshot["completed"] == 6
        assert snapshot["peak_active"] == 2

    asyncio.run(scenario())
    assert state["peak"] == 2


def test_cache_singleflight_and_hit(tmp_path: Path) -> None:
    cache = AsyncTTLCache()
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.03)
        return {"value": 7}

    async def scenario() -> None:
        results = await asyncio.gather(*(cache.get_or_create("same", 30, factory) for _ in range(10)))
        assert all(result[0] == {"value": 7} for result in results)
        assert sum(result[1] == "cache_miss" for result in results) == 1
        assert sum(result[1] == "singleflight" for result in results) == 9
        cached, status = await cache.get_or_create("same", 30, factory)
        assert cached == {"value": 7}
        assert status == "cache_hit"

    asyncio.run(scenario())
    assert calls == 1

