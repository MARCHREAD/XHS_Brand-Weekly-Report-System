import asyncio
import json
from pathlib import Path

import pytest
from curl_cffi import requests as curl_requests
from fastapi.testclient import TestClient
from pydantic import ValidationError

from collector.api import create_app
from collector.client import XhsClient
from collector.config import Settings
from collector.errors import XhsUpstreamError
from collector.pgy import (
    NumericRange,
    PgyBloggerDetailRequest,
    PgyBloggerSearchRequest,
    PgyNoteDetailRequest,
    PgySimilarBloggerRequest,
    parse_note_link,
    tree_paths_by_name,
)
from collector.service import CollectorService
from collector.runtime import SessionPool


COOKIE = "a1=one; web_session=two; webId=three; solar.beaker.session.id=four"
NOTE_ID = "6aa9fdf500000000260387df"
NOTE_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token=xsec-1&xsec_source=pc_search"


class FakeSigner:
    def __init__(self) -> None:
        self.calls = []

    def headers(self, method, path, cookies, **kwargs):
        self.calls.append((method, path, cookies, kwargs))
        return {"x-s": "signed", "x-t": "1", "x-s-common": "common"}

    def search_id(self):
        return "search-fixture"


class FakeCookieJar:
    def get_dict(self):
        return {}


class FakeHttpSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.cookies = FakeCookieJar()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        body = self.responses.pop(0)
        if isinstance(body, BaseException):
            raise body
        return type(
            "Response",
            (),
            {"status_code": 200, "content": json.dumps(body).encode("utf-8")},
        )()


def test_pgy_search_maps_all_filter_groups() -> None:
    request = PgyBloggerSearchRequest.model_validate(
        {
            "keyword": "护肤",
            "column": "fansCount",
            "sort": "asc",
            "page_num": 2,
            "page_size": 20,
            "goal": {"market_target": {"target": "exposure"}},
            "blogger": {
                "content_tag": ["美妆", "面部保养"],
                "personal_tags": ["妈妈"],
                "feature_tags": ["vlog"],
                "content_theme": ["通用"],
                "audience20": ["自在户外"],
                "note_scene": ["汽车 理性决策"],
                "consumer_behavior": ["内容行为预估 汽车"],
                "industry_crowd": ["17121263"],
                "gender": "女",
                "location": ["上海"],
                "signed": 1,
            },
            "fans": {
                "count": {"min": 10000, "max": 50000},
                "age": 3,
                "gender": 2,
                "location": ["浙江", "杭州"],
                "marital_status": 1,
                "consumption_level": 2,
                "child_age": [4],
                "device_price": ["5000-5999"],
                "device_brand": ["苹果"],
            },
            "note": {
                "imp_median": {"min": 1000},
                "read_median": {"max": 5000},
                "inter_median": {"min": 100, "max": 500},
                "thousand_like_percent": {"min": 10, "max": 30},
                "note_type": 1,
            },
            "coop": {
                "pic_price": {"max": 3000},
                "video_price": {"min": 5000},
                "order_count": {"min": 1},
                "reply_48h_ratio": {"min": 90},
                "industry": "美妆个护",
                "brand_ids": ["brand-1"],
                "exclude_brands": True,
                "imp_median": {"min": 2000},
                "pic_cpm": {"max": 50},
                "pic_read_price": {"max": 2},
                "pic_engage_cost": {"max": 8},
            },
            "live": {
                "live_count": {"min": 1},
                "avg_viewer": {"min": 1000},
                "avg_gmv": {"max": 100000},
            },
            "flags": {
                "is_star": True,
                "high_quality": True,
                "new_high_quality": True,
                "note_and_live": True,
                "filter_intention": True,
                "industry_first": "美妆个护",
                "industry_second": "护肤",
                "activity_codes": ["activity-1"],
                "exclude_low_active": True,
                "exclude_fans_down": True,
                "exclude_cooperated": True,
                "exclude_invited": True,
            },
        }
    )

    payload = request.to_upstream(fans_locations=["中国 浙江", "中国 浙江 杭州"])

    assert payload["contentTag"] == ["美妆", "面部保养"]
    assert payload["fansLocation"] == ["中国 浙江", "中国 浙江 杭州"]
    assert payload["fansNumberLower"] == 10000
    assert payload["fansNumberUpper"] == 50000
    assert payload["accumCommonImpMedinNum30d"] == [1000, -1]
    assert payload["readMidNor30"] == [0, 5000]
    assert payload["thousandLikePercent30"] == [0.1, 0.3]
    assert payload["inviteReply48hNumRatio"] == [0.9, -1]
    assert payload["notePriceLower"] == 0
    assert payload["notePriceUpper"] == 3000
    assert payload["filterList"] == [
        {"field": "kliveCnt30d", "value": [1, -1]},
        {"field": "avgLiveViewerNum", "value": [1000, -1]},
        {"field": "avgAgmv90d", "value": [0, 100000]},
    ]
    assert payload["flagList"] == [
        {"flagType": "HAS_BRAND_COOP_BUYER_AUTH", "flagValue": "1"},
        {"flagType": "IS_HIGH_QUALITY", "flagValue": "1"},
    ]


