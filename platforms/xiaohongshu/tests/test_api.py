import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from collector.api import create_app
from collector.config import Settings


class FakeService:
    async def search(self, keyword, page, page_size, sort, note_type):
        return {"items": [{"note_id": "n1", "title": keyword}], "has_more": False, "search_id": ""}

    async def search_pages(self, keyword, pages, sort, note_type):
        return {
            "items": [{"note_id": f"n{page}", "title": keyword} for page in range(1, pages + 1)],
            "requested_pages": pages,
            "fetched_pages": pages,
            "has_more": True,
            "search_id": "search-fixture",
        }

    async def search_users(self, keyword, pages):
        return {
            "items": [{"user_id": f"u{page}", "nickname": keyword} for page in range(1, pages + 1)],
            "requested_pages": pages,
            "fetched_pages": pages,
            "has_more": True,
            "search_id": "user-search-fixture",
        }

    async def author(self, user_id, trace=None, **kwargs):
        token = kwargs.get("xsec_token", "")
        return {
            "user_id": user_id,
            "nickname": "user",
            "xsec_token": token,
            "xsec_source": kwargs.get("xsec_source", "") if token else "",
            "xsec_token_available": bool(token),
        }

    async def runtime_snapshot(self):
        return {
            "pool": {"configured_workers": 2, "effective_workers": 2, "active": 0, "queued": 0},
            "cache": {"enabled": True, "entries": 1},
            "gpt_concurrency": 3,
        }

    async def collect_keyword(self, *, trace, **options):
        event = {
            "id": "api-event",
            "stage": "search",
            "interface": "POST /search",
            "target": options["keyword"],
            "status": "running",
        }
        await trace(event)
        await asyncio.sleep(0.01)
        await trace({**event, "status": "success", "duration_ms": 10, "response": {"item_count": 1}})
        return {"keyword": options["keyword"], "count": 1, "items": []}


class FakeAuthManager:
    async def create(self):
        return {"login_id": "login-fixture", "state": "waiting_scan", "qr_image": "data:image/png;base64,AA=="}

    async def poll(self, login_id):
        assert login_id == "login-fixture"
        return {"state": "waiting_scan", "authenticated": False}, None

    async def submit_sms(self, login_id, code):
        assert login_id == "login-fixture" and code == "123456"
        return {"state": "sms_verified", "authenticated": False}

    async def resend_sms(self, login_id):
        assert login_id == "login-fixture"
        return {"state": "sms_code_required", "resend_in": 60}


class FakeAuthenticatedAuthManager(FakeAuthManager):
    async def poll(self, login_id):
        return {"state": "authenticated", "authenticated": True}, "a1=one; web_session=two; webId=three"


class FakeSessionSupervisor:
    def __init__(self):
        self.verified = False

    async def reload(self):
        return False

    async def snapshot(self):
        return {
            "state": "valid" if self.verified else "unverified",
            "configured": True,
            "total": 1,
            "active": 1,
            "counts": {},
            "sessions": [],
        }

    async def verify_all(self):
        self.verified = True
        return await self.snapshot()

    async def active_clients(self):
        return [], 0

    async def install(self, cookie_string):
        assert "web_session" in cookie_string
        self.verified = True
        return await self.snapshot()


def test_health_without_secrets(tmp_path: Path) -> None:
    app = create_app(settings=Settings(cookie_file=tmp_path / "missing.txt"), service=FakeService())
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["data"]["xhs_cookie_configured"] is False
    assert response.json()["data"]["qr_login_available"] is True


