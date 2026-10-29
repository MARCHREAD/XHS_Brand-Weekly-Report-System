import asyncio
from pathlib import Path
import threading

from collector.config import Settings, parse_cookie_string
from collector.errors import XhsUpstreamError
from collector.sessions import SessionSupervisor


class FakeSessionClient:
    def __init__(self, cookie_string: str, *, outcome: str = "valid") -> None:
        self.cookies = parse_cookie_string(cookie_string)
        self.outcome = outcome

    def session_status(self):
        if self.outcome == "expired":
            raise XhsUpstreamError("no login", upstream_code=-100, auth_failure=True)
        if self.outcome == "network":
            raise XhsUpstreamError("timeout")
        return {"user_id": "fixture"}

    def effective_cookie_string(self) -> str:
        return "; ".join(f"{name}={value}" for name, value in self.cookies.items())


def test_supervisor_verifies_and_reports_redacted_session(tmp_path: Path) -> None:
    cookie_file = tmp_path / "secrets" / "xhs_cookie.txt"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text("a1=one; web_session=secret-value; webId=three", encoding="utf-8")
    supervisor = SessionSupervisor(
        Settings(cookie_file=cookie_file),
        client_factory=lambda value: FakeSessionClient(value),  # type: ignore[arg-type]
    )

    snapshot = asyncio.run(supervisor.verify_all())

    assert snapshot["state"] == "valid"
    assert snapshot["active"] == 1
    assert snapshot["sessions"][0]["last_verified_at"]
    assert "secret-value" not in str(snapshot)


def test_supervisor_excludes_server_rejected_session(tmp_path: Path) -> None:
    cookie_file = tmp_path / "xhs_cookie.txt"
    cookie_file.write_text("a1=one; web_session=two; webId=three", encoding="utf-8")
    supervisor = SessionSupervisor(
        Settings(cookie_file=cookie_file),
        client_factory=lambda value: FakeSessionClient(value, outcome="expired"),  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        snapshot = await supervisor.verify_all()
        clients, _ = await supervisor.active_clients()
        assert snapshot["state"] == "expired"
        assert snapshot["active"] == 0
        assert clients == []

    asyncio.run(scenario())


def test_supervisor_persists_rotated_cookie(tmp_path: Path) -> None:
    cookie_file = tmp_path / "xhs_cookie.txt"
    cookie_file.write_text("a1=one; web_session=old; webId=three", encoding="utf-8")
    clients: list[FakeSessionClient] = []

    def factory(value: str) -> FakeSessionClient:
        client = FakeSessionClient(value)
        client.cookies["web_session"] = "rotated"
        clients.append(client)
        return client

    supervisor = SessionSupervisor(
        Settings(cookie_file=cookie_file),
        client_factory=factory,  # type: ignore[arg-type]
    )

    snapshot = asyncio.run(supervisor.verify_all())

    assert snapshot["sessions"][0]["refreshed_at"]
    assert parse_cookie_string(cookie_file.read_text(encoding="utf-8"))["web_session"] == "rotated"


def test_reload_waits_for_inflight_verification(tmp_path: Path) -> None:
    cookie_file = tmp_path / "xhs_cookie.txt"
    cookie_file.write_text("a1=one; web_session=two; webId=three", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()

    class SlowSessionClient(FakeSessionClient):
        def session_status(self):
            entered.set()
            assert release.wait(timeout=2)
            return {"user_id": "fixture"}

    supervisor = SessionSupervisor(
        Settings(cookie_file=cookie_file),
        client_factory=lambda value: SlowSessionClient(value),  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        verification = asyncio.create_task(supervisor.verify_all())
        assert await asyncio.to_thread(entered.wait, 2)
        reload_task = asyncio.create_task(supervisor.reload())
        await asyncio.sleep(0)
        assert not reload_task.done()
        release.set()
        snapshot = await verification
        await reload_task
        assert snapshot["state"] == "valid"
        assert (await supervisor.snapshot())["state"] == "valid"

    asyncio.run(scenario())