def test_pgy_validation_rejects_invalid_limits_and_fields() -> None:
    with pytest.raises(ValidationError):
        NumericRange()
    with pytest.raises(ValidationError):
        PgySimilarBloggerRequest(user_id="u1", page_size=5)
    with pytest.raises(ValidationError):
        PgyBloggerSearchRequest.model_validate({"page_num": 251})
    with pytest.raises(ValidationError):
        PgyBloggerSearchRequest.model_validate({"page_num": 250, "pages": 2})
    with pytest.raises(ValidationError):
        PgyBloggerSearchRequest.model_validate({"fans": {"count_typo": {"min": 1}}})


def test_fans_location_names_expand_to_full_paths() -> None:
    tree = [
        {
            "name": "中国",
            "children": [
                {"name": "浙江", "children": [{"name": "杭州"}]},
                {"name": "吉林", "children": [{"name": "吉林"}]},
            ],
        }
    ]
    assert tree_paths_by_name(tree, ["浙江", "杭州", "吉林"]) == [
        "中国 浙江",
        "中国 浙江 杭州",
        "中国 吉林",
        "中国 吉林 吉林",
    ]


def test_pgy_client_preserves_raw_envelope_and_uses_pgy_headers(tmp_path: Path) -> None:
    signer = FakeSigner()
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing", pgy_cookie_file=tmp_path / "missing-pgy"),
        signer=signer,  # type: ignore[arg-type]
        cookie_string=COOKIE,
    )
    response = {"code": 0, "msg": "success", "success": True, "data": {"noteId": "n1"}}
    client.pgy_session = FakeHttpSession([response])  # type: ignore[assignment]
    client._wait_for_rate_limit = lambda: None

    assert client.pgy_note_detail("n1") == response
    method, url, kwargs = client.pgy_session.calls[0]
    assert method == "GET"
    assert url.endswith("/api/solar/index/note_detail?noteId=n1")
    assert kwargs["headers"]["origin"] == "https://pgy.xiaohongshu.com"
    assert kwargs["headers"]["referer"].endswith("/solar/pre-trade/note/kol")
    assert signer.calls[0][1] == "/api/solar/index/note_detail"
    assert signer.calls[0][3]["params"] == {"noteId": "n1"}