def test_local_qr_login_routes(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(cookie_file=tmp_path / "missing.txt"),
        service=FakeService(),
        auth_manager=FakeAuthManager(),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        created = client.post("/v1/xhs/auth/qrcode")
        assert created.status_code == 201
        assert created.json()["data"]["login_id"] == "login-fixture"
        polled = client.get("/v1/xhs/auth/qrcode/login-fixture")
        assert polled.status_code == 200
        assert polled.json()["data"]["state"] == "waiting_scan"
        submitted = client.post("/v1/xhs/auth/qrcode/login-fixture/sms", json={"code": "123456"})
        resent = client.post("/v1/xhs/auth/qrcode/login-fixture/sms/resend")
        assert submitted.status_code == 200
        assert submitted.json()["data"]["state"] == "sms_verified"
        assert resent.status_code == 200
        assert resent.json()["data"]["state"] == "sms_code_required"


def test_local_session_status_and_verify_routes(tmp_path: Path) -> None:
    supervisor = FakeSessionSupervisor()
    app = create_app(
        settings=Settings(cookie_file=tmp_path / "missing.txt"),
        service=FakeService(),
        session_supervisor=supervisor,  # type: ignore[arg-type]
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        status = client.get("/v1/xhs/auth/session")
        verified = client.post("/v1/xhs/auth/session/verify")
    assert status.status_code == 200
    assert status.json()["data"]["state"] == "unverified"
    assert verified.status_code == 200
    assert verified.json()["data"]["state"] == "valid"


def test_qr_login_routes_reject_nonlocal_host(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(cookie_file=tmp_path / "missing.txt"),
        service=FakeService(),
        auth_manager=FakeAuthManager(),
    )
    response = TestClient(app, base_url="https://collector.example").post("/v1/xhs/auth/qrcode")
    assert response.status_code == 403


def test_completed_qr_login_hot_swaps_service(tmp_path: Path) -> None:
    previous = FakeService()
    app = create_app(
        settings=Settings(cookie_file=tmp_path / "missing.txt"),
        service=previous,
        auth_manager=FakeAuthenticatedAuthManager(),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/v1/xhs/auth/qrcode/login-fixture")
    assert response.status_code == 200
    assert response.json()["data"]["authenticated"] is True
    assert app.state.service is not previous


def test_search_envelope(tmp_path: Path) -> None:
    app = create_app(settings=Settings(cookie_file=tmp_path / "missing.txt"), service=FakeService())
    response = TestClient(app).get(
        "/v1/xhs/search/notes",
        params={"keyword": "咖啡", "pages": 3},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 0
    assert body["data"]["items"][0]["title"] == "咖啡"
    assert len(body["data"]["items"]) == 3
    assert body["data"]["requested_pages"] == 3
    assert body["data"]["fetched_pages"] == 3


def test_search_pages_has_no_configured_upper_limit(tmp_path: Path) -> None:
    app = create_app(settings=Settings(cookie_file=tmp_path / "missing.txt"), service=FakeService())
    response = TestClient(app).get(
        "/v1/xhs/search/notes",
        params={"keyword": "长关键词" * 100, "pages": 51},
    )
    assert response.status_code == 200
    assert response.json()["data"]["requested_pages"] == 51


def test_search_users_envelope(tmp_path: Path) -> None:
    app = create_app(settings=Settings(cookie_file=tmp_path / "missing.txt"), service=FakeService())
    response = TestClient(app).get(
        "/v1/xhs/search/users",
        params={"keyword": "咖啡", "pages": 2},
    )
    assert response.status_code == 200
    assert len(response.json()["data"]["items"]) == 2
    assert response.json()["data"]["requested_pages"] == 2


def test_user_profile_returns_supplied_xsec_token(tmp_path: Path) -> None:
    app = create_app(settings=Settings(cookie_file=tmp_path / "missing.txt"), service=FakeService())
    response = TestClient(app).get(
        "/v1/xhs/users/u1",
        params={"xsec_token": "token-fixture", "xsec_source": "pc_search"},
    )
    data = response.json()["data"]
    assert response.status_code == 200
    assert data["xsec_token"] == "token-fixture"
    assert data["xsec_source"] == "pc_search"
    assert data["xsec_token_available"] is True


def test_background_job_routes(tmp_path: Path) -> None:
    app = create_app(settings=Settings(cookie_file=tmp_path / "missing.txt"), service=FakeService())
    request = {
        "keyword": "咖啡",
        "pages": 1,
        "page_size": 20,
        "note_limit": 1,
        "include_details": False,
        "include_authors": False,
        "include_comments": False,
        "comment_pages": 1,
        "use_gpt": False,
        "save": False,
        "sort": "general",
        "note_type": 0,
    }
    with TestClient(app) as client:
        created = client.post("/v1/xhs/collect/jobs", json=request)
        assert created.status_code == 202
        job_id = created.json()["data"]["job_id"]
        for _ in range(20):
            snapshot = client.get(f"/v1/xhs/collect/jobs/{job_id}")
            if snapshot.json()["data"]["status"] == "completed":
                break
            import time

            time.sleep(0.01)
        data = snapshot.json()["data"]
        assert data["status"] == "completed"
        assert data["events"][0]["status"] == "success"
        assert data["runtime"]["pool"]["effective_workers"] == 2
