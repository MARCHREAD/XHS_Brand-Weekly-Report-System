import json
from pathlib import Path

import pytest

from collector.client import XhsClient
from collector.config import Settings
from collector.errors import XhsUpstreamError


class FakeSigner:
    def headers(self, *args, **kwargs):
        return {}


class FakeCookieJar:
    def __init__(self) -> None:
        self.values = {"web_session": "session-after-confirmation"}

    def get_dict(self):
        return dict(self.values)


class FakeResponse:
    status_code = 200
    content = json.dumps(
        {
            "code": 100000,
            "success": False,
            "msg": "成功",
            "data": {"code_status": 2},
        },
        ensure_ascii=False,
    ).encode("utf-8")


class FakeSession:
    def __init__(self) -> None:
        self.cookies = FakeCookieJar()
        self.last_url = ""

    def request(self, method, url, **kwargs):
        self.last_url = url
        return FakeResponse()


def test_qr_status_uses_nested_business_status_when_success_flag_is_false(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing.txt"),
        signer=FakeSigner(),  # type: ignore[arg-type]
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()  # type: ignore[assignment]

    result = client.qr_login_status("qr-fixture", "code-fixture")

    assert result["code_status"] == 2
    assert client.merged_cookies()["web_session"] == "session-after-confirmation"
    assert "qr_id=qr-fixture" in client.session.last_url
    assert "qrId=" not in client.session.last_url
    assert "client_public_key_base64=" in client.session.last_url
    assert "clientPublicKeyBase64=" not in client.session.last_url


def test_qr_status_accepts_top_level_business_status(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing.txt"),
        signer=FakeSigner(),  # type: ignore[arg-type]
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()  # type: ignore[assignment]
    client.session.request = lambda *args, **kwargs: type(
        "TopLevelResponse",
        (),
        {
            "status_code": 200,
            "content": json.dumps(
                {"success": False, "msg": "成功", "codeStatus": 2},
                ensure_ascii=False,
            ).encode("utf-8"),
        },
    )()

    result = client.qr_login_status("qr-fixture", "code-fixture")

    assert result["codeStatus"] == 2


def test_qr_status_tolerates_empty_http_200_status_envelope(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing.txt"),
        signer=FakeSigner(),  # type: ignore[arg-type]
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()  # type: ignore[assignment]
    client.session.request = lambda *args, **kwargs: type(
        "EmptyStatusResponse",
        (),
        {
            "status_code": 200,
            "content": json.dumps({"success": False}).encode("utf-8"),
        },
    )()

    assert client.qr_login_status("qr-fixture", "code-fixture") == {"success": False}


def test_qr_status_accepts_non_200_when_session_cookie_was_issued(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing.txt"),
        signer=FakeSigner(),  # type: ignore[arg-type]
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()  # type: ignore[assignment]
    client.session.request = lambda *args, **kwargs: type(
        "CookieIssuingResponse",
        (),
        {
            "status_code": 471,
            "content": json.dumps(
                {"success": False, "msg": "成功"},
                ensure_ascii=False,
            ).encode("utf-8"),
        },
    )()

    result = client.qr_login_status("qr-fixture", "code-fixture")

    assert result == {"success": False, "msg": "成功"}
    assert client.merged_cookies()["web_session"] == "session-after-confirmation"


def test_qr_status_accepts_non_200_business_success_as_intermediate_state(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing.txt"),
        signer=FakeSigner(),  # type: ignore[arg-type]
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()  # type: ignore[assignment]
    client.session.cookies.values = {}
    client.session.request = lambda *args, **kwargs: type(
        "BusinessSuccessResponse",
        (),
        {
            "status_code": 471,
            "content": json.dumps(
                {"code": 0, "success": True, "data": {}},
                ensure_ascii=False,
            ).encode("utf-8"),
        },
    )()

    assert client.qr_login_status("qr-fixture", "code-fixture") == {}


def test_qr_status_records_redacted_anti_abuse_headers(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing.txt"),
        signer=FakeSigner(),  # type: ignore[arg-type]
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()  # type: ignore[assignment]
    client.session.cookies.values = {}
    client.session.request = lambda *args, **kwargs: type(
        "AntiAbuseResponse",
        (),
        {
            "status_code": 471,
            "headers": {
                "verifytype": "102",
                "Resultpolicy": "400",
                "x-biz": "fixture",
                "verifyuuid": "secret-uuid",
                "verifymsg": "secret-message",
            },
            "content": json.dumps({"code": 0, "success": True, "data": {}}).encode(),
        },
    )()

    assert client.qr_login_status("qr-fixture", "code-fixture") == {}
    metadata = client.last_qr_status_metadata
    assert metadata is not None
    assert metadata["ordinary_response_headers"] == {
        "verifytype": "102",
        "resultpolicy": "400",
        "x-biz": "fixture",
    }
    assert metadata["sensitive_response_headers"] == {
        "verifyuuid": {"present": True, "length": len("secret-uuid")},
        "verifymsg": {"present": True, "length": len("secret-message")},
    }
    rendered = json.dumps(metadata)
    assert "secret-uuid" not in rendered
    assert "secret-message" not in rendered


def test_qr_status_rejects_non_200_without_session_cookie(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing.txt"),
        signer=FakeSigner(),  # type: ignore[arg-type]
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()  # type: ignore[assignment]
    client.session.cookies.values = {}
    client.session.request = lambda *args, **kwargs: type(
        "RejectedResponse",
        (),
        {
            "status_code": 471,
            "content": json.dumps({"success": False}).encode("utf-8"),
        },
    )()

    with pytest.raises(XhsUpstreamError):
        client.qr_login_status("qr-fixture", "code-fixture")


def test_user_search_and_collection_wire_contract(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing"),
        signer=FakeSigner(),
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()
    client.session.cookies.values = {}
    calls = []
    responses = [
        {"code": 0, "success": True, "data": {"users": [], "has_more": False}},
        {"code": 0, "success": True, "data": {"notes": [], "has_more": False, "cursor": ""}},
    ]

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return type("Response", (), {"status_code": 200, "content": json.dumps(responses.pop(0)).encode(), "headers": {}})()

    client.session.request = request
    client._wait_for_rate_limit = lambda: None
    client.search_users("coffee", page=1, page_size=15, search_id="sid", request_id="rid")
    client.user_collections("user-1")
    search_payload = json.loads(calls[0][2]["data"])
    assert search_payload["search_user_request"] == {
        "keyword": "coffee",
        "search_id": "sid",
        "page": 1,
        "page_size": 15,
        "biz_type": "web_search_user",
        "request_id": "rid",
    }
    assert "/api/sns/web/v2/note/collect/page" in calls[1][1]
    assert "user_id=user-1" in calls[1][1]


def test_sms_verification_uses_official_xhs_page(tmp_path: Path) -> None:
    from urllib.parse import parse_qs, urlsplit

    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing"),
        signer=FakeSigner(),
        cookie_string="a1=one; webId=two",
    )
    client._qr_verification = {
        "verifyType": "120",
        "verifyUuid": "private-fixture",
        "verifyBiz": 471,
        "verifyMsg": "encoded-message",
    }

    url = client.qr_web_verification_url()
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.netloc == "www.xiaohongshu.com"
    assert parsed.path == "/web-login/captcha"
    assert query["verifyType"] == ["120"]
    assert query["verifyUuid"] == ["private-fixture"]
    assert query["verifyBiz"] == ["471"]
    assert query["callFrom"] == ["web"]
    assert query["appId"] == ["xhs-pc-web"]


def test_sms_verification_endpoints_use_same_challenge_and_session(tmp_path: Path) -> None:
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing"),
        signer=FakeSigner(),
        cookie_string="a1=one; webId=two",
    )
    client.session = FakeSession()
    client.session.cookies.values = {}
    client._qr_verification = {
        "verifyType": "120",
        "verifyUuid": "private-fixture",
        "verifyBiz": 471,
    }
    calls = []
    responses = [
        {"code": 0, "success": True, "data": {"receiver": "138****0000"}},
        {"code": 0, "success": True, "data": {"rid": "sms-rid", "expireSec": 60}},
        {"code": 0, "success": True, "data": {}},
    ]

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return type(
            "Response",
            (),
            {"status_code": 200, "content": json.dumps(responses.pop(0)).encode(), "headers": {}},
        )()

    client.session.request = request
    client._wait_for_rate_limit = lambda: None
    assert client.init_sms_verification()["receiver"] == "138****0000"
    assert client.send_sms_verification()["rid"] == "sms-rid"
    assert client.check_sms_verification("sms-rid", "123456", 0) == {}
    assert [call[1].rsplit("/", 1)[-1] for call in calls] == ["init", "send", "check"]
    payloads = [json.loads(call[2]["data"]) for call in calls]
    assert payloads[0] == payloads[1] == {
        "verifyUuid": "private-fixture",
        "verifyType": "120",
        "verifyBiz": 471,
        "sourceSite": "",
        "captchaVersion": "2.0.0",
    }
    assert payloads[2] == {**payloads[0], "rid": "sms-rid", "code": "123456", "checkCount": 0}
    assert all(call[2]["cookies"]["a1"] == "one" for call in calls)


@pytest.mark.parametrize("verification_type", ["124", "209"])
def test_qr_verification_preserves_challenge_and_camelcase_payload(
    tmp_path: Path,
    verification_type: str,
) -> None:
    from urllib.parse import parse_qs, urlsplit

    client = XhsClient(Settings(cookie_file=tmp_path / "missing"), signer=FakeSigner(), cookie_string="a1=one; webId=two")
    client.session = FakeSession()
    client.session.cookies.values = {}
    calls = []
    responses = [
        (471, {"code": 0, "success": True, "data": {}}, {"VerifyType": verification_type, "VerifyUuid": "private-fixture"}),
        (200, {"code": 0, "success": True, "data": {"rid": "rid-fixture"}}, {}),
        (200, {"code": 0, "success": True, "data": {"status": 4}}, {}),
    ]

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        status, body, headers = responses.pop(0)
        return type("Response", (), {"status_code": status, "content": json.dumps(body).encode(), "headers": headers})()

    client.session.request = request
    client._wait_for_rate_limit = lambda: None
    client.qr_login_status("qr-fixture", "code-fixture")
    assert client.qr_verification_type == verification_type
    assert client.create_qr_verification() == {"rid": "rid-fixture"}
    assert client.qr_verification_status("rid-fixture") == {"status": 4}
    assert calls[1][1].endswith("/api/redcaptcha/v2/qr/init")
    payload = json.loads(calls[1][2]["data"])
    assert payload == {"verifyType": verification_type, "verifyUuid": "private-fixture", "verifyBiz": 471, "sourceSite": "", "captchaVersion": "2.0.0"}
    assert json.loads(calls[2][2]["data"]) == {**payload, "rid": "rid-fixture"}
    assert calls[1][2]["cookies"]["a1"] == "one"
    query = parse_qs(
        urlsplit(client.qr_verification_url("rid-fixture")).query,
        keep_blank_values=True,
    )
    assert query["rid"] == ["rid-fixture"] and query["webid"] == ["two"]
    assert ("verifyMsg" in query) is (verification_type == "124")
    assert "private-fixture" not in json.dumps(client.last_qr_status_metadata)