def test_pgy_client_builds_blogger_note_metric_requests(tmp_path: Path) -> None:
    signer = FakeSigner()
    client = XhsClient(
        Settings(cookie_file=tmp_path / "missing", pgy_cookie_file=tmp_path / "missing-pgy"),
        signer=signer,  # type: ignore[arg-type]
        cookie_string=COOKIE,
    )
    response = {"code": 0, "msg": "success", "success": True, "data": {"list": []}}
    client.pgy_session = FakeHttpSession([response, response])  # type: ignore[assignment]
    client._wait_for_rate_limit = lambda: None

    client.pgy_blogger_note_cases("u1", page_num=2)
    client.pgy_blogger_notes_rate("u1", business=1, date_type=2)

    case_params = signer.calls[0][3]["params"]
    assert signer.calls[0][1] == "/api/solar/kol/data_v2/notes_detail"
    assert case_params["userId"] == "u1"
    assert case_params["pageNumber"] == 2
    assert case_params["pageSize"] == 20
    rate_params = signer.calls[1][3]["params"]
    assert signer.calls[1][1] == "/api/solar/kol/data_v3/notes_rate"
    assert rate_params == {
        "userId": "u1",
        "business": 1,
        "noteType": 3,
        "dateType": 2,
        "advertiseSwitch": 1,
    }


def test_pgy_client_retries_transport_errors_with_fresh_signatures(tmp_path: Path) -> None:
    signer = FakeSigner()
    settings = Settings(
        cookie_file=tmp_path / "missing",
        pgy_cookie_file=tmp_path / "missing-pgy",
        min_delay_seconds=0,
        pgy_timeout_seconds=1,
        pgy_max_retries=1,
        pgy_retry_backoff_seconds=0,
    )
    client = XhsClient(settings, signer=signer, cookie_string=COOKIE)  # type: ignore[arg-type]
    response = {"code": 0, "msg": "success", "success": True, "data": {"kols": []}}
    client.pgy_session = FakeHttpSession(
        [curl_requests.RequestsError("timeout"), response]
    )  # type: ignore[assignment]

    result = client.pgy_similar_bloggers("u1", 1, 4)

    assert result == response
    assert len(client.pgy_session.calls) == 2
    assert len(signer.calls) == 2
    assert all(call[2]["timeout"] == 1 for call in client.pgy_session.calls)


def test_pgy_track_uses_fast_timeout_without_retry(tmp_path: Path) -> None:
    signer = FakeSigner()
    settings = Settings(
        cookie_file=tmp_path / "missing",
        pgy_cookie_file=tmp_path / "missing-pgy",
        min_delay_seconds=0,
        pgy_timeout_seconds=20,
        pgy_max_retries=3,
        pgy_retry_backoff_seconds=0,
    )
    client = XhsClient(settings, signer=signer, cookie_string=COOKIE)  # type: ignore[arg-type]
    client.pgy_session = FakeHttpSession(
        [curl_requests.RequestsError("timeout")]
    )  # type: ignore[assignment]

    with pytest.raises(XhsUpstreamError, match="after 1 attempts"):
        client.pgy_blogger_track({"pageNum": 1})

    assert len(client.pgy_session.calls) == 1
    assert client.pgy_session.calls[0][2]["timeout"] == 8


def test_pgy_note_link_parser_accepts_full_and_html_escaped_urls() -> None:
    assert parse_note_link(NOTE_URL) == (NOTE_ID, "xsec-1", "pc_search")
    assert parse_note_link(NOTE_URL.replace("&", "&amp;")) == (NOTE_ID, "xsec-1", "pc_search")


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.xiaohongshu.com/explore/{NOTE_ID}",
        f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token=xsec-1",
        "https://www.xiaohongshu.com/explore/not-a-note?xsec_token=x&xsec_source=pc_search",
    ],
)
def test_pgy_note_link_parser_rejects_incomplete_urls(url: str) -> None:
    with pytest.raises(ValueError):
        parse_note_link(url)


class FakePgyClient:
    signer = FakeSigner()

    @staticmethod
    def _response(name):
        return {"code": 0, "msg": "success", "success": True, "data": {"section": name}}

    def pgy_blogger_profile(self, user_id):
        return self._response("profile")

    def pgy_blogger_data_summary(self, user_id, business):
        return self._response(f"data-{business}")

    def pgy_blogger_fans_summary(self, user_id):
        return self._response("fans-summary")

    def pgy_blogger_fans_profile(self, user_id):
        return self._response("fans-profile")

    def pgy_blogger_fans_history(self, user_id, increase_type, date_type):
        return self._response(f"history-{increase_type}-{date_type}")


