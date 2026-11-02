import asyncio
import json
from pathlib import Path
import time
import pytest

from fastapi.testclient import TestClient

from collector.api import create_app
from collector.client import XhsClient
from collector.config import Settings, parse_cookie_string
from collector.errors import XhsUpstreamError
from collector.config import ConfigurationError
from collector.pgy_auth import PgyEmailLoginManager


class FakeLoginClient:
    def __init__(self, cookie: str) -> None:
        self.cookie = cookie
        self.calls = []

    def pgy_email_ticket(self, email, password):
        self.calls.append(("email", email, password))
        return "ticket-fixture"

    def pgy_send_phone_code(self, phone, zone):
        self.calls.append(("send", phone, zone))
        return {"code": 0, "success": True}

    def pgy_phone_ticket(self, phone, code, zone):
        self.calls.append(("phone", phone, code, zone))
        return "phone-ticket-fixture"

    def pgy_accept_login_ticket(self, ticket):
        self.calls.append(("ticket", ticket))
        return {"code": 0, "success": True, "data": {}}

    def pgy_user_info(self):
        self.calls.append(("verify",))
        return {"code": 0, "success": True, "data": {"userId": "u1", "role": "brand"}}

    def effective_pgy_cookie_string(self):
        cookies = parse_cookie_string(self.cookie)
        cookies["solar.beaker.session.id"] = "issued-session"
        return "; ".join(f"{key}={value}" for key, value in cookies.items())


def test_pgy_email_login_persists_only_issued_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XHS_PGY_COOKIE", raising=False)
    clients = []

    def factory(cookie):
        client = FakeLoginClient(cookie)
        clients.append(client)
        return client

    pgy_cookie = tmp_path / "secrets" / "pgy_cookie.txt"
    manager = PgyEmailLoginManager(
        Settings(cookie_file=tmp_path / "missing-xhs", pgy_cookie_file=pgy_cookie),
        client_factory=factory,  # type: ignore[arg-type]
    )

    status, cookie = asyncio.run(manager.login("user@example.com", "password-fixture"))

    assert status["state"] == "valid"
    assert parse_cookie_string(cookie)["solar.beaker.session.id"] == "issued-session"
    stored = pgy_cookie.read_text(encoding="utf-8")
    assert "password-fixture" not in stored
    assert "user@example.com" not in stored
    assert clients[0].calls == [
        ("email", "user@example.com", "password-fixture"),
        ("ticket", "ticket-fixture"),
        ("verify",),
    ]


def test_pgy_saved_session_can_be_verified(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XHS_PGY_COOKIE", raising=False)
    pgy_cookie = tmp_path / "pgy_cookie.txt"
    pgy_cookie.write_text("a1=one; webId=two; solar.beaker.session.id=three", encoding="utf-8")
    manager = PgyEmailLoginManager(
        Settings(cookie_file=tmp_path / "missing-xhs", pgy_cookie_file=pgy_cookie),
        client_factory=lambda cookie: FakeLoginClient(cookie),  # type: ignore[arg-type]
    )

    status, cookie = asyncio.run(manager.verify())

    assert status["state"] == "valid"
    assert cookie is not None
    assert status["last_verified_at"]


class FakeSigner:
    def __init__(self) -> None:
        self.calls = []

    def headers(self, method, path, cookies, **kwargs):
        self.calls.append((method, path, cookies, kwargs))
        return {"x-s": "signed", "x-t": "1", "x-s-common": "common"}


class FakeCookieJar:
    def get_dict(self):
        return {"solar.beaker.session.id": "issued"}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.cookies = FakeCookieJar()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        status, body = self.responses.pop(0)
        return type(
            "Response",
            (),
            {"status_code": status, "content": json.dumps(body).encode(), "headers": {}},
        )()


def test_pgy_client_email_ticket_and_exchange_wire_contract(tmp_path: Path) -> None:
    signer = FakeSigner()
    cookie = "a1=one; webId=two"
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing", pgy_cookie_file=tmp_path / "missing-pgy"),
        signer=signer,  # type: ignore[arg-type]
        cookie_string=cookie,
        pgy_cookie_string=cookie,
    )
    client.pgy_session = FakeSession(
        [
            (200, {"code": 0, "success": True, "data": {"ticket": "ticket-1"}}),
            (200, {"code": 0, "success": True, "data": {}}),
        ]
    )  # type: ignore[assignment]
    client._wait_for_rate_limit = lambda: None

    ticket = client.pgy_email_ticket("user@example.com", "secret")
    client.pgy_accept_login_ticket(ticket)

    first = client.pgy_session.calls[0]
    assert first[0] == "POST"
    assert first[1] == "https://customer.xiaohongshu.com/api/cas/customer/web/service-ticket"
    assert json.loads(first[2]["data"]) == {
        "email": "user@example.com",
        "pwd": "secret",
        "service": "https://pgy.xiaohongshu.com",
        "source": "",
        "type": "emailPwd",
    }
    assert first[2]["headers"]["x-ratelimit-meta"] == "host=pgy.xiaohongshu.com"
    assert signer.calls[0][1] == "/api/cas/customer/web/service-ticket"
    assert signer.calls[0][3]["payload"]["type"] == "emailPwd"
    assert signer.calls[1][1] == "/api/solar/login_with_ticket_new"
    assert signer.calls[1][3]["payload"] == {"ticket": "ticket-1"}


