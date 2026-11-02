import asyncio
import base64
from pathlib import Path

import pytest

from collector.auth import QrLoginManager, render_qr_data_uri
from collector.config import Settings, parse_cookie_string


class FakeQrClient:
    def __init__(self, cookie_string: str) -> None:
        self.initial = parse_cookie_string(cookie_string)
        self.status = 0
        self.cookie_issued = False

    def create_qr_login(self):
        return {"qr_id": "qr-fixture", "code": "123456", "url": "xhsdiscover://login?fixture=1"}

    def qr_login_status(self, qr_id: str, code: str):
        assert qr_id == "qr-fixture"
        assert code == "123456"
        return {"code_status": self.status}

    def merged_cookies(self):
        if self.status == 2 or self.cookie_issued:
            return {**self.initial, "web_session": "session-fixture"}
        return dict(self.initial)


def test_qr_image_is_local_png_data_uri() -> None:
    value = render_qr_data_uri("xhsdiscover://login?fixture=1")
    prefix = "data:image/png;base64,"
    assert value.startswith(prefix)
    assert base64.b64decode(value.removeprefix(prefix)).startswith(b"\x89PNG")


def test_qr_login_persists_complete_cookie(tmp_path: Path) -> None:
    clients: list[FakeQrClient] = []

    def factory(cookie_string: str) -> FakeQrClient:
        client = FakeQrClient(cookie_string)
        clients.append(client)
        return client

    cookie_file = tmp_path / "secrets" / "xhs_cookie.txt"
    manager = QrLoginManager(Settings(cookie_file=cookie_file), client_factory=factory)

    async def exercise() -> None:
        created = await manager.create()
        assert created["state"] == "waiting_scan"
        pending, cookie = await manager.poll(str(created["login_id"]))
        assert pending["state"] == "waiting_scan"
        assert cookie is None
        clients[0].status = 2
        completed, cookie = await manager.poll(str(created["login_id"]))
        assert completed["authenticated"] is True
        assert cookie is not None

    asyncio.run(exercise())
    stored = parse_cookie_string(cookie_file.read_text(encoding="utf-8"))
    assert {"a1", "webId", "web_session"} <= stored.keys()
    assert stored["web_session"] == "session-fixture"


def test_qr_login_accepts_complete_cookie_before_status_two(tmp_path: Path) -> None:
    clients: list[FakeQrClient] = []

    def factory(cookie_string: str) -> FakeQrClient:
        client = FakeQrClient(cookie_string)
        clients.append(client)
        return client

    cookie_file = tmp_path / "secrets" / "xhs_cookie.txt"
    manager = QrLoginManager(Settings(cookie_file=cookie_file), client_factory=factory)

    async def exercise() -> None:
        created = await manager.create()
        clients[0].cookie_issued = True
        completed, cookie = await manager.poll(str(created["login_id"]))
        assert completed["state"] == "authenticated"
        assert completed["code_status"] == 2
        assert cookie is not None

    asyncio.run(exercise())


class FakeVerificationClient(FakeQrClient):
    def __init__(self, cookie_string: str, verification_type: str = "124") -> None:
        super().__init__(cookie_string)
        self.qr_verification_type: str | None = verification_type
        self.verification_status = 1
        self.init_calls = 0
        self.login_polls = 0
        self.sms_send_calls = 0
        self.sms_checks: list[tuple[str, str, int]] = []

    def qr_login_status(self, qr_id, code):
        self.login_polls += 1
        if self.verification_status == 4:
            self.cookie_issued = True
            self.qr_verification_type = None
        return {"code_status": 0}

    def create_qr_verification(self):
        self.init_calls += 1
        return {"rid": "secret-rid"}

    def qr_verification_url(self, rid):
        assert rid == "secret-rid"
        return "https://www.xiaohongshu.com/web-login/qrcode-transfer?rid=fixture"

    def qr_verification_status(self, rid):
        assert rid == "secret-rid"
        return {"status": self.verification_status}

    def qr_web_verification_url(self):
        return "https://www.xiaohongshu.com/web-login/captcha?fixture=1"

    def init_sms_verification(self):
        return {"receiver": "138****0000"}

    def send_sms_verification(self):
        self.sms_send_calls += 1
        return {"rid": f"sms-rid-{self.sms_send_calls}", "expireSec": 60}

    def check_sms_verification(self, rid, code, check_count):
        self.sms_checks.append((rid, code, check_count))
        self.cookie_issued = True
        self.qr_verification_type = None
        return {}