def test_pgy_blogger_detail_builds_double_envelope(tmp_path: Path) -> None:
    service = CollectorService(
        Settings(cookie_file=tmp_path / "missing"),
        client=FakePgyClient(),  # type: ignore[arg-type]
    )
    request = PgyBloggerDetailRequest(user_id="u1", business=1, increase_type=2, date_type=2)

    result = asyncio.run(service.pgy_blogger_detail(request))

    assert result["success"] is True
    assert result["data"]["profile"]["section"] == "profile"
    assert result["data"]["data_summary"]["section"] == "data-1"
    assert result["data"]["fans_history"]["section"] == "history-2-2"


class FakeSquarePgyClient:
    signer = FakeSigner()

    def __init__(self) -> None:
        self.track_payload = None
        self.search_payloads = []

    @staticmethod
    def response(data):
        return {"code": 0, "msg": "success", "success": True, "data": data}

    def pgy_filter_config(self):
        return self.response({"featureTags": []})

    def pgy_content_tags(self):
        return self.response([])

    def pgy_consumer_behavior(self):
        return self.response({"consumeBehaviorTag": []})

    def pgy_areas(self, *, blogger=False):
        if blogger:
            return self.response({"list": []})
        return self.response(
            {
                "list": [
                    {
                        "name": "中国",
                        "children": [
                            {"name": "浙江", "children": [{"name": "杭州"}]},
                        ],
                    }
                ]
            }
        )

    def pgy_activities(self):
        return self.response([])

    def pgy_special_industry(self):
        return self.response({"industryTag": []})

    def pgy_blogger_track(self, payload):
        self.track_payload = payload
        return self.response({"trackId": "track-1"})

    def pgy_blogger_search(self, payload):
        self.search_payloads.append(payload)
        page = payload["pageNum"]
        return self.response(
            {"kols": [{"userId": "u1"}, {"userId": f"u{page}"}], "total": 5000}
        )


def test_pgy_square_uses_filter_dictionary_track_and_list(tmp_path: Path) -> None:
    client = FakeSquarePgyClient()
    service = CollectorService(
        Settings(cookie_file=tmp_path / "missing"),
        client=client,  # type: ignore[arg-type]
    )
    request = PgyBloggerSearchRequest.model_validate(
        {
            "keyword": "咖啡",
            "fans": {"location": ["浙江", "杭州"]},
            "pages": 2,
        }
    )

    result = asyncio.run(service.pgy_search_bloggers(request))

    assert result["data"]["total"] == 5000
    assert client.track_payload["fansLocation"] == ["中国 浙江", "中国 浙江 杭州"]
    assert "trackId" not in client.track_payload
    assert [payload["pageNum"] for payload in client.search_payloads] == [1, 2]
    assert all(payload["trackId"] == "track-1" for payload in client.search_payloads)
    assert [kol["userId"] for kol in result["data"]["kols"]] == ["u1", "u2"]
    assert result["data"]["pages_requested"] == 2
    assert result["data"]["pages_fetched"] == 2
    assert result["data"]["returned"] == 2


class PartiallyFailingSquarePgyClient(FakeSquarePgyClient):
    def pgy_blogger_search(self, payload):
        if payload["pageNum"] == 2:
            raise XhsUpstreamError("Pgy transport failed after 3 attempts: timeout")
        return super().pgy_blogger_search(payload)


def test_pgy_square_keeps_other_pages_when_one_page_times_out(tmp_path: Path) -> None:
    client = PartiallyFailingSquarePgyClient()
    service = CollectorService(
        Settings(cookie_file=tmp_path / "missing"),
        client=client,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.pgy_search_bloggers(PgyBloggerSearchRequest.model_validate({"pages": 3}))
    )

    assert result["data"]["pages_attempted"] == 3
    assert result["data"]["pages_fetched"] == 2
    assert result["data"]["failed_pages"] == [
        {"page": 2, "error": "Pgy transport failed after 3 attempts: timeout"}
    ]
    assert [kol["userId"] for kol in result["data"]["kols"]] == ["u1", "u3"]


