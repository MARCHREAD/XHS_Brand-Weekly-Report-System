from collector.normalizers import (
    normalize_author,
    normalize_comment,
    normalize_many_notes,
    normalize_note,
    parse_display_count,
)
from collector.client import build_xhs_url


def test_parse_display_count() -> None:
    assert parse_display_count("1.6万") == 16_000
    assert parse_display_count("2,306") == 2_306
    assert parse_display_count(7) == 7


def test_xhs_url_encoding_matches_signer_contract() -> None:
    url = build_xhs_url(
        "https://edith.xiaohongshu.com/api",
        {"cursor": "", "image_formats": "jpg,webp,avif", "token": "abc="},
    )
    assert url.endswith("?cursor=&image_formats=jpg,webp,avif&token=abc%3D")


def test_normalize_note_search_shape() -> None:
    result = normalize_note(
        {
            "id": "note-1",
            "xsec_token": "token",
            "note_card": {
                "display_title": "标题",
                "user": {"user_id": "user-1", "nickname": "作者"},
                "interact_info": {"liked_count": "1.2万", "collected_count": "8"},
                "tag_list": [{"id": "tag-1", "name": "咖啡"}],
                "cover": {"info_list": [{"url": "http://sns-webpic-qc.xhscdn.com/cover"}]},
            },
        }
    )
    assert result["note_id"] == "note-1"
    assert result["author"]["user_id"] == "user-1"
    assert result["counts"]["liked"]["value"] == 12_000
    assert result["tags"] == [{"id": "tag-1", "name": "咖啡"}]
    assert result["images"] == ["https://sns-webpic-qc.xhscdn.com/cover"]


def test_normalize_many_notes_discards_search_suggestions() -> None:
    notes = normalize_many_notes(
        [
            {"id": "6aa28418000000002b01190a", "note_card": {"type": "normal"}},
            {"id": "query#1", "model_type": "hot_query"},
        ]
    )
    assert [item["note_id"] for item in notes] == ["6aa28418000000002b01190a"]


def test_normalize_full_image_gallery_and_video_streams() -> None:
    note = normalize_note(
        {
            "note_card": {
                "note_id": "6aa28418000000002b01190a",
                "type": "video",
                "image_list": [
                    {
                        "width": 1080,
                        "height": 1440,
                        "url_default": "http://sns-webpic-qc.xhscdn.com/image-1",
                        "url_pre": "http://sns-webpic-qc.xhscdn.com/image-1-preview",
                        "info_list": [
                            {"image_scene": "WB_PRV", "url": "http://sns-webpic-qc.xhscdn.com/image-1-preview"},
                            {"image_scene": "WB_DFT", "url": "http://sns-webpic-qc.xhscdn.com/image-1"},
                        ],
                    },
                    {
                        "width": 1080,
                        "height": 1440,
                        "url_default": "http://sns-webpic-qc.xhscdn.com/image-2",
                        "live_photo": True,
                        "stream": {
                            "EF4": [
                                {"master_url": "http://sns-video-v2.xhscdn.com/live-photo.mp4"}
                            ]
                        },
                    },
                ],
                "video": {
                    "media": {
                        "video_id": 123,
                        "stream": {
                            "EF4": [
                                {
                                    "master_url": "http://sns-video-v2.xhscdn.com/720.mp4?sign=x",
                                    "backup_urls": ["http://sns-bak-v1.xhscdn.com/720.mp4"],
                                    "width": 720,
                                    "height": 1280,
                                    "video_bitrate": 200000,
                                    "video_duration": 9000,
                                    "format": "mp4",
                                },
                            ],
                            "EF5": [
                                {
                                    "master_url": "http://sns-video-v2.xhscdn.com/1080.mp4?sign=y",
                                    "backup_urls": ["http://sns-bak-v1.xhscdn.com/1080.mp4"],
                                    "width": 1080,
                                    "height": 1920,
                                    "video_bitrate": 400000,
                                    "video_duration": 9000,
                                    "format": "mp4",
                                },
                            ]
                        },
                    }
                },
            }
        }
    )
    assert note["image_count"] == 2
    assert note["images"] == [
        "https://sns-webpic-qc.xhscdn.com/image-1",
        "https://sns-webpic-qc.xhscdn.com/image-2",
    ]
    assert note["image_items"][0]["variants"][0]["scene"] == "WB_PRV"
    assert note["image_items"][1]["live_photo_url"] == "https://sns-video-v2.xhscdn.com/live-photo.mp4"
    assert note["video"]["stream_count"] == 2
    assert note["video"]["best_url"] == "https://sns-video-v2.xhscdn.com/1080.mp4?sign=y"
    assert note["video"]["playable_url"] == "https://sns-video-v2.xhscdn.com/720.mp4?sign=x"
    assert note["video"]["streams"][0]["backup_urls"][0].startswith("https://")


def test_normalize_author_and_comment() -> None:
    author = normalize_author(
        {
            "basic_info": {"user_id": "u1", "nickname": "N", "desc": "bio"},
            "interactions": [{"type": "fans", "count": "2万"}],
        }
    )
    comment = normalize_comment(
        {"id": "c1", "content": "hello", "like_count": "3", "user_info": {"user_id": "u2"}}
    )
    assert author["metrics"]["fans"] == 20_000
    assert comment["comment_id"] == "c1"
    assert comment["like_count"] == 3


def test_normalize_author_age_metrics_and_private_collection() -> None:
    author = normalize_author(
        {
            "user_id": "u1",
            "basic_info": {"nickname": "N", "images": "https://avatar"},
            "tags": [{"name": "39岁", "tagType": "info"}],
            "interactions": [
                {"type": "follows", "count": "12"},
                {"type": "fans", "count": "34"},
                {"type": "interaction", "count": "436"},
            ],
            "liked": 420,
            "collected": 16,
            "posted": 36,
            "tab_public": {
                "collection": False,
                "collectionNote": {"display": False, "lock": False, "count": 0},
            },
        }
    )
    assert author["age"] == 39
    assert author["received"] == {
        "likes": 420,
        "collections": 16,
        "likes_and_collections": 436,
        "posted_notes": 36,
    }
    assert author["following_users"]["count"] == 12
    assert author["followers"]["count"] == 34
    assert author["following_users"]["available"] is False
    assert author["collected_notes"]["visibility"] == "private"
    assert author["collected_notes"]["is_private"] is True
    assert author["collected_notes"]["available"] is False
    assert author["collected_notes"]["reason"] == "private"


def test_normalize_secondary_comment_target() -> None:
    comment = normalize_comment(
        {
            "id": "sub-1",
            "content": "reply",
            "user_info": {"user_id": "u2", "nickname": "B"},
            "target_comment": {
                "id": "root-1",
                "user_info": {"user_id": "u1", "nickname": "A"},
            },
        }
    )
    assert comment["target_comment"] == {
        "comment_id": "root-1",
        "author": {"user_id": "u1", "nickname": "A"},
    }