@pytest.mark.parametrize("verification_type", ["124", "209"])
def test_second_scan_replays_original_session_and_persists_only_after_confirm(
    tmp_path: Path,
    verification_type: str,
) -> None:
    client = FakeVerificationClient("a1=one; webId=two", verification_type)
    cookie_file = tmp_path / "cookie"
    manager = QrLoginManager(Settings(cookie_file=cookie_file), client_factory=lambda _: client)

    async def exercise():
        login_id = (await manager.create())["login_id"]
        pending, cookie = await manager.poll(login_id)
        assert pending["state"] == "verification_waiting_scan" and cookie is None
        assert pending["verification_type"] == verification_type
        assert pending["qr_image"].startswith("data:image/png;base64,")
        assert "secret-rid" not in str(pending)
        client.verification_status = 2
        scanned, cookie = await manager.poll(login_id)
        assert scanned["state"] == "verification_scanned" and cookie is None
        assert not cookie_file.exists()
        assert client.login_polls == 1 and client.init_calls == 1
        client.verification_status = 4
        done, cookie = await manager.poll(login_id)
        assert done["authenticated"] is True and cookie
        assert client.login_polls == 2 and cookie_file.exists()

    asyncio.run(exercise())


def test_consecutive_qr_verification_challenges_are_supported(tmp_path: Path) -> None:
    client = FakeVerificationClient("a1=one; webId=two", "209")
    cookie_file = tmp_path / "cookie"
    manager = QrLoginManager(Settings(cookie_file=cookie_file), client_factory=lambda _: client)

    async def exercise():
        login_id = (await manager.create())["login_id"]
        first, _ = await manager.poll(login_id)
        assert first["verification_type"] == "209"

        client.verification_status = 4
        client.qr_login_status = lambda *_: {"code_status": 0}
        second, cookie = await manager.poll(login_id)
        assert second["state"] == "verification_waiting_scan"
        assert second["verification_type"] == "209"
        assert cookie is None
        assert client.init_calls == 2

    asyncio.run(exercise())


def test_sms_verification_runs_in_python_session_and_replays_login(tmp_path: Path) -> None:
    client = FakeVerificationClient("a1=one; webId=two", "120")
    cookie_file = tmp_path / "cookie"
    manager = QrLoginManager(Settings(cookie_file=cookie_file), client_factory=lambda _: client)

    async def exercise():
        login_id = (await manager.create())["login_id"]
        required, cookie = await manager.poll(login_id)
        assert required["state"] == "sms_code_required"
        assert required["verification_type"] == "120"
        assert required["receiver"] == "138****0000"
        assert required["resend_in"] > 0
        assert required["expires_in"] > 240
        assert cookie is None and not cookie_file.exists()

        submitted = await manager.submit_sms(login_id, "123456")
        assert submitted["state"] == "sms_verified"
        assert client.sms_checks == [("sms-rid-1", "123456", 0)]
        completed, cookie = await manager.poll(login_id)
        assert completed["state"] == "authenticated"
        assert cookie is not None and cookie_file.exists()

    asyncio.run(exercise())


def test_sms_resend_replaces_rid_after_cooldown(tmp_path: Path) -> None:
    client = FakeVerificationClient("a1=one; webId=two", "120")
    manager = QrLoginManager(Settings(cookie_file=tmp_path / "cookie"), client_factory=lambda _: client)

    async def exercise():
        login_id = str((await manager.create())["login_id"])
        await manager.poll(login_id)
        attempt = manager._attempts[login_id]
        attempt.sms_resend_at = 0
        resent = await manager.resend_sms(login_id)
        assert resent["state"] == "sms_code_required"
        assert attempt.sms_rid == "sms-rid-2"
        assert client.sms_send_calls == 2

    asyncio.run(exercise())


@pytest.mark.parametrize("upstream_status,state", [(3, "verification_cancelled"), (5, "expired"), (6, "verification_failed")])
def test_verification_terminal_states_never_persist(tmp_path: Path, upstream_status, state) -> None:
    client = FakeVerificationClient("a1=one; webId=two")
    cookie_file = tmp_path / "cookie"
    manager = QrLoginManager(Settings(cookie_file=cookie_file), client_factory=lambda _: client)

    async def exercise():
        login_id = (await manager.create())["login_id"]
        await manager.poll(login_id)
        client.verification_status = upstream_status
        result, cookie = await manager.poll(login_id)
        assert result["state"] == state and cookie is None
        assert not cookie_file.exists()

    asyncio.run(exercise())