class TrackFailingSquarePgyClient(FakeSquarePgyClient):
    def pgy_blogger_track(self, payload):
        self.track_payload = payload
        raise XhsUpstreamError("Pgy transport failed after 3 attempts: timeout")


def test_pgy_square_continues_without_track_id_after_transport_failure(tmp_path: Path) -> None:
    client = TrackFailingSquarePgyClient()
    service = CollectorService(
        Settings(cookie_file=tmp_path / "missing"),
        client=client,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.pgy_search_bloggers(PgyBloggerSearchRequest.model_validate({"pages": 1}))
    )

    assert result["data"]["pages_fetched"] == 1
    assert result["data"]["track_error"] == "Pgy transport failed after 3 attempts: timeout"
    assert "trackId" not in client.search_payloads[0]


def test_pgy_square_reuses_supplied_track_id_without_tracking_request(tmp_path: Path) -> None:
    client = FakeSquarePgyClient()
    service = CollectorService(
        Settings(cookie_file=tmp_path / "missing"),
        client=client,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.pgy_search_bloggers(
            PgyBloggerSearchRequest.model_validate(
                {"pages": 1, "page_num": 2, "track_id": "track-reused"}
            )
        )
    )

    assert client.track_payload is None
    assert client.search_payloads[0]["trackId"] == "track-reused"
    assert result["data"]["trackId"] == "track-reused"


class FakeSimilarPgyClient:
    signer = FakeSigner()

    def __init__(self) -> None:
        self.pages = []

    def pgy_similar_bloggers(self, user_id, page_num, page_size):
        self.pages.append(page_num)
        rows = [{"userId": "u1"}, {"userId": f"u{page_num}"}] if page_num < 3 else []
        return {"success": True, "data": {"kols": rows, "total": 10}}


def test_pgy_similar_collects_pages_deduplicates_and_stops_on_empty(tmp_path: Path) -> None:
    client = FakeSimilarPgyClient()
    service = CollectorService(
        Settings(cookie_file=tmp_path / "missing"),
        client=client,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.pgy_similar_bloggers(PgySimilarBloggerRequest(user_id="u0", pages=5))
    )

    assert client.pages == [1, 2, 3]
    assert [kol["userId"] for kol in result["data"]["kols"]] == ["u1", "u2"]
    assert result["data"]["pages_requested"] == 5
    assert result["data"]["pages_fetched"] == 3
    assert result["data"]["last_page"] == 3


class FakePgyService:
    async def pgy_note_detail(self, body):
        assert isinstance(body, PgyNoteDetailRequest)
        note_id, token, source = body.parameters()
        assert token == "xsec-1"
        assert source == "pc_search"
        return {"code": 0, "msg": "success", "success": True, "data": {"noteId": note_id}}


def test_pgy_api_keeps_outer_and_upstream_envelopes(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(cookie_file=tmp_path / "missing"),
        service=FakePgyService(),  # type: ignore[arg-type]
    )
    client = TestClient(app)

    response = client.post(
        "/v1/xhs/pgy/get_note_detail",
        json={"note_url": NOTE_URL},
    )
    missing_token = client.post(
        "/v1/xhs/pgy/get_note_detail",
        json={"note_url": f"https://www.xiaohongshu.com/explore/{NOTE_ID}"},
    )
    invalid = client.post(
        "/v1/xhs/pgy/get_note_detail",
        json={"note_url": NOTE_URL, "typo": True},
    )

    assert response.status_code == 200
    assert response.json()["data"]["data"]["noteId"] == NOTE_ID
    assert response.json()["data"]["success"] is True
    assert missing_token.status_code == 422
    assert invalid.status_code == 422


class EmptySessionSupervisor:
    async def reload(self):
        return False

    async def snapshot(self):
        return {"state": "expired", "configured": True, "active": 0, "sessions": []}

    async def verify_all(self):
        return await self.snapshot()

    async def active_clients(self):
        return [], 0


