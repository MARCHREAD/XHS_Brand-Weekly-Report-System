from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, Literal
from urllib.parse import quote, urlencode

from curl_cffi import requests

from .config import Settings, parse_cookie_string
from .errors import XhsUpstreamError
from .signing import XhsSigner
from .ssk import WebSskExchange, extract_encrypted_ssk


EDITH_HOST = "https://edith.xiaohongshu.com"
SEARCH_HOST = "https://so.xiaohongshu.com"
PGY_HOST = "https://pgy.xiaohongshu.com"
CUSTOMER_HOST = "https://customer.xiaohongshu.com"
AUTH_FAILURE_CODES = {-100, -101, 10001, 300012}
AUTH_FAILURE_MARKERS = ("无登录信息", "登录信息为空", "未登录", "login required")


def build_xhs_url(base_url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return base_url
    parts: list[str] = []
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            rendered = ",".join(str(item) for item in value)
        elif value is None:
            rendered = ""
        else:
            rendered = str(value)
        parts.append(f"{quote(str(key), safe='')}={quote(rendered, safe=',')}")
    separator = "&" if "?" in base_url and not base_url.endswith(("?", "&")) else ""
    if "?" not in base_url:
        separator = "?"
    return base_url + separator + "&".join(parts)


class XhsClient:
    def __init__(
        self,
        settings: Settings,
        signer: XhsSigner | None = None,
        cookie_string: str | None = None,
        pgy_cookie_string: str | None = None,
    ) -> None:
        self.settings = settings
        self.cookie_string = cookie_string or settings.cookie_string()
        self.cookies = parse_cookie_string(self.cookie_string)
        self.signer = signer or XhsSigner()
        self.session = requests.Session(impersonate=settings.impersonate)
        self.pgy_cookie_string = pgy_cookie_string or settings.pgy_cookie_string(self.cookie_string)
        self.pgy_cookies = parse_cookie_string(self.pgy_cookie_string)
        self.pgy_session = requests.Session(impersonate=settings.impersonate)
        self.web_ssk: str | None = None
        self.last_qr_status_metadata: dict[str, object] | None = None
        self._qr_verification: dict[str, Any] | None = None
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def _base_headers(self) -> dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://www.xiaohongshu.com",
            "referer": "https://www.xiaohongshu.com/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
        }

    def _pgy_base_headers(self) -> dict[str, str]:
        return {
            **self._base_headers(),
            "origin": PGY_HOST,
            "referer": f"{PGY_HOST}/solar/pre-trade/note/kol",
        }

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.settings.min_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def effective_cookies(self) -> dict[str, str]:
        return {**self.cookies, **self.session.cookies.get_dict()}

    def effective_cookie_string(self) -> str:
        return "; ".join(
            f"{name}={value}" for name, value in self.effective_cookies().items() if name and value
        )

    def effective_pgy_cookies(self) -> dict[str, str]:
        return {**self.pgy_cookies, **self.pgy_session.cookies.get_dict()}

    def effective_pgy_cookie_string(self) -> str:
        return "; ".join(
            f"{name}={value}"
            for name, value in self.effective_pgy_cookies().items()
            if name and value
        )

    def _request(
        self,
        method: Literal["GET", "POST"],
        host: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        x_rap: bool = False,
        sign_format: Literal["xys", "xyw"] = "xys",
        user_id: str | None = None,
        accept_qr_status_envelope: bool = False,
    ) -> dict[str, Any]:
        if host not in {EDITH_HOST, SEARCH_HOST}:
            raise ValueError(f"Unsupported XHS host: {host}")
        with self._request_lock:
            self._wait_for_rate_limit()
            cookies = self.effective_cookies()
            cookie_string = self.effective_cookie_string()
            signed = self.signer.headers(
                method,
                path,
                cookie_string,
                params=params,
                payload=payload,
                x_rap=x_rap,
                sign_format=sign_format,
                user_id=user_id,
            )
            headers = {**self._base_headers(), **signed}
            request_kwargs: dict[str, Any] = {
                "headers": headers,
                "cookies": cookies,
                "timeout": self.settings.timeout_seconds,
            }
            if payload is not None:
                request_kwargs["data"] = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            try:
                url = build_xhs_url(host + path, params) if method == "GET" else host + path
                response = self.session.request(method, url, **request_kwargs)
            except requests.RequestsError as exc:
                raise XhsUpstreamError(f"XHS transport failed: {exc}") from exc
            finally:
                self._last_request_at = time.monotonic()

        try:
            decoded = response.content.decode("utf-8")
            result = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise XhsUpstreamError(
                "XHS returned a non-JSON response",
                upstream_status=response.status_code,
            ) from exc
        if not isinstance(result, dict):
            raise XhsUpstreamError("XHS returned an unexpected JSON shape", upstream_status=response.status_code)
        if accept_qr_status_envelope:
            data_fields = result.get("data")
            code_status = result.get("code_status", result.get("codeStatus"))
            if isinstance(data_fields, dict):
                code_status = data_fields.get(
                    "code_status",
                    data_fields.get("codeStatus", code_status),
                )
            response_cookie_jar = getattr(response, "cookies", None)
            response_cookie_names: list[str] = []
            if response_cookie_jar is not None:
                try:
                    response_cookie_names = sorted(response_cookie_jar.get_dict())
                except (AttributeError, TypeError, ValueError):
                    response_cookie_names = []
            # Keep anti-abuse diagnostics useful without persisting header
            # secrets or high-entropy identifiers. Header names are treated
            # case-insensitively by normalising them to lowercase.
            response_headers = getattr(response, "headers", {})
            normalized_headers: dict[str, str] = {}
            try:
                normalized_headers = {
                    str(name).lower(): str(value)
                    for name, value in response_headers.items()
                }
            except (AttributeError, TypeError, ValueError):
                normalized_headers = {}
            ordinary_header_names = ("verifytype", "resultpolicy", "x-biz")
            sensitive_header_names = ("verifyuuid", "riskuuid", "verifymsg")
            ordinary_headers = {
                name: normalized_headers[name]
                for name in ordinary_header_names
                if name in normalized_headers
            }
            sensitive_headers = {
                name: {"present": True, "length": len(normalized_headers[name])}
                for name in sensitive_header_names
                if name in normalized_headers
            }
            self._qr_verification = None
            if response.status_code in {461, 471} and normalized_headers.get("verifytype"):
                self._qr_verification = {
                    "verifyType": normalized_headers["verifytype"],
                    "verifyUuid": normalized_headers.get("verifyuuid", ""),
                    "verifyBiz": response.status_code,
                    "verifyMsg": normalized_headers.get("verifymsg", ""),
                }
                if normalized_headers.get("x-biz"):
                    self._qr_verification["biz"] = normalized_headers["x-biz"]
            self.last_qr_status_metadata = {
                "http_status": response.status_code,
                "http_version": getattr(response, "http_version", None),
                "upstream_code": result.get("code"),
                "success": result.get("success"),
                "code_status": code_status,
                "top_level_fields": sorted(result),
                "data_fields": sorted(data_fields) if isinstance(data_fields, dict) else [],
                "response_cookie_names": response_cookie_names,
                "session_cookie_names": sorted(self.effective_cookies()),
                "has_ssk": extract_encrypted_ssk(result) is not None,
                "response_header_names": sorted(normalized_headers),
                "ordinary_response_headers": ordinary_headers,
                "sensitive_response_headers": sensitive_headers,
            }
            print(
                "[xhs-qr-status] "
                + json.dumps(
                    self.last_qr_status_metadata,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        upstream_code = result.get("code")
        success_flag_mismatch = result.get("success") is False
        qr_business_success = accept_qr_status_envelope and (
            result.get("success") is True
            and upstream_code in {0, "0", None}
        )
        qr_cookie_issued = accept_qr_status_envelope and bool(
            self.effective_cookies().get("web_session")
        )
        accepted_qr_response = accept_qr_status_envelope and (
            response.status_code == 200 or qr_business_success or qr_cookie_issued
            or self._qr_verification is not None
        )
        if (
            response.status_code != 200 and not accepted_qr_response
        ) or (
            success_flag_mismatch and not accepted_qr_response
        ):
            message = str(result.get("msg") or result.get("message") or "XHS request rejected")
            status_code = 429 if response.status_code in {429, 461, 471} else 502
            normalized_code: int | str | None = upstream_code
            try:
                normalized_code = int(upstream_code) if upstream_code is not None else None
            except (TypeError, ValueError):
                pass
            auth_failure = normalized_code in AUTH_FAILURE_CODES or any(
                marker in message.lower() for marker in AUTH_FAILURE_MARKERS
            )
            raise XhsUpstreamError(
                message,
                status_code=status_code,
                upstream_status=response.status_code,
                upstream_code=upstream_code,
                auth_failure=auth_failure,
            )
        data = result.get("data", result)
        if not isinstance(data, dict):
            return {"value": data}
        return data

    def _pgy_request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        signed: bool = True,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        with self._request_lock:
            url = build_xhs_url(PGY_HOST + path, params) if method == "GET" else PGY_HOST + path
            response = None
            last_error: requests.RequestsError | None = None
            resolved_timeout = timeout_seconds or self.settings.pgy_timeout_seconds
            resolved_retries = self.settings.pgy_max_retries if max_retries is None else max_retries
            for attempt in range(resolved_retries + 1):
                self._wait_for_rate_limit()
                cookies = self.effective_pgy_cookies()
                headers = self._pgy_base_headers()
                if signed:
                    headers.update(
                        self.signer.headers(
                            method,
                            path,
                            self.effective_pgy_cookie_string(),
                            params=params,
                            payload=payload,
                        )
                    )
                request_kwargs: dict[str, Any] = {
                    "headers": headers,
                    "cookies": cookies,
                    "timeout": resolved_timeout,
                }
                if payload is not None:
                    request_kwargs["data"] = json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                try:
                    response = self.pgy_session.request(method, url, **request_kwargs)
                    break
                except requests.RequestsError as exc:
                    last_error = exc
                    if attempt >= resolved_retries:
                        break
                    backoff = self.settings.pgy_retry_backoff_seconds * (2**attempt)
                    if backoff > 0:
                        time.sleep(backoff)
                finally:
                    self._last_request_at = time.monotonic()
            if response is None:
                attempts = resolved_retries + 1
                raise XhsUpstreamError(
                    f"Pgy transport failed after {attempts} attempts: {last_error}"
                ) from last_error

        try:
            result = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise XhsUpstreamError(
                "Pgy returned a non-JSON response",
                upstream_status=response.status_code,
            ) from exc
        if not isinstance(result, dict):
            raise XhsUpstreamError(
                "Pgy returned an unexpected JSON shape",
                upstream_status=response.status_code,
            )
        upstream_code = result.get("code")
        success = result.get("success")
        if response.status_code != 200 or success is False:
            message = str(result.get("msg") or result.get("message") or "Pgy request rejected")
            normalized_code: int | str | None = upstream_code
            try:
                normalized_code = int(upstream_code) if upstream_code is not None else None
            except (TypeError, ValueError):
                pass
            auth_failure = response.status_code in {401, 403} or normalized_code in AUTH_FAILURE_CODES or any(
                marker in message.lower() for marker in AUTH_FAILURE_MARKERS
            )
            raise XhsUpstreamError(
                message,
                status_code=429 if response.status_code == 429 else 502,
                upstream_status=response.status_code,
                upstream_code=upstream_code,
                auth_failure=auth_failure,
            )
        return result

    def pgy_user_info(self) -> dict[str, Any]:
        return self._pgy_request("GET", "/api/solar/user/info", signed=False)

    def pgy_email_ticket(self, email: str, password: str) -> str:
        payload = {
            "email": email,
            "pwd": password,
            "service": PGY_HOST,
            "source": "",
            "type": "emailPwd",
        }
        return self._pgy_cas_ticket(payload)

    def pgy_send_phone_code(self, phone: str, zone: str = "86") -> dict[str, Any]:
        return self._pgy_cas_request(
            "/api/cas/customer/web/verify-code",
            {"phone": phone, "zone": zone, "service": PGY_HOST},
        )

    def pgy_phone_ticket(self, phone: str, code: str, zone: str = "86") -> str:
        return self._pgy_cas_ticket({
            "phone": phone, "zone": zone, "verify_code": code,
            "service": PGY_HOST, "source": "", "type": "phoneVerifyCode",
        })

    def _pgy_cas_ticket(self, payload: dict[str, Any]) -> str:
        result = self._pgy_cas_request("/api/cas/customer/web/service-ticket", payload)
        data = result.get("data", result)
        ticket = str(data.get("ticket") or "") if isinstance(data, dict) else ""
        if not ticket:
            raise XhsUpstreamError("Pgy login returned no ticket")
        return ticket

    def _pgy_cas_request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            **self._pgy_base_headers(),
            "x-ratelimit-meta": "host=pgy.xiaohongshu.com",
        }
        with self._request_lock:
            self._wait_for_rate_limit()
            headers.update(
                self.signer.headers(
                    "POST",
                    path,
                    self.effective_pgy_cookie_string(),
                    payload=payload,
                )
            )
            try:
                response = self.pgy_session.request(
                    "POST",
                    CUSTOMER_HOST + path,
                    headers=headers,
                    cookies=self.effective_pgy_cookies(),
                    data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                    timeout=self.settings.timeout_seconds,
                )
            except requests.RequestsError as exc:
                raise XhsUpstreamError(f"Pgy login transport failed: {exc}") from exc
            finally:
                self._last_request_at = time.monotonic()
        try:
            result = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise XhsUpstreamError(
                "Pgy login returned a non-JSON response",
                upstream_status=response.status_code,
            ) from exc
        if not isinstance(result, dict):
            raise XhsUpstreamError(
                "Pgy login returned an unexpected JSON shape",
                upstream_status=response.status_code,
            )
        if (
            response.status_code != 200 or result.get("success") is False
            or (result.get("success") is not True and result.get("code") not in {0, "0"})
        ):
            normalized_headers = {
                str(name).lower(): str(value)
                for name, value in getattr(response, "headers", {}).items()
            }
            verification_type = normalized_headers.get("verifytype", "")
            message = str(
                result.get("msg")
                or result.get("message")
                or (f"Pgy login requires verification type {verification_type}" if verification_type else "Pgy login rejected")
            )
            raise XhsUpstreamError(
                message,
                upstream_status=response.status_code,
                upstream_code=result.get("code"),
                auth_failure=response.status_code in {401, 403} or result.get("code") in AUTH_FAILURE_CODES,
            )
        return result

    def pgy_accept_login_ticket(self, ticket: str) -> dict[str, Any]:
        return self._pgy_request(
            "POST",
            "/api/solar/login_with_ticket_new",
            payload={"ticket": ticket},
        )

    def pgy_note_detail(self, note_id: str) -> dict[str, Any]:
        return self._pgy_request(
            "GET",
            "/api/solar/index/note_detail",
            params={"noteId": note_id},
        )

    def pgy_blogger_note_cases(
        self,
        user_id: str,
        *,
        page_num: int = 1,
        page_size: int = 20,
        note_type: int = 4,
        advertise_switch: int = 1,
        order_type: int = 1,
    ) -> dict[str, Any]:
        return self._pgy_request(
            "GET",
            "/api/solar/kol/data_v2/notes_detail",
            params={
                "advertiseSwitch": advertise_switch,
                "orderType": order_type,
                "pageNumber": page_num,
                "pageSize": page_size,
                "userId": user_id,
                "noteType": note_type,
                "isThirdPlatform": 0,
            },
        )

    def pgy_blogger_notes_rate(
        self,
        user_id: str,
        *,
        business: int,
        date_type: int,
        note_type: int = 3,
        advertise_switch: int = 1,
    ) -> dict[str, Any]:
        return self._pgy_request(
            "GET",
            "/api/solar/kol/data_v3/notes_rate",
            params={
                "userId": user_id,
                "business": business,
                "noteType": note_type,
                "dateType": date_type,
                "advertiseSwitch": advertise_switch,
            },
        )

    def pgy_blogger_profile(self, user_id: str) -> dict[str, Any]:
        path = f"/api/solar/cooperator/user/blogger/{quote(user_id, safe='')}"
        return self._pgy_request("GET", path)

    def pgy_blogger_data_summary(self, user_id: str, business: int) -> dict[str, Any]:
        return self._pgy_request(
            "GET",
            "/api/pgy/kol/data/data_summary",
            params={"userId": user_id, "business": business},
        )

    def pgy_blogger_fans_summary(self, user_id: str) -> dict[str, Any]:
        return self._pgy_request(
            "GET",
            "/api/solar/kol/data_v3/fans_summary",
            params={"userId": user_id},
        )

    def pgy_blogger_fans_profile(self, user_id: str) -> dict[str, Any]:
        path = f"/api/solar/kol/data/{quote(user_id, safe='')}/fans_profile"
        return self._pgy_request("GET", path)

    def pgy_blogger_fans_history(
        self,
        user_id: str,
        increase_type: int,
        date_type: int,
    ) -> dict[str, Any]:
        path = f"/api/solar/kol/data/{quote(user_id, safe='')}/fans_overall_new_history"
        return self._pgy_request(
            "GET",
            path,
            params={"dateType": date_type, "increaseType": increase_type},
        )

    def pgy_similar_bloggers(self, user_id: str, page_num: int, page_size: int) -> dict[str, Any]:
        return self._pgy_request(
            "GET",
            "/api/solar/kol/get_similar_kol",
            params={"userId": user_id, "pageNum": page_num, "pageSize": page_size},
        )

    def pgy_blogger_track(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._pgy_request(
            "POST",
            "/api/solar/cooperator/blogger/track",
            payload=payload,
            timeout_seconds=min(8.0, self.settings.pgy_timeout_seconds),
            max_retries=0,
        )

    def pgy_blogger_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._pgy_request("POST", "/api/solar/cooperator/blogger/v2", payload=payload)

    def pgy_content_tags(self) -> dict[str, Any]:
        return self._pgy_request("GET", "/api/solar/cooperator/content/tag_tree")

    def pgy_filter_config(self) -> dict[str, Any]:
        return self._pgy_request("GET", "/api/solar/kol/get_select_kol_tags_config_v2")

    def pgy_consumer_behavior(self) -> dict[str, Any]:
        return self._pgy_request("GET", "/api/pgy/kol/consume_behavior")

    def pgy_areas(self, *, blogger: bool = False) -> dict[str, Any]:
        params = {"type": 2} if blogger else None
        return self._pgy_request("GET", "/api/solar/area/get_areas", params=params)

    def pgy_activities(self) -> dict[str, Any]:
        return self._pgy_request("GET", "/api/solar/cooperator/get_all_activities")

    def pgy_special_industry(self) -> dict[str, Any]:
        return self._pgy_request("GET", "/api/pgy/kol/get_industry_tag")

    def homefeed(self, *, category: str = "homefeed_recommend", cursor_score: str = "", num: int = 20) -> dict[str, Any]:
        payload = {
            "cursor_score": cursor_score,
            "num": num,
            "refresh_type": 1 if not cursor_score else 3,
            "note_index": num - 1,
            "unread_begin_note_id": "",
            "unread_end_note_id": "",
            "unread_note_count": 0,
            "category": category,
            "search_key": "",
            "need_num": min(6, num),
            "image_formats": ["jpg", "webp", "avif"],
            "need_filter_image": False,
        }
        return self._request("POST", EDITH_HOST, "/api/sns/web/v1/homefeed", payload=payload, x_rap=True)

    def create_qr_login(self) -> dict[str, Any]:
        return self._request(
            "POST",
            EDITH_HOST,
            "/api/sns/web/v1/login/qrcode/create",
            payload={},
            x_rap=True,
        )

    def qr_login_status(self, qr_id: str, code: str) -> dict[str, Any]:
        exchange = WebSskExchange()
        result = self._request(
            "GET",
            EDITH_HOST,
            "/api/sns/web/v1/login/qrcode/status",
            params={
                "qr_id": qr_id,
                "code": code,
                # The web client adds this as clientPublicKeyBase64 before its
                # request transformer runs.  The actual wire key is snake_case,
                # just like qrId becomes qr_id.
                "client_public_key_base64": exchange.client_public_key_base64,
            },
            accept_qr_status_envelope=True,
        )
        encrypted_ssk = extract_encrypted_ssk(result)
        if encrypted_ssk:
            self.web_ssk = exchange.accept_encrypted_ssk(encrypted_ssk)
        return result

    def merged_cookies(self) -> dict[str, str]:
        return self.effective_cookies()

    @property
    def qr_verification_type(self) -> str | None:
        return str(self._qr_verification["verifyType"]) if self._qr_verification else None

    def _qr_verification_payload(self) -> dict[str, Any]:
        challenge = self._qr_verification
        if (
            not challenge
            or challenge["verifyType"] not in {"124", "209"}
            or not challenge["verifyUuid"]
        ):
            raise ValueError("QR verification context is missing or unsupported")
        return {
            key: value for key, value in {
                **challenge, "sourceSite": "", "captchaVersion": "2.0.0",
            }.items() if key != "verifyMsg"
        }

    def create_qr_verification(self) -> dict[str, Any]:
        # Official FeCaptcha QRCodeLite sends camelCase JSON (transform:false).
        return self._request(
            "POST", EDITH_HOST, "/api/redcaptcha/v2/qr/init",
            payload=self._qr_verification_payload(),
        )

    def qr_verification_status(self, rid: str) -> dict[str, Any]:
        return self._request(
            "POST", EDITH_HOST, "/api/redcaptcha/v2/qr/status/query",
            payload={**self._qr_verification_payload(), "rid": rid},
        )

    def qr_verification_url(self, rid: str) -> str:
        challenge = self._qr_verification or {}
        self._qr_verification_payload()  # Validate before rendering an account QR.
        params = {
            "rid": rid,
            "verifyUuid": challenge["verifyUuid"],
            "verifyBiz": challenge["verifyBiz"],
            "verifyType": challenge["verifyType"],
            "webid": self.effective_cookies().get("webId", ""),
        }
        if challenge["verifyType"] == "124":
            params["verifyMsg"] = challenge.get("verifyMsg", "")
        return "https://www.xiaohongshu.com/web-login/qrcode-transfer?" + urlencode(params)

    def qr_web_verification_url(self) -> str:
        challenge = self._qr_verification
        if not challenge or not challenge.get("verifyUuid"):
            raise ValueError("Web verification context is missing")
        params = {
            "redirectPath": "https://www.xiaohongshu.com/",
            "callFrom": "web",
            "verifyUuid": challenge["verifyUuid"],
            "verifyType": challenge["verifyType"],
            "verifyBiz": challenge["verifyBiz"],
            "appId": "xhs-pc-web",
        }
        if challenge.get("biz"):
            params["biz"] = challenge["biz"]
        if challenge.get("verifyMsg"):
            params["verifyMsg"] = challenge["verifyMsg"]
        return "https://www.xiaohongshu.com/web-login/captcha?" + urlencode(params)

    def _sms_verification_payload(self) -> dict[str, Any]:
        challenge = self._qr_verification
        if (
            not challenge
            or challenge["verifyType"] != "120"
            or not challenge.get("verifyUuid")
        ):
            raise ValueError("SMS verification context is missing or unsupported")
        return {
            key: value
            for key, value in {
                "verifyUuid": challenge["verifyUuid"],
                "verifyType": challenge["verifyType"],
                "verifyBiz": challenge["verifyBiz"],
                "biz": challenge.get("biz"),
                "sourceSite": "",
                "captchaVersion": "2.0.0",
            }.items()
            if value is not None
        }

    def init_sms_verification(self) -> dict[str, Any]:
        return self._request(
            "POST",
            EDITH_HOST,
            "/api/redcaptcha/v2/vc/init",
            payload=self._sms_verification_payload(),
        )

    def send_sms_verification(self) -> dict[str, Any]:
        return self._request(
            "POST",
            EDITH_HOST,
            "/api/redcaptcha/v2/vc/send",
            payload=self._sms_verification_payload(),
        )

    def check_sms_verification(self, rid: str, code: str, check_count: int) -> dict[str, Any]:
        return self._request(
            "POST",
            EDITH_HOST,
            "/api/redcaptcha/v2/vc/check",
            payload={
                **self._sms_verification_payload(),
                "rid": rid,
                "code": code,
                "checkCount": check_count,
            },
        )

    def session_status(self) -> dict[str, Any]:
        return self._request(
            "GET",
            EDITH_HOST,
            "/api/sns/web/v1/user/selfinfo",
        )

    def search_notes(
        self,
        keyword: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search_id: str | None = None,
        sort: str = "general",
        note_type: int = 0,
    ) -> dict[str, Any]:
        payload = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": search_id or self.signer.search_id(),
            "sort": sort,
            "note_type": note_type,
            "image_formats": ["jpg", "webp", "avif"],
            "source": "web_search_result_notes",
        }
        return self._request("POST", SEARCH_HOST, "/api/sns/web/v2/search/notes", payload=payload, x_rap=True)

    def note_detail(self, note_id: str, xsec_token: str, *, xsec_source: str = "pc_search") -> dict[str, Any]:
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        return self._request("POST", EDITH_HOST, "/api/sns/web/v1/feed", payload=payload, x_rap=True)

    def user_profile(
        self,
        user_id: str,
        *,
        xsec_token: str = "",
        xsec_source: str = "pc_search",
    ) -> dict[str, Any]:
        params = {
            "target_user_id": user_id,
            "image_formats": "jpg,webp,avif",
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        return self._request(
            "GET",
            EDITH_HOST,
            "/api/sns/web/v1/user/otherinfo",
            params=params,
            user_id=user_id,
        )

    def search_users(
        self,
        keyword: str,
        *,
        page: int,
        page_size: int,
        search_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        payload = {
            "search_user_request": {
                "keyword": keyword,
                "search_id": search_id,
                "page": page,
                "page_size": page_size,
                "biz_type": "web_search_user",
                "request_id": request_id,
            }
        }
        return self._request(
            "POST",
            EDITH_HOST,
            "/api/sns/web/v1/search/usersearch",
            payload=payload,
            x_rap=True,
        )

    def user_collections(
        self,
        user_id: str,
        *,
        cursor: str = "",
        num: int = 30,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            EDITH_HOST,
            "/api/sns/web/v2/note/collect/page",
            params={
                "cursor": cursor,
                "num": num,
                "user_id": user_id,
                "image_formats": "jpg,webp,avif",
            },
            x_rap=True,
            user_id=user_id,
        )

    def user_notes(
        self,
        user_id: str,
        *,
        cursor: str = "",
        num: int = 30,
        xsec_token: str,
        xsec_source: str = "pc_search",
    ) -> dict[str, Any]:
        params = {
            "num": num,
            "cursor": cursor,
            "user_id": user_id,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
        }
        return self._request(
            "GET",
            EDITH_HOST,
            "/api/sns/web/v1/user_posted",
            params=params,
            x_rap=True,
            user_id=user_id,
        )

    def comments(self, note_id: str, xsec_token: str, *, cursor: str = "") -> dict[str, Any]:
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": "",
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        return self._request("GET", EDITH_HOST, "/api/sns/web/v2/comment/page", params=params)

    def sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str,
        *,
        cursor: str = "",
        num: int = 10,
    ) -> dict[str, Any]:
        params = {
            "note_id": note_id,
            "root_comment_id": root_comment_id,
            "num": num,
            "cursor": cursor,
            "image_formats": "jpg,webp,avif",
            "top_comment_id": "",
            "xsec_token": xsec_token,
        }
        return self._request("GET", EDITH_HOST, "/api/sns/web/v2/comment/sub/page", params=params)
