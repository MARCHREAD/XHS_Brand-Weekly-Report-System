import asyncio
from pathlib import Path

from collector.config import Settings
from collector.service import CollectorService


class FakeSigner:
    def search_id(self) -> str:
        return "search-fixture"

    def search_request_id(self) -> str:
        return "request-fixture"


class FakeClient:
    signer = FakeSigner()

    def search_notes(self, keyword, **kwargs):
        return {
            "items": [
                {
                    "id": "6aa28418000000002b01190a",
                    "xsec_token": "token",
                    "note_card": {
                        "type": "normal",
                        "display_title": keyword,
                        "user": {"user_id": "u1", "nickname": "author"},
                    },
                }
            ],
            "has_more": False,
        }

    def note_detail(self, note_id, xsec_token, **kwargs):
        return {
            "items": [
                {
                    "note_card": {
                        "note_id": note_id,
                        "title": "detail",
                        "desc": "description",
                        "user": {"user_id": "u1", "nickname": "author"},
                        "tag_list": [{"id": "t1", "name": "tag"}],
                    }
                }
            ]
        }

    def user_profile(self, user_id, **kwargs):
        return {"basic_info": {"user_id": user_id, "nickname": "author", "desc": "bio"}}

    def comments(self, note_id, xsec_token, **kwargs):
        return {"comments": [{"id": "c1", "content": "comment"}], "has_more": False, "cursor": ""}


class PagedFakeClient(FakeClient):
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def search_notes(self, keyword, **kwargs):
        self.requests.append(kwargs)
        page = int(kwargs["page"])
        return {
            "items": [
                {
                    "id": f"6aa28418000000002b01190{page}",
                    "xsec_token": f"token-{page}",
                    "note_card": {
                        "type": "normal",
                        "display_title": f"{keyword}-{page}",
                        "user": {"user_id": "u1", "nickname": "author"},
                    },
                }
            ],
            "has_more": page < 3,
        }


class SubCommentFakeClient(FakeClient):
    def __init__(self) -> None:
        self.sub_requests: list[str] = []

    def comments(self, note_id, xsec_token, **kwargs):
        return {
            "comments": [
                {
                    "id": "root-1",
                    "content": "root",
                    "sub_comment_count": 4,
                    "sub_comment_has_more": True,
                    "sub_comment_cursor": "cursor-1",
                    "sub_comments": [{"id": "sub-1", "content": "embedded"}],
                }
            ],
            "has_more": False,
            "cursor": "",
        }

    def sub_comments(self, note_id, root_comment_id, xsec_token, **kwargs):
        cursor = str(kwargs.get("cursor") or "")
        self.sub_requests.append(cursor)
        if cursor == "cursor-1":
            return {
                "comments": [
                    {"id": "sub-2", "content": "page one"},
                    {"id": "sub-3", "content": "duplicate"},
                ],
                "has_more": True,
                "cursor": "cursor-2",
            }
        return {
            "comments": [
                {"id": "sub-3", "content": "duplicate"},
                {"id": "sub-4", "content": "page two"},
            ],
            "has_more": False,
            "cursor": "cursor-3",
        }


class UserSearchFakeClient(FakeClient):
    def __init__(self) -> None:
        self.search_requests: list[dict[str, object]] = []

    def search_users(self, keyword, **kwargs):
        self.search_requests.append({"keyword": keyword, **kwargs})
        page = int(kwargs["page"])
        return {
            "users": [
                {
                    "id": f"u{page}",
                    "name": f"user-{page}",
                    "image": "https://avatar",
                    "fans": "10",
                    "note_count": "2",
                    "xsec_token": "token",
                }
            ],
            "has_more": page < 2,
        }

    def user_profile(self, user_id, **kwargs):
        public = user_id == "u1"
        return {
            "basic_info": {"nickname": user_id},
            "tags": [{"name": "29岁"}],
            "interactions": [
                {"type": "follows", "count": "3"},
                {"type": "fans", "count": "10"},
                {"type": "interaction", "count": "7"},
            ],
            "liked": 5,
            "collected": 2,
            "tab_public": {
                "collection": public,
                "collectionNote": {"display": public, "lock": False, "count": 1 if public else 0},
            },
        }

    def user_collections(self, user_id, **kwargs):
        return {
            "notes": [
                {
                    "id": "6aa28418000000002b01190a",
                    "xsec_token": "token",
                    "note_card": {
                        "type": "normal",
                        "display_title": "collected",
                        "user": {"user_id": "author", "nickname": "A"},
                    },
                }
            ],
            "has_more": False,
            "cursor": "",
        }

