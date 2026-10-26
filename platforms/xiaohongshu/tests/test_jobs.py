import asyncio

from collector.jobs import CollectorJobManager


class FakeAsyncService:
    async def collect_keyword(self, *, trace, **options):
        event = {
            "id": "event-1",
            "stage": "search",
            "interface": "POST /search",
            "target": options["keyword"],
            "status": "running",
        }
        await trace(event)
        await asyncio.sleep(0.01)
        await trace({**event, "status": "success", "duration_ms": 10, "response": {"items": 2}})
        return {"keyword": options["keyword"], "count": 2, "items": []}


def test_background_job_updates_event_in_place() -> None:
    async def scenario() -> None:
        manager = CollectorJobManager()
        created = await manager.create(
            FakeAsyncService(),  # type: ignore[arg-type]
            {
                "keyword": "咖啡",
                "pages": 1,
                "note_limit": 2,
                "include_details": False,
                "include_authors": False,
                "include_comments": False,
                "comment_pages": 1,
                "use_gpt": False,
                "save": False,
            },
        )
        for _ in range(20):
            snapshot = await manager.get(created["job_id"])
            if snapshot["status"] == "completed":
                break
            await asyncio.sleep(0.01)
        assert snapshot["status"] == "completed"
        assert snapshot["progress"]["percent"] == 100
        assert len(snapshot["events"]) == 1
        assert snapshot["events"][0]["status"] == "success"
        assert snapshot["result"]["count"] == 2

    asyncio.run(scenario())