def test_pgy_api_does_not_require_an_active_xhs_session(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(cookie_file=tmp_path / "missing"),
        pgy_service=FakePgyService(),  # type: ignore[arg-type]
        session_supervisor=EmptySessionSupervisor(),  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/xhs/pgy/get_note_detail",
            json={"note_url": NOTE_URL},
        )

    assert response.status_code == 200
    assert response.json()["data"]["data"]["noteId"] == NOTE_ID


class PermissionFallbackClient:
    signer = FakeSigner()

    def __init__(self):
        self.case_pages = []
        self.rate_calls = []

    def pgy_note_detail(self, note_id):
        raise XhsUpstreamError(
            "permission denied",
            upstream_status=200,
            upstream_code=-10040000,
        )

    def note_detail(self, note_id, xsec_token, *, xsec_source):
        return {
            "items": [
                {
                    "id": note_id,
                    "xsec_token": xsec_token,
                    "xsec_source": xsec_source,
                    "note_card": {
                        "note_id": note_id,
                        "title": "fallback note",
                        "user": {"user_id": "u1", "nickname": "author"},
                    },
                }
            ]
        }

    def pgy_blogger_note_cases(self, user_id, *, page_num, page_size):
        self.case_pages.append(page_num)
        rows = (
            [{"noteId": "other", "readNum": 8}]
            if page_num == 1
            else [{"noteId": NOTE_ID, "readNum": 3637, "likeNum": 1122, "collectNum": 153, "brandName": "brand"}]
        )
        return {"success": True, "data": {"list": rows, "total": 21}}

    def pgy_blogger_notes_rate(self, user_id, *, business, date_type):
        self.rate_calls.append((business, date_type))
        rows = []
        if business == 1 and date_type == 1:
            rows = [{"noteId": NOTE_ID, "impNum": 28101, "readNum": 3637, "likeNum": 1122}]
        return {"success": True, "data": {"notes": rows}}


def test_pgy_note_permission_error_matches_blogger_metrics(tmp_path: Path) -> None:
    settings = Settings(cookie_file=tmp_path / "missing")
    client = PermissionFallbackClient()
    service = CollectorService(
        settings,
        client=client,  # type: ignore[arg-type]
        xhs_fallback_pool=SessionPool(settings, [client]),  # type: ignore[list-item]
    )

    result = asyncio.run(service.pgy_note_detail(PgyNoteDetailRequest(note_url=NOTE_URL)))

    assert result["success"] is True
    assert result["data"]["note_id"] == NOTE_ID
    assert result["data"]["title"] == "fallback note"
    assert result["data"]["impNum"] == 28101
    assert result["data"]["readNum"] == 3637
    assert result["data"]["favNum"] == 153
    assert result["data"]["data_source"] == "pgy_blogger_metrics+xhs_web"
    assert result["data"]["pgy_access"] == "matched"
    assert client.case_pages == [1, 2]
    assert client.rate_calls == [(1, 1)]


class MissingPgyMetricsClient(PermissionFallbackClient):
    def pgy_blogger_note_cases(self, user_id, *, page_num, page_size):
        self.case_pages.append(page_num)
        return {"success": True, "data": {"list": [], "total": 0}}

    def pgy_blogger_notes_rate(self, user_id, *, business, date_type):
        self.rate_calls.append((business, date_type))
        return {"success": True, "data": {"notes": []}}


def test_pgy_note_falls_back_when_note_is_not_in_blogger_metrics(tmp_path: Path) -> None:
    settings = Settings(cookie_file=tmp_path / "missing")
    client = MissingPgyMetricsClient()
    service = CollectorService(
        settings,
        client=client,  # type: ignore[arg-type]
        xhs_fallback_pool=SessionPool(settings, [client]),  # type: ignore[list-item]
    )

    result = asyncio.run(service.pgy_note_detail(PgyNoteDetailRequest(note_url=NOTE_URL)))

    assert result["data"]["data_source"] == "xhs_web_fallback"
    assert result["data"]["pgy_access"] == "not_listed"
    assert result["data"]["impNum"] is None
    assert client.case_pages == [1]
    assert client.rate_calls == [(0, 1), (1, 1), (0, 2), (1, 2)]
