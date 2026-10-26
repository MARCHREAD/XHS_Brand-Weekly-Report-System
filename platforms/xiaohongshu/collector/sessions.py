from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
import time
from typing import Any, Callable
from uuid import uuid4

from .client import XhsClient
from .config import REQUIRED_COOKIE_NAMES, ConfigurationError, Settings, parse_cookie_string
from .errors import XhsUpstreamError


ACTIVE_STATES = {"unverified", "valid", "degraded"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_cookie(value: str) -> str:
    cookies = parse_cookie_string(value)
    missing = REQUIRED_COOKIE_NAMES - cookies.keys()
    if missing:
        raise ConfigurationError(f"XHS cookie is missing required fields: {sorted(missing)}")
    return "; ".join(f"{name}={cookie_value}" for name, cookie_value in cookies.items())


def _session_key(cookie_string: str) -> str:
    cookies = parse_cookie_string(cookie_string)
    stable_identity = f"{cookies.get('a1', '')}|{cookies.get('webId', '')}"
    return hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()[:12]


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    cookie_string: str
    client: XhsClient
    state: str = "unverified"
    last_checked_at: str | None = None
    last_verified_at: str | None = None
    last_error: str | None = None
    refreshed_at: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "last_checked_at": self.last_checked_at,
            "last_verified_at": self.last_verified_at,
            "last_error": self.last_error,
            "refreshed_at": self.refreshed_at,
        }


class SessionSupervisor:
    """Validates, refreshes, persists and activates account-bound XHS sessions."""

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
        self._records: dict[str, SessionRecord] = {}
        self._operation_lock = asyncio.Lock()
        self._lock = asyncio.Lock()
        self._last_scan_at: str | None = None
        self._load_error: str | None = None
        self._generation = 0

    async def reload(self) -> bool:
        async with self._operation_lock:
            return await self._reload_once()

    async def _reload_once(self) -> bool:
        try:
            values = self.settings.cookie_strings()
            load_error = None
        except ConfigurationError as exc:
            values = []
            load_error = str(exc) if self.settings.cookie_configured() else None

        normalized = [_normalize_cookie(value) for value in values]
        async with self._lock:
            previous = self._records
            updated: dict[str, SessionRecord] = {}
            changed = False
            for value in normalized:
                session_id = _session_key(value)
                record = previous.get(session_id)
                if record is None:
                    record = SessionRecord(
                        session_id=session_id,
                        cookie_string=value,
                        client=self._client_factory(value),
                    )
                    changed = True
                elif record.cookie_string != value and record.client.effective_cookie_string() != value:
                    record = SessionRecord(
                        session_id=session_id,
                        cookie_string=value,
                        client=self._client_factory(value),
                    )
                    changed = True
                updated[session_id] = record
            if set(previous) != set(updated):
                changed = True
            self._records = updated
            self._load_error = load_error
            self._last_scan_at = _utc_now()
            if changed:
                self._generation += 1
            return changed

    async def install(self, cookie_string: str) -> dict[str, Any]:
        value = _normalize_cookie(cookie_string)
        async with self._operation_lock:
            await self._reload_once()
            session_id = _session_key(value)
            now = _utc_now()
            record = SessionRecord(
                session_id=session_id,
                cookie_string=value,
                client=self._client_factory(value),
                state="valid",
                last_checked_at=now,
                last_verified_at=now,
            )
            async with self._lock:
                self._records[session_id] = record
                self._load_error = None
                self._last_scan_at = now
                self._generation += 1
                self._persist_locked()
                return self._snapshot_locked()

    async def verify_all(self) -> dict[str, Any]:
        async with self._operation_lock:
            await self._reload_once()
            async with self._lock:
                records = list(self._records.values())
                before_active = self._active_signature_locked()

            cookie_changed = False
            for record in records:
                checked_at = _utc_now()
                try:
                    await asyncio.to_thread(record.client.session_status)
                except XhsUpstreamError as exc:
                    record.last_checked_at = checked_at
                    record.last_error = str(exc)[:240]
                    if exc.auth_failure:
                        record.state = "expired"
                    else:
                        record.state = "degraded" if record.last_verified_at else "error"
                except Exception as exc:
                    record.last_checked_at = checked_at
                    record.last_error = str(exc)[:240] or exc.__class__.__name__
                    record.state = "degraded" if record.last_verified_at else "error"
                else:
                    record.state = "valid"
                    record.last_checked_at = checked_at
                    record.last_verified_at = checked_at
                    record.last_error = None
                    effective = _normalize_cookie(record.client.effective_cookie_string())
                    if effective != record.cookie_string:
                        record.cookie_string = effective
                        record.refreshed_at = checked_at
                        cookie_changed = True

            async with self._lock:
                after_active = self._active_signature_locked()
                if before_active != after_active:
                    self._generation += 1
                if cookie_changed:
                    self._persist_locked()
                return self._snapshot_locked()

    async def active_clients(self) -> tuple[list[XhsClient], int]:
        async with self._lock:
            clients = [record.client for record in self._records.values() if record.state in ACTIVE_STATES]
            return clients, self._generation

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self._snapshot_locked()

    def _active_signature_locked(self) -> tuple[str, ...]:
        return tuple(
            sorted(record.session_id for record in self._records.values() if record.state in ACTIVE_STATES)
        )

    def _snapshot_locked(self) -> dict[str, Any]:
        records = list(self._records.values())
        counts = {
            state: sum(record.state == state for record in records)
            for state in ("unverified", "valid", "degraded", "expired", "error")
        }
        if counts["valid"]:
            state = "valid"
        elif counts["degraded"]:
            state = "degraded"
        elif counts["unverified"]:
            state = "unverified"
        elif counts["expired"]:
            state = "expired"
        elif counts["error"] or self._load_error:
            state = "error"
        else:
            state = "missing"
        return {
            "state": state,
            "configured": bool(records) or self.settings.cookie_configured(),
            "total": len(records),
            "active": sum(record.state in ACTIVE_STATES for record in records),
            "counts": counts,
            "last_scan_at": self._last_scan_at,
            "check_interval_seconds": self.settings.session_check_seconds,
            "load_error": self._load_error,
            "sessions": [record.public() for record in records],
        }

    def _persist_locked(self) -> None:
        if os.getenv("XHS_COOKIE", "").strip() or os.getenv("XHS_COOKIE_POOL", "").strip():
            return
        values = [record.cookie_string for record in self._records.values()]
        if not values:
            return
        use_pool = bool(
            self.settings.cookie_pool_file
            and (self.settings.cookie_pool_file.is_file() or len(values) > 1)
        )
        destination = self.settings.cookie_pool_file if use_pool else self.settings.cookie_file
        if destination is None:
            return
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(values) + "\n" if use_pool else values[0]
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(body, encoding="utf-8")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