def test_bounded_aggregate_pipeline(tmp_path: Path) -> None:
    service = CollectorService(Settings(cookie_file=tmp_path / "none"), client=FakeClient())
    result = asyncio.run(
        service.collect_keyword(
            "咖啡",
            pages=1,
            page_size=10,
            note_limit=1,
            include_details=True,
            include_authors=True,
            include_comments=True,
            comment_pages=1,
            use_gpt=False,
            save=False,
            sort="general",
            note_type=0,
        )
    )
    assert result["search_id"] == "search-fixture"
    assert result["count"] == 1
    assert result["items"][0]["note"]["desc"] == "description"
    assert result["items"][0]["author"]["desc"] == "bio"
    assert result["items"][0]["author"]["xsec_token"] == "token"
    assert result["items"][0]["author"]["xsec_token_available"] is True
    assert result["items"][0]["note"]["note_id"] == "6aa28418000000002b01190a"
    assert result["items"][0]["comments"][0]["comment_id"] == "c1"


def test_search_pages_fetches_requested_pages_with_one_search_id(tmp_path: Path) -> None:
    client = PagedFakeClient()
    service = CollectorService(Settings(cookie_file=tmp_path / "none"), client=client)

    result = asyncio.run(service.search_pages("咖啡", 5, "general", 0))

    assert result["requested_pages"] == 5
    assert result["fetched_pages"] == 3
    assert [item["title"] for item in result["items"]] == ["咖啡-1", "咖啡-2", "咖啡-3"]
    assert [request["page"] for request in client.requests] == [1, 2, 3]
    assert all(request["page_size"] == 20 for request in client.requests)
    assert {request["search_id"] for request in client.requests} == {"search-fixture"}


def test_comments_include_all_secondary_comment_pages(tmp_path: Path) -> None:
    client = SubCommentFakeClient()
    service = CollectorService(Settings(cookie_file=tmp_path / "none"), client=client)

    result = asyncio.run(service.comments("note-1", "token", ""))

    root = result["comments"][0]
    assert client.sub_requests == ["cursor-1", "cursor-2"]
    assert [comment["comment_id"] for comment in root["sub_comments"]] == [
        "sub-1",
        "sub-2",
        "sub-3",
        "sub-4",
    ]
    assert root["sub_comment_count"] == 4
    assert root["sub_comment_has_more"] is False
    assert root["sub_comment_cursor"] == "cursor-3"


def test_search_users_enriches_age_metrics_and_privacy(tmp_path: Path) -> None:
    client = UserSearchFakeClient()
    service = CollectorService(Settings(cookie_file=tmp_path / "none"), client=client)

    result = asyncio.run(service.search_users("咖啡", 3))

    assert result["fetched_pages"] == 2
    assert [item["user_id"] for item in result["items"]] == ["u1", "u2"]
    assert result["items"][0]["profile"]["age"] == 29
    assert result["items"][0]["xsec_token"] == "token"
    assert result["items"][0]["profile"]["xsec_token"] == "token"
    assert result["items"][0]["profile"]["xsec_token_available"] is True
    assert result["items"][0]["profile"]["received"]["likes"] == 5
    assert result["items"][0]["profile"]["collected_notes"]["is_private"] is False
    assert len(result["items"][0]["profile"]["collected_notes"]["items"]) == 1
    assert result["items"][1]["profile"]["collected_notes"]["is_private"] is True
    assert result["items"][0]["profile"]["followers"]["available"] is False