class FakePgyAuthManager:
    async def snapshot(self):
        return {"state": "missing", "configured": False}

    async def verify(self):
        return {"state": "valid", "configured": True}, "a1=one; solar.beaker.session.id=two"

    async def login(self, email, password):
        assert email == "user@example.com"
        assert password == "password-fixture"
        return {"state": "valid", "configured": True}, "a1=one; solar.beaker.session.id=two"

    async def send_phone_code(self, phone, zone):
        assert phone == "13800000000"
        assert zone == "86"
        return {"state": "sms_code_required", "login_id": "a" * 32, "resend_in": 60, "expires_in": 300}

    async def login_phone(self, login_id, code):
        assert login_id == "a" * 32
        assert code == "123456"
        return {"state": "valid", "configured": True}, "a1=one; solar.beaker.session.id=two"


def test_phone_login_uses_same_client_and_validates_before_persistence(monkeypatch, tmp_path):
    monkeypatch.delenv("XHS_PGY_COOKIE", raising=False)
    clients = []
    def factory(cookie):
        client = FakeLoginClient(cookie)
        clients.append(client)
        return client
    cookie_path = tmp_path / "pgy-cookie.txt"
    manager = PgyEmailLoginManager(Settings(cookie_file=tmp_path / "xhs", pgy_cookie_file=cookie_path), client_factory=factory)
    async def run():
        attempt = await manager.send_phone_code("13800000000")
        assert attempt["receiver"] == "138****0000"
        assert not cookie_path.exists()
        with pytest.raises(ConfigurationError, match="wait"):
            await manager.send_phone_code("13800000000")
        status, cookie = await manager.login_phone(attempt["login_id"], "123456")
        assert status["state"] == "valid"
        assert cookie == cookie_path.read_text(encoding="utf-8")
        with pytest.raises(ConfigurationError, match="expired"):
            await manager.login_phone(attempt["login_id"], "123456")
    asyncio.run(run())
    assert len(clients) == 1
    assert clients[0].calls == [("send", "13800000000", "86"),
                              ("phone", "13800000000", "123456", "86"),
                              ("ticket", "phone-ticket-fixture"), ("verify",)]
    assert "13800000000" not in cookie_path.read_text(encoding="utf-8")
    assert "123456" not in cookie_path.read_text(encoding="utf-8")


def test_phone_resend_reuses_cookie_jar_and_expired_attempt_is_rejected(monkeypatch, tmp_path):
    monkeypatch.delenv("XHS_PGY_COOKIE", raising=False)
    manager = PgyEmailLoginManager(Settings(cookie_file=tmp_path / "xhs", pgy_cookie_file=tmp_path / "pgy"),
                                   client_factory=FakeLoginClient)
    async def run():
        first = await manager.send_phone_code("13800000000")
        client = manager._phone_attempts[first["login_id"]].client
        manager._sms_resend_at = 0
        second = await manager.send_phone_code("13800000000")
        assert second["login_id"] == first["login_id"]
        assert manager._phone_attempts[first["login_id"]].client is client
        manager._phone_attempts[first["login_id"]].expires_at = 0
        with pytest.raises(ConfigurationError, match="expired"):
            await manager.login_phone(first["login_id"], "123456")
        assert all(call[0] == "send" for call in client.calls)
    asyncio.run(run())


def test_wrong_phone_code_and_failed_verification_do_not_replace_good_session(monkeypatch, tmp_path):
    monkeypatch.delenv("XHS_PGY_COOKIE", raising=False)
    class BadCodeClient(FakeLoginClient):
        def pgy_phone_ticket(self, phone, code, zone):
            raise XhsUpstreamError(f"invalid code {code} for {phone}", upstream_code=1)
    path = tmp_path / "pgy"
    saved = "a1=original; solar.beaker.session.id=original"
    path.write_text(saved)
    manager = PgyEmailLoginManager(Settings(cookie_file=tmp_path / "xhs", pgy_cookie_file=path), client_factory=BadCodeClient)
    manager._state = "valid"
    async def run():
        attempt = await manager.send_phone_code("13800000000")
        for _ in range(3):
            with pytest.raises(XhsUpstreamError) as error:
                await manager.login_phone(attempt["login_id"], "123456")
            assert "13800000000" not in str(error.value)
            assert "123456" not in str(error.value)
        assert attempt["login_id"] not in manager._phone_attempts
        assert (await manager.snapshot())["state"] == "valid"
    asyncio.run(run())
    assert path.read_text() == saved
    class NoIdentityClient(FakeLoginClient):
        def pgy_user_info(self):
            return {"success": True, "data": {}}
    manager = PgyEmailLoginManager(Settings(cookie_file=tmp_path / "xhs", pgy_cookie_file=path), client_factory=NoIdentityClient)
    async def failed_verify():
        attempt = await manager.send_phone_code("13800000000")
        with pytest.raises(XhsUpstreamError):
            await manager.login_phone(attempt["login_id"], "123456")
    asyncio.run(failed_verify())
    assert path.read_text() == saved


