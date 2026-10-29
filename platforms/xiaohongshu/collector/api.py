from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import ipaddress
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from .auth import QrLoginManager
from .client import XhsClient
from .config import PROJECT_ROOT, ConfigurationError, Settings
from .errors import EnrichmentError, XhsCollectorError, XhsUpstreamError
from .jobs import CollectorJobManager
from .pgy import (
    PgyBloggerDetailRequest,
    PgyBloggerSearchRequest,
    PgyNoteDetailRequest,
    PgySimilarBloggerRequest,
)
from .pgy_auth import PgyEmailLoginManager
from .runtime import SessionPool
from .service import CollectorService
from .sessions import SessionSupervisor


class CollectRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    pages: int = Field(default=1, ge=1, le=5)
    page_size: int = Field(default=20, ge=1, le=20)
    note_limit: int = Field(default=10, ge=1, le=50)
    include_details: bool = True
    include_authors: bool = True
    include_comments: bool = True
    comment_pages: int = Field(default=1, ge=1, le=5)
    use_gpt: bool = False
    save: bool = False
    sort: Literal["general", "popularity_descending", "time_descending"] = "general"
    note_type: int = Field(default=0, ge=0, le=2)


class SmsCodeRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class PgyEmailLoginRequest(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )
    password: SecretStr = Field(min_length=1, max_length=256)


class PgyPhoneCodeRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$", description="中国大陆手机号")
    zone: Literal["86"] = "86"


class PgyPhoneLoginRequest(BaseModel):
    login_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    code: str = Field(pattern=r"^\d{6}$")


def envelope(data: object, *, request_id: str | None = None) -> dict[str, object]:
    return {
        "code": 0,
        "message": "success",
        "request_id": request_id or uuid4().hex,
        "data": data,
    }


