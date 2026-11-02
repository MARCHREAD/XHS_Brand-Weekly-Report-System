from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from io import BytesIO
import os
from pathlib import Path
import sys
import time
from typing import Callable
from uuid import uuid4

import qrcode
from .client import XhsClient
from .config import REQUIRED_COOKIE_NAMES, ConfigurationError, Settings
from ._signer import Xhshow


QR_LOGIN_TTL_SECONDS = 65


@dataclass(slots=True)
class _QrLoginAttempt:
    client: XhsClient
    qr_id: str = field(repr=False)
    code: str = field(repr=False)
    created_at: float
    expires_at: float
    verification_rid: str | None = field(default=None, repr=False)
    verification_image: str | None = field(default=None, repr=False)
    verification_type: str | None = None
    sms_rid: str | None = field(default=None, repr=False)
    sms_receiver: str | None = None
    sms_resend_at: float = 0.0
    sms_check_count: int = 0
    poll_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def render_qr_data_uri(value: str) -> str:
    qr = qrcode.QRCode(version=None, box_size=6, border=3)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#111111", back_color="#ffffff")
    output = BytesIO()
    image.save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def serialize_cookie_string(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items() if name and value)


class QrLoginManager:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[str], XhsClient] | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory or (
            lambda cookie: XhsClient(settings, cookie_string=cookie)
        )
        self._attempts: dict[str, _QrLoginAttempt] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> dict[str, object]:
        a1 = Xhshow.generate_a1()
        web_id = Xhshow.generate_web_id(a1)
        client = self._client_factory(f"a1={a1}; webId={web_id}")
        result = await asyncio.to_thread(client.create_qr_login)
        qr_id = str(result.get("qr_id") or "")
        code = str(result.get("code") or "")
        login_url = str(result.get("url") or "")
        if not qr_id or not code or not login_url:
            raise ConfigurationError("XHS QR login returned an incomplete response")
        now = time.monotonic()
        login_id = uuid4().hex
        attempt = _QrLoginAttempt(
            client=client,
            qr_id=qr_id,
            code=code,
            created_at=now,
            expires_at=now + QR_LOGIN_TTL_SECONDS,
        )
        async with self._lock:
            self._remove_expired_locked(now)
            self._attempts.clear()
            self._attempts[login_id] = attempt
        return {
            "login_id": login_id,
            "state": "waiting_scan",
            "expires_in": QR_LOGIN_TTL_SECONDS,
            "qr_image": render_qr_data_uri(login_url),
        }

    async def poll(self, login_id: str) -> tuple[dict[str, object], str | None]:
        async with self._lock:
            attempt = self._attempts.get(login_id)
        if attempt is None:
            raise KeyError(login_id)
        async with attempt.poll_lock:
            async with self._lock:
                if self._attempts.get(login_id) is not attempt:
                    raise KeyError(login_id)
            return await self._poll_attempt(login_id, attempt)

    async def _poll_attempt(self, login_id: str, attempt: _QrLoginAttempt) -> tuple[dict[str, object], str | None]:
        now = time.monotonic()
        if now >= attempt.expires_at:
            async with self._lock:
                self._attempts.pop(login_id, None)
            return self._status("expired", 3, 0), None

        if attempt.sms_rid:
            return self._sms_status(attempt), None

        if attempt.verification_rid:
            verification = await asyncio.to_thread(
                attempt.client.qr_verification_status, attempt.verification_rid,
            )
            verify_status = int(verification.get("status", 0) or 0)
            status_label = {
                1: "waiting_scan", 2: "scanned", 3: "cancelled",
                4: "confirmed", 5: "expired", 6: "failed",
            }.get(verify_status, "unknown")
            # Only protocol enums are logged; challenge IDs and QR contents stay in memory.
            print(
                f"[xhs-qr-verification] type={attempt.verification_type or 'unknown'} state={status_label}",
                file=sys.stderr,
                flush=True,
            )
            if verify_status in {3, 5, 6}:
                async with self._lock:
                    self._attempts.pop(login_id, None)
                state = {3: "verification_cancelled", 5: "expired", 6: "verification_failed"}[verify_status]
                return self._status(state, 3, 0), None
            if verify_status != 4:
                return self._verification_status(attempt, verify_status), None
            attempt.verification_rid = None
            attempt.verification_image = None
            attempt.verification_type = None
            # The official SDK replays the original QR status after confirmation.
            attempt.expires_at = max(attempt.expires_at, time.monotonic() + 20)

        result = await asyncio.to_thread(
            attempt.client.qr_login_status,
            attempt.qr_id,
            attempt.code,
        )
        code_status = int(result.get("code_status", result.get("codeStatus", 0)) or 0)
        expires_in = max(0, round(attempt.expires_at - time.monotonic()))
        cookies = attempt.client.merged_cookies()
        if not (REQUIRED_COOKIE_NAMES - cookies.keys()):
            async with self._lock:
                if self._attempts.get(login_id) is not attempt:
                    raise KeyError(login_id)
            cookie_string = serialize_cookie_string(cookies)
            self._persist_cookie(cookie_string)
            async with self._lock:
                self._attempts.pop(login_id, None)
            return {
                **self._status("authenticated", code_status or 2, expires_in),
                "cookie_fields": sorted(cookies),
            }, cookie_string
        verification_type = getattr(attempt.client, "qr_verification_type", None)
        if verification_type:
            if verification_type == "120":
                await self._start_sms_verification(attempt)
                return self._sms_status(attempt), None
            if verification_type not in {"124", "209"}:
                if attempt.verification_type != verification_type:
                    attempt.verification_type = verification_type
                    attempt.expires_at = time.monotonic() + 300
                return {
                    **self._status("verification_required", code_status, expires_in),
                    "verification_type": verification_type,
                    "verification_url": attempt.client.qr_web_verification_url(),
                    "expires_in": max(0, round(attempt.expires_at - time.monotonic())),
                    "message": f"请在小红书官方页面完成验证类型 {verification_type}",
                }, None
            if not attempt.verification_rid:
                verification = await asyncio.to_thread(attempt.client.create_qr_verification)
                rid = str(verification.get("rid") or "")
                if not rid:
                    raise ConfigurationError("XHS QR verification returned no request ID")
                attempt.verification_rid = rid
                attempt.verification_type = verification_type
                attempt.verification_image = render_qr_data_uri(attempt.client.qr_verification_url(rid))
                attempt.expires_at = time.monotonic() + QR_LOGIN_TTL_SECONDS
            return self._verification_status(attempt, 1), None
        if code_status == 3:
            async with self._lock:
                self._attempts.pop(login_id, None)
            return self._status("expired", code_status, 0), None
        if code_status != 2:
            state = "scanned" if code_status == 1 else "waiting_scan"
            return self._status(state, code_status, expires_in), None

        missing = REQUIRED_COOKIE_NAMES - cookies.keys()
        raise ConfigurationError(
            f"XHS QR login completed without required cookie fields: {sorted(missing)}"
        )

    async def submit_sms(self, login_id: str, code: str) -> dict[str, object]:
        if len(code) != 6 or not code.isdigit():
            raise ConfigurationError("SMS verification code must contain exactly 6 digits")
        attempt = await self._get_attempt(login_id)
        async with attempt.poll_lock:
            if not attempt.sms_rid:
                raise ConfigurationError("No SMS verification is pending for this login")
            await asyncio.to_thread(
                attempt.client.check_sms_verification,
                attempt.sms_rid,
                code,
                attempt.sms_check_count,
            )
            attempt.sms_rid = None
            attempt.sms_receiver = None
            attempt.sms_resend_at = 0.0
            attempt.verification_type = None
            attempt.expires_at = max(attempt.expires_at, time.monotonic() + 30)
            return {
                "state": "sms_verified",
                "authenticated": False,
                "message": "短信验证通过，正在继续登录",
            }

    async def resend_sms(self, login_id: str) -> dict[str, object]:
        attempt = await self._get_attempt(login_id)
        async with attempt.poll_lock:
            if not attempt.sms_rid:
                raise ConfigurationError("No SMS verification is pending for this login")
            remaining = round(attempt.sms_resend_at - time.monotonic())
            if remaining > 0:
                return self._sms_status(attempt)
            sent = await asyncio.to_thread(attempt.client.send_sms_verification)
            rid = str(sent.get("rid") or "")
            if not rid:
                raise ConfigurationError("XHS SMS verification returned no request ID")
            attempt.sms_rid = rid
            attempt.sms_resend_at = time.monotonic() + max(1, int(sent.get("expireSec") or 60))
            return self._sms_status(attempt)

    async def _get_attempt(self, login_id: str) -> _QrLoginAttempt:
        async with self._lock:
            attempt = self._attempts.get(login_id)
        if attempt is None:
            raise KeyError(login_id)
        return attempt

    async def _start_sms_verification(self, attempt: _QrLoginAttempt) -> None:
        if attempt.sms_rid:
            return
        initialized = await asyncio.to_thread(attempt.client.init_sms_verification)
        sent = await asyncio.to_thread(attempt.client.send_sms_verification)
        rid = str(sent.get("rid") or "")
        if not rid:
            raise ConfigurationError("XHS SMS verification returned no request ID")
        attempt.verification_type = "120"
        attempt.sms_rid = rid
        attempt.sms_receiver = str(initialized.get("receiver") or "")
        attempt.sms_resend_at = time.monotonic() + max(1, int(sent.get("expireSec") or 60))
        attempt.sms_check_count = 0
        attempt.expires_at = time.monotonic() + 300

    @staticmethod
    def _sms_status(attempt: _QrLoginAttempt) -> dict[str, object]:
        return {
            "state": "sms_code_required",
            "authenticated": False,
            "verification_type": "120",
            "receiver": attempt.sms_receiver,
            "resend_in": max(0, round(attempt.sms_resend_at - time.monotonic())),
            "expires_in": max(0, round(attempt.expires_at - time.monotonic())),
        }

    @staticmethod
    def _verification_status(attempt: _QrLoginAttempt, status: int) -> dict[str, object]:
        return {
            "state": "verification_scanned" if status == 2 else "verification_waiting_scan",
            "authenticated": False,
            "verification_type": attempt.verification_type,
            "expires_in": max(0, round(attempt.expires_at - time.monotonic())),
            "qr_image": attempt.verification_image,
        }

    @staticmethod
    def _status(state: str, code_status: int, expires_in: int) -> dict[str, object]:
        return {
            "state": state,
            "code_status": code_status,
            "expires_in": expires_in,
            "authenticated": state == "authenticated",
        }

    def _persist_cookie(self, cookie_string: str) -> None:
        path = self.settings.cookie_file.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(cookie_string, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _remove_expired_locked(self, now: float) -> None:
        expired = [key for key, value in self._attempts.items() if value.expires_at <= now]
        for key in expired:
            self._attempts.pop(key, None)