def test_phone_client_wire_contract_and_send_rejection(tmp_path):
    signer = FakeSigner()
    client = XhsClient(Settings(cookie_file=tmp_path / "missing"), signer=signer,
                       cookie_string="a1=one; webId=two", pgy_cookie_string="a1=one; webId=two")
    client.pgy_session = FakeSession([(200, {"code": 0, "success": True}),
                                    (200, {"code": 0, "success": True, "data": {"ticket": "phone-ticket"}}),
                                    (200, {"code": 1, "success": False, "msg": "rejected"})])
    client._wait_for_rate_limit = lambda: None
    client.pgy_send_phone_code("13800000000")
    assert client.pgy_phone_ticket("13800000000", "123456") == "phone-ticket"
    calls = client.pgy_session.calls
    assert calls[0][1] == "https://customer.xiaohongshu.com/api/cas/customer/web/verify-code"
    assert json.loads(calls[0][2]["data"]) == {"phone": "13800000000", "zone": "86", "service": "https://pgy.xiaohongshu.com"}
    assert json.loads(calls[1][2]["data"]) == {"phone": "13800000000", "zone": "86", "verify_code": "123456", "service": "https://pgy.xiaohongshu.com", "source": "", "type": "phoneVerifyCode"}
    assert len(signer.calls) == 2
    assert signer.calls[1][3]["payload"]["verify_code"] == "123456"
    assert "verifyCode" not in signer.calls[1][3]["payload"]
    with pytest.raises(XhsUpstreamError):
        client.pgy_send_phone_code("13800000000")
    assert len(client.pgy_session.calls) == 3


def test_phone_api_validates_and_restricts_local_login(tmp_path):
    app = create_app(settings=Settings(cookie_file=tmp_path / "xhs", pgy_cookie_file=tmp_path / "pgy"),
                     service=object(), pgy_auth_manager=FakePgyAuthManager())
    local = TestClient(app, base_url="http://127.0.0.1")
    sent = local.post("/v1/xhs/pgy/auth/phone/code", json={"phone": "13800000000"})
    assert sent.status_code == 200
    result = local.post("/v1/xhs/pgy/auth/phone", json={"login_id": sent.json()["data"]["login_id"], "code": "123456"})
    assert result.status_code == 200
    assert app.state.pgy_service is not None
    assert local.post("/v1/xhs/pgy/auth/phone/code", json={"phone": "bad"}).status_code == 422
    assert local.post("/v1/xhs/pgy/auth/phone", json={"login_id": "a"*32, "code": "12"}).status_code == 422
    remote = TestClient(app, base_url="https://example.com")
    assert remote.post("/v1/xhs/pgy/auth/phone/code", json={"phone": "13800000000"}).status_code == 403
    assert remote.post("/v1/xhs/pgy/auth/phone", json={"login_id": "a"*32, "code": "123456"}).status_code == 403


def test_pgy_email_login_api_is_local_and_hot_activates_service(tmp_path: Path) -> None:
    settings = Settings(
        cookie_file=tmp_path / "missing-xhs",
        pgy_cookie_file=tmp_path / "missing-pgy",
    )
    app = create_app(
        settings=settings,
        service=object(),  # type: ignore[arg-type]
        pgy_auth_manager=FakePgyAuthManager(),  # type: ignore[arg-type]
    )
    payload = {"email": "user@example.com", "password": "password-fixture"}

    local = TestClient(app, base_url="http://127.0.0.1").post(
        "/v1/xhs/pgy/auth/email",
        json=payload,
    )
    remote = TestClient(app, base_url="https://collector.example").post(
        "/v1/xhs/pgy/auth/email",
        json=payload,
    )

    assert local.status_code == 200
    assert local.json()["data"]["state"] == "valid"
    assert app.state.pgy_service is not None
    assert remote.status_code == 403


class EmptyXhsSessions:
    async def verify_all(self):
        return {"state": "missing", "active": 0, "sessions": []}

    async def snapshot(self):
        return {"state": "missing", "active": 0, "sessions": []}

    async def active_clients(self):
        return [], 0


def test_background_monitor_activates_saved_pgy_session(tmp_path: Path) -> None:
    pgy_cookie = tmp_path / "pgy.txt"
    pgy_cookie.write_text("a1=one; solar.beaker.session.id=two", encoding="utf-8")
    settings = Settings(
        cookie_file=tmp_path / "missing-xhs",
        pgy_cookie_file=pgy_cookie,
        session_check_seconds=60,
    )
    app = create_app(
        settings=settings,
        pgy_auth_manager=FakePgyAuthManager(),  # type: ignore[arg-type]
        session_supervisor=EmptyXhsSessions(),  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        for _ in range(20):
            client.get("/health")
            if app.state.pgy_cookie_fingerprint:
                break
            time.sleep(0.01)

    assert app.state.pgy_service is not None
    assert app.state.pgy_cookie_fingerprint is not None
