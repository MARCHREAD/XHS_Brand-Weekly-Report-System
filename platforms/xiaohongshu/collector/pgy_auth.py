from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field
import os
import time
from typing import Callable, Any
from uuid import uuid4

from ._signer import Xhshow
from .client import XhsClient
from .config import PROJECT_ROOT, ConfigurationError, Settings, parse_cookie_string
from .errors import XhsUpstreamError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cookie_string(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items() if name and value)


@dataclass
class _PhoneAttempt:
    client: XhsClient = field(repr=False)
    phone: str = field(repr=False)
    zone: str
    expires_at: float
    failures: int = 0


class PgyEmailLoginManager:
    """Owns browser-free Pgy email/SMS login and persisted session state."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[str], XhsClient] | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory or (
            lambda cookie: XhsClient(
                settings,
                cookie_string=cookie,
                pgy_cookie_string=cookie,
            )
        )
        self._lock = asyncio.Lock()
        self._state = "unverified" if settings.pgy_cookie_configured() else "missing"
        self._last_checked_at: str | None = None
        self._last_verified_at: str | None = None
        self._last_error: str | None = None
        self._phone_attempts: dict[str, _PhoneAttempt] = {}
        self._sms_resend_at = 0.0

    def _new_client(self) -> XhsClient:
        a1 = Xhshow.generate_a1()
        return self._client_factory(f"a1={a1}; webId={Xhshow.generate_web_id(a1)}")

    def _check_cookie_override(self) -> None:
        if os.getenv("XHS_PGY_COOKIE", "").strip():
            raise ConfigurationError("Remove XHS_PGY_COOKIE before interactive login so the new session can persist")

    async def send_phone_code(self, phone: str, zone: str = "86") -> dict[str, Any]:
        self._check_cookie_override()
        async with self._lock:
            now = time.monotonic()
            if now < self._sms_resend_at:
                raise ConfigurationError(f"Please wait {int(self._sms_resend_at - now) + 1} seconds before resending")
            # Match the official 60-second resend interval, including rejected sends.
            self._sms_resend_at = now + 60
            for key, attempt in list(self._phone_attempts.items()):
                if attempt.expires_at <= now:
                    del self._phone_attempts[key]
            existing = next(((key, attempt) for key, attempt in self._phone_attempts.items()
                             if attempt.phone == phone and attempt.zone == zone), None)
            client = existing[1].client if existing else self._new_client()
            try:
                await asyncio.to_thread(client.pgy_send_phone_code, phone, zone)
            except XhsUpstreamError as exc:
                raise self._phone_error(exc, phone) from None
            login_id = existing[0] if existing else uuid4().hex
            self._phone_attempts.clear()
            self._phone_attempts[login_id] = _PhoneAttempt(client, phone, zone, time.monotonic() + 300)
            return {"state": "sms_code_required", "login_id": login_id,
                    "receiver": phone[:3] + "****" + phone[-4:], "zone": zone,
                    "expires_in": 300, "resend_in": max(0, int(self._sms_resend_at - time.monotonic()) + 1)}

    async def login_phone(self, login_id: str, code: str) -> tuple[dict[str, Any], str]:
        self._check_cookie_override()
        async with self._lock:
            attempt = self._phone_attempts.get(login_id)
            if attempt is None or attempt.expires_at <= time.monotonic():
                self._phone_attempts.pop(login_id, None)
                raise ConfigurationError("SMS login attempt expired; request a new code")
            try:
                ticket = await asyncio.to_thread(attempt.client.pgy_phone_ticket, attempt.phone, code, attempt.zone)
                await asyncio.to_thread(attempt.client.pgy_accept_login_ticket, ticket)
                result = await asyncio.to_thread(attempt.client.pgy_user_info)
                self._require_user(result)
                cookie = self._finish_login(attempt.client)
            except XhsUpstreamError as exc:
                attempt.failures += 1
                if attempt.failures >= 3:
                    self._phone_attempts.pop(login_id, None)
                raise self._phone_error(exc, attempt.phone, code) from None
            self._phone_attempts.pop(login_id, None)
            return self._public("valid", configured=True), cookie

    @staticmethod
    def _phone_error(exc: XhsUpstreamError, phone: str, code: str = "") -> XhsUpstreamError:
        message = str(exc).replace(phone, "[phone]")
        if code:
            message = message.replace(code, "[code]")
        return XhsUpstreamError(message[:240], status_code=exc.status_code,
                                upstream_status=exc.upstream_status, upstream_code=exc.upstream_code,
                                auth_failure=exc.auth_failure)

    def _finish_login(self, client: XhsClient) -> str:
        cookie = client.effective_pgy_cookie_string()
        if not parse_cookie_string(cookie).get("a1"):
            raise ConfigurationError("Pgy login completed without an a1 cookie")
        self._persist_cookie(cookie)
        now = _utc_now()
        self._state = "valid"
        self._last_checked_at = now
        self._last_verified_at = now
        self._last_error = None
        return cookie

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            configured = self.settings.pgy_cookie_configured()
            state = self._state if configured or self._state == "valid" else "missing"
            return self._public(state, configured=configured or state == "valid")

    async def verify(self) -> tuple[dict[str, Any], str | None]:
        async with self._lock:
            checked_at = _utc_now()
            try:
                cookie = self.settings.pgy_cookie_string()
                client = self._client_factory(cookie)
                result = await asyncio.to_thread(client.pgy_user_info)
                self._require_user(result)
            except ConfigurationError as exc:
                self._state = "missing"
                self._last_checked_at = checked_at
                self._last_error = str(exc)
                return self._public("missing", configured=False), None
            except XhsUpstreamError as exc:
                self._state = "expired" if exc.auth_failure else "degraded"
                self._last_checked_at = checked_at
                self._last_error = str(exc)[:240]
                return self._public(self._state, configured=True), None
            except Exception as exc:
                self._state = "degraded"
                self._last_checked_at = checked_at
                self._last_error = str(exc)[:240] or exc.__class__.__name__
                return self._public("degraded", configured=True), None
            cookie = client.effective_pgy_cookie_string()
            self._state = "valid"
            self._last_checked_at = checked_at
            self._last_verified_at = checked_at
            self._last_error = None
            self._persist_cookie(cookie)
            return self._public("valid", configured=True), cookie

    async def login(self, email: str, password: str) -> tuple[dict[str, Any], str]:
        if os.getenv("XHS_PGY_COOKIE", "").strip():
            raise ConfigurationError(
                "Remove XHS_PGY_COOKIE before using interactive Pgy login so the new session can persist to file"
            )
        async with self._lock:
            client = self._new_client()
            try:
                ticket = await asyncio.to_thread(client.pgy_email_ticket, email, password)
                await asyncio.to_thread(client.pgy_accept_login_ticket, ticket)
                result = await asyncio.to_thread(client.pgy_user_info)
                self._require_user(result)
            except Exception as exc:
                self._state = "expired" if isinstance(exc, XhsUpstreamError) and exc.auth_failure else "error"
                self._last_checked_at = _utc_now()
                self._last_error = str(exc)[:240] or exc.__class__.__name__
                raise
            cookie = self._finish_login(client)
            return self._public("valid", configured=True), cookie

    @staticmethod
    def _require_user(result: dict[str, Any]) -> dict[str, Any]:
        data = result.get("data", result)
        if not isinstance(data, dict) or not any(data.get(key) for key in ("userId", "sellerId", "role")):
            raise XhsUpstreamError("Pgy session verification returned no account identity", auth_failure=True)
        return data

    def _public(self, state: str, *, configured: bool) -> dict[str, Any]:
        return {
            "state": state,
            "configured": configured,
            "last_checked_at": self._last_checked_at,
            "last_verified_at": self._last_verified_at,
            "last_error": self._last_error,
            "storage": "secrets/pgy_cookie.txt",
        }

    def _persist_cookie(self, cookie: str) -> None:
        path = (self.settings.pgy_cookie_file or (PROJECT_ROOT / "secrets" / "pgy_cookie.txt")).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(cookie, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
