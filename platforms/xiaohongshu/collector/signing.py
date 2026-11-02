from __future__ import annotations

from threading import Lock
from typing import Any, Literal

from ._signer import SessionManager, Xhshow


class XhsSigner:
    """Owns one stateful signing context for an XHS session chain."""

    def __init__(self) -> None:
        self._client = Xhshow()
        self._session = SessionManager()
        self._lock = Lock()

    def search_id(self) -> str:
        with self._lock:
            return self._client.get_search_id()

    def search_request_id(self) -> str:
        with self._lock:
            return self._client.get_search_request_id()

    def headers(
        self,
        method: Literal["GET", "POST"],
        path: str,
        cookies: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        x_rap: bool = False,
        sign_format: Literal["xys", "xyw"] = "xys",
        user_id: str | None = None,
    ) -> dict[str, str]:
        with self._lock:
            common = {
                "uri": path,
                "cookies": cookies,
                "session": self._session,
                "x_rap": x_rap,
                "sign_format": sign_format,
                "user_id": user_id,
            }
            if method == "GET":
                return self._client.sign_headers_get(params=params, **common)
            return self._client.sign_headers_post(payload=payload, **common)