def create_app(
    settings: Settings | None = None,
    service: CollectorService | None = None,
    pgy_service: CollectorService | None = None,
    pgy_auth_manager: PgyEmailLoginManager | None = None,
    job_manager: CollectorJobManager | None = None,
    auth_manager: QrLoginManager | None = None,
    session_supervisor: SessionSupervisor | None = None,
) -> FastAPI:
    async def activate_sessions(target_app: FastAPI, *, verify: bool = False, force: bool = False) -> dict[str, object]:
        supervisor = target_app.state.sessions
        snapshot = await (supervisor.verify_all() if verify else supervisor.snapshot())
        clients, generation = await supervisor.active_clients()
        if clients and (force or generation != target_app.state.session_generation):
            activated_service = CollectorService(
                target_app.state.settings,
                pool=SessionPool(target_app.state.settings, clients),
            )
            target_app.state.service = activated_service
            if target_app.state.pgy_service is not None:
                target_app.state.pgy_service.xhs_fallback_pool = activated_service.pool
            if (
                not target_app.state.pgy_service_injected
                and not target_app.state.settings.pgy_cookie_configured()
            ):
                target_app.state.pgy_service = activated_service
            target_app.state.session_generation = generation
        elif not clients and target_app.state.manage_sessions:
            target_app.state.service = None
            if target_app.state.pgy_service is not None:
                target_app.state.pgy_service.xhs_fallback_pool = None
            if (
                not target_app.state.pgy_service_injected
                and not target_app.state.settings.pgy_cookie_configured()
            ):
                target_app.state.pgy_service = None
            target_app.state.session_generation = generation
        return snapshot

    async def session_loop(target_app: FastAPI) -> None:
        while True:
            try:
                async with target_app.state.service_lock:
                    await activate_sessions(target_app, verify=True)
                if (
                    not target_app.state.pgy_service_injected
                    and target_app.state.settings.pgy_cookie_configured()
                ):
                    pgy_status, pgy_cookie = await target_app.state.pgy_auth.verify()
                    async with target_app.state.service_lock:
                        if pgy_cookie:
                            await activate_pgy_session(pgy_cookie)
                        elif pgy_status.get("state") == "expired":
                            target_app.state.pgy_service = None
                            target_app.state.pgy_cookie_fingerprint = None
                target_app.state.session_monitor_error = None
            except Exception as exc:
                target_app.state.session_monitor_error = str(exc)[:240]
            await asyncio.sleep(target_app.state.settings.session_check_seconds)

    @asynccontextmanager
    async def lifespan(target_app: FastAPI):
        task: asyncio.Task[None] | None = None
        if target_app.state.manage_sessions:
            task = asyncio.create_task(session_loop(target_app))
            target_app.state.session_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="XHS Collector API",
        version="0.7.7",
        description="Browser-free Xiaohongshu and Pgy collection API.",
        lifespan=lifespan,
    )
    app.state.settings = settings or Settings.from_env()
    app.state.service = service
    app.state.pgy_service = pgy_service if pgy_service is not None else service
    app.state.pgy_service_injected = pgy_service is not None
    app.state.pgy_cookie_fingerprint = None
    app.state.manage_sessions = service is None
    app.state.session_generation = -1
    app.state.session_monitor_error = None
    app.state.service_lock = asyncio.Lock()
    app.state.jobs = job_manager or CollectorJobManager(app.state.settings.job_retention_seconds)
    app.state.auth = auth_manager or QrLoginManager(app.state.settings)
    app.state.pgy_auth = pgy_auth_manager or PgyEmailLoginManager(app.state.settings)
    app.state.sessions = session_supervisor or SessionSupervisor(app.state.settings)
    if (
        app.state.pgy_service is not None
        and app.state.service is not None
        and hasattr(app.state.pgy_service, "xhs_fallback_pool")
        and hasattr(app.state.service, "pool")
    ):
        app.state.pgy_service.xhs_fallback_pool = app.state.service.pool

    async def activate_pgy_session(cookie: str) -> None:
        fingerprint = hashlib.sha256(cookie.encode("utf-8")).hexdigest()
        fallback_pool = getattr(app.state.service, "pool", None)
        if (
            app.state.pgy_service is not None
            and app.state.pgy_cookie_fingerprint == fingerprint
        ):
            app.state.pgy_service.xhs_fallback_pool = fallback_pool
            return
        request_client = XhsClient(
            app.state.settings,
            cookie_string=cookie,
            pgy_cookie_string=cookie,
        )
        app.state.pgy_service = CollectorService(
            app.state.settings,
            client=request_client,
            xhs_fallback_pool=fallback_pool,
        )
        app.state.pgy_cookie_fingerprint = fingerprint

    async def get_service(request: Request) -> CollectorService:
        if request.app.state.service is None:
            async with request.app.state.service_lock:
                if request.app.state.service is None:
                    await request.app.state.sessions.reload()
                    clients, generation = await request.app.state.sessions.active_clients()
                    if not clients:
                        raise ConfigurationError("No active XHS session; open session management to verify or refresh login")
                    request.app.state.service = CollectorService(
                        request.app.state.settings,
                        pool=SessionPool(request.app.state.settings, clients),
                    )
                    request.app.state.session_generation = generation
        return request.app.state.service

    async def get_pgy_service(request: Request) -> CollectorService:
        if request.app.state.pgy_service is not None:
            return request.app.state.pgy_service
        if request.app.state.settings.pgy_cookie_configured():
            async with request.app.state.service_lock:
                if request.app.state.pgy_service is None:
                    cookie = request.app.state.settings.pgy_cookie_string()
                    await activate_pgy_session(cookie)
                return request.app.state.pgy_service
        service_value = await get_service(request)
        service_value.xhs_fallback_pool = service_value.pool
        request.app.state.pgy_service = service_value
        return service_value

    def require_local_setup(request: Request) -> None:
        host = request.url.hostname or ""
        client_host = request.client.host if request.client else ""
        host_is_local = host in {"localhost", "127.0.0.1", "::1", "testserver"}
        try:
            client_is_local = ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            client_is_local = client_host == "testclient"
        if not host_is_local or not client_is_local:
            raise HTTPException(status_code=403, detail="Session management is local-only")

    @app.exception_handler(ConfigurationError)
    async def configuration_error_handler(_: Request, exc: ConfigurationError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"code": 50301, "message": str(exc), "data": None})

    @app.exception_handler(XhsUpstreamError)
    async def upstream_error_handler(_: Request, exc: XhsUpstreamError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": 50201,
                "message": str(exc),
                "data": {
                    "upstream_status": exc.upstream_status,
                    "upstream_code": exc.upstream_code,
                },
            },
        )

    @app.exception_handler(EnrichmentError)
    async def enrichment_error_handler(_: Request, exc: EnrichmentError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"code": 50302, "message": str(exc), "data": None})

    @app.exception_handler(XhsCollectorError)
    async def collector_error_handler(_: Request, exc: XhsCollectorError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"code": 50001, "message": str(exc), "data": None})

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        current = request.app.state.settings
        session = await request.app.state.sessions.snapshot()
        pgy_session = await request.app.state.pgy_auth.snapshot()
        active_sessions = int(session.get("active", 0) or 0)
        effective_workers = active_sessions or (
            current.cookie_pool_size() if not request.app.state.manage_sessions else 0
        )
        return envelope(
            {
                "status": "ok",
                "xhs_cookie_configured": current.cookie_configured(),
                "pgy_cookie_configured": current.pgy_cookie_configured(),
                "pgy_session": pgy_session,
                "openai_configured": current.openai_configured,
                "signer": "builtin-python",
                "transport": current.impersonate,
                "configured_workers": current.worker_count,
                "effective_workers": effective_workers,
                "cache_enabled": current.cache_enabled,
                "qr_login_available": True,
                "session": session,
                "session_monitor_error": request.app.state.session_monitor_error,
            }
        )

    @app.get("/v1/xhs/auth/session")
    async def session_status(request: Request) -> dict[str, object]:
        require_local_setup(request)
        await request.app.state.sessions.reload()
        return envelope(await request.app.state.sessions.snapshot())

    @app.post("/v1/xhs/auth/session/verify")
    async def verify_session(request: Request) -> dict[str, object]:
        require_local_setup(request)
        async with request.app.state.service_lock:
            snapshot = await activate_sessions(request.app, verify=True, force=True)
        return envelope(snapshot)

    @app.post("/v1/xhs/auth/qrcode", status_code=201)
    async def create_qr_login(request: Request) -> dict[str, object]:
        require_local_setup(request)
        return envelope(await request.app.state.auth.create())

    @app.get("/v1/xhs/auth/qrcode/{login_id}")
    async def poll_qr_login(login_id: str, request: Request) -> dict[str, object]:
        require_local_setup(request)
        try:
            status, cookie_string = await request.app.state.auth.poll(login_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="QR login attempt not found") from exc
        if cookie_string:
            async with request.app.state.service_lock:
                await request.app.state.sessions.install(cookie_string)
                await activate_sessions(request.app, force=True)
        return envelope(status)

    @app.post("/v1/xhs/auth/qrcode/{login_id}/sms")
    async def submit_qr_sms(login_id: str, body: SmsCodeRequest, request: Request) -> dict[str, object]:
        require_local_setup(request)
        try:
            return envelope(await request.app.state.auth.submit_sms(login_id, body.code))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="QR login attempt not found") from exc

    @app.post("/v1/xhs/auth/qrcode/{login_id}/sms/resend")
    async def resend_qr_sms(login_id: str, request: Request) -> dict[str, object]:
        require_local_setup(request)
        try:
            return envelope(await request.app.state.auth.resend_sms(login_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="QR login attempt not found") from exc

    @app.get("/v1/xhs/runtime")
    async def runtime(service: CollectorService = Depends(get_service)) -> dict[str, object]:
        return envelope(await service.runtime_snapshot())

    @app.get("/v1/xhs/pgy/auth/session")
    async def pgy_session_status(request: Request) -> dict[str, object]:
        require_local_setup(request)
        return envelope(await request.app.state.pgy_auth.snapshot())

    @app.post("/v1/xhs/pgy/auth/session/verify")
    async def verify_pgy_session(request: Request) -> dict[str, object]:
        require_local_setup(request)
        status, cookie = await request.app.state.pgy_auth.verify()
        if cookie:
            async with request.app.state.service_lock:
                await activate_pgy_session(cookie)
        return envelope(status)

    @app.post("/v1/xhs/pgy/auth/email")
    async def pgy_email_login(
        body: PgyEmailLoginRequest,
        request: Request,
    ) -> dict[str, object]:
        require_local_setup(request)
        status, cookie = await request.app.state.pgy_auth.login(
            body.email,
            body.password.get_secret_value(),
        )
        async with request.app.state.service_lock:
            await activate_pgy_session(cookie)
        return envelope(status)

    @app.post("/v1/xhs/pgy/auth/phone/code")
    async def pgy_send_phone_code(body: PgyPhoneCodeRequest, request: Request) -> dict[str, object]:
        require_local_setup(request)
        return envelope(await request.app.state.pgy_auth.send_phone_code(body.phone, body.zone))

    @app.post("/v1/xhs/pgy/auth/phone")
    async def pgy_phone_login(body: PgyPhoneLoginRequest, request: Request) -> dict[str, object]:
        require_local_setup(request)
        status, cookie = await request.app.state.pgy_auth.login_phone(body.login_id, body.code)
        async with request.app.state.service_lock:
            await activate_pgy_session(cookie)
        return envelope(status)

    @app.get("/v1/xhs/homefeed")
    async def homefeed(
        category: str = Query(default="homefeed_recommend", max_length=80),
        cursor_score: str = Query(default="", max_length=500),
        num: int = Query(default=20, ge=1, le=40),
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(await service.homefeed(category, cursor_score, num))

    @app.get("/v1/xhs/search/notes")
    async def search_notes(
        keyword: str = Query(min_length=1),
        pages: int = Query(default=1, ge=1),
        sort: Literal["general", "popularity_descending", "time_descending"] = "general",
        note_type: int = Query(default=0, ge=0, le=2),
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(await service.search_pages(keyword, pages, sort, note_type))

    @app.get("/v1/xhs/search/users")
    async def search_users(
        keyword: str = Query(min_length=1),
        pages: int = Query(default=1, ge=1),
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(await service.search_users(keyword, pages))

    @app.get("/v1/xhs/notes/{note_id}")
    async def note_detail(
        note_id: str,
        xsec_token: str = Query(min_length=1, max_length=500),
        xsec_source: str = Query(default="pc_search", max_length=80),
        use_gpt: bool = False,
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(await service.note(note_id, xsec_token, xsec_source, use_gpt))

    @app.get("/v1/xhs/notes/{note_id}/comments")
    async def note_comments(
        note_id: str,
        xsec_token: str = Query(min_length=1, max_length=500),
        cursor: str = Query(default="", max_length=500),
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(await service.comments(note_id, xsec_token, cursor))

    @app.get("/v1/xhs/users/{user_id}")
    async def user_profile(
        user_id: str,
        xsec_token: str = Query(default="", max_length=500),
        xsec_source: str = Query(default="pc_search", max_length=80),
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(await service.author(user_id, xsec_token=xsec_token, xsec_source=xsec_source))

    @app.get("/v1/xhs/users/{user_id}/notes")
    async def user_notes(
        user_id: str,
        xsec_token: str = Query(min_length=1, max_length=500),
        xsec_source: str = Query(default="pc_search", max_length=80),
        cursor: str = Query(default="", max_length=500),
        num: int = Query(default=30, ge=1, le=30),
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(await service.author_notes(user_id, cursor, num, xsec_token, xsec_source))

    @app.post("/v1/xhs/pgy/get_note_detail")
    async def pgy_note_detail(
        body: PgyNoteDetailRequest,
        service: CollectorService = Depends(get_pgy_service),
    ) -> dict[str, object]:
        return envelope(await service.pgy_note_detail(body))

    @app.post("/v1/xhs/pgy/get_blogger_detail")
    async def pgy_blogger_detail(
        body: PgyBloggerDetailRequest,
        service: CollectorService = Depends(get_pgy_service),
    ) -> dict[str, object]:
        return envelope(await service.pgy_blogger_detail(body))

    @app.post("/v1/xhs/pgy/get_blogger_similar")
    async def pgy_similar_bloggers(
        body: PgySimilarBloggerRequest,
        service: CollectorService = Depends(get_pgy_service),
    ) -> dict[str, object]:
        return envelope(await service.pgy_similar_bloggers(body))

    @app.post("/v1/xhs/pgy/get_blogger_square")
    async def pgy_search_bloggers(
        body: PgyBloggerSearchRequest,
        service: CollectorService = Depends(get_pgy_service),
    ) -> dict[str, object]:
        return envelope(await service.pgy_search_bloggers(body))

    @app.get("/v1/xhs/pgy/get_blogger_filter_options")
    async def pgy_filter_options(
        service: CollectorService = Depends(get_pgy_service),
    ) -> dict[str, object]:
        return envelope(await service.pgy_filter_options())

    @app.post("/v1/xhs/collect")
    async def collect(request: CollectRequest, service: CollectorService = Depends(get_service)) -> dict[str, object]:
        return envelope(await service.collect_keyword(**request.model_dump()))

    @app.post("/v1/xhs/collect/jobs", status_code=202)
    async def create_collect_job(
        request: CollectRequest,
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        job = await app.state.jobs.create(service, request.model_dump())
        job["runtime"] = await service.runtime_snapshot()
        return envelope(job)

    @app.get("/v1/xhs/collect/jobs/{job_id}")
    async def get_collect_job(
        job_id: str,
        service: CollectorService = Depends(get_service),
    ) -> dict[str, object]:
        try:
            job = await app.state.jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Collector job not found") from exc
        job["runtime"] = await service.runtime_snapshot()
        return envelope(job)

    from .weekly.manager import Manager as WeeklyManager
    from .weekly.routes import router as weekly_router

    app.include_router(weekly_router(WeeklyManager(app.state.settings.output_dir), get_service, require_local_setup))
    app.mount("/", StaticFiles(directory=PROJECT_ROOT / "web", html=True), name="web")
    return app


app = create_app()
