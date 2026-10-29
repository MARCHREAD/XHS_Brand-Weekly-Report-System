from __future__ import annotations

import json
import re
from typing import Any, Iterable


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first(*values: Any, default: Any = "") -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _media_url(value: Any) -> str:
    url = str(value or "")
    if url.startswith("http://") and ".xhscdn.com/" in url:
        return "https://" + url.removeprefix("http://")
    return url


def parse_display_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(万|w|W)?", text)
    if not match:
        return None
    multiplier = 10_000 if match.group(2) else 1
    return int(float(match.group(1)) * multiplier)


def normalize_tags(tag_list: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _list(tag_list):
        if isinstance(item, str):
            if item:
                result.append({"id": "", "name": item})
            continue
        tag = _dict(item)
        name = str(_first(tag.get("name"), tag.get("tag_name"), tag.get("title")))
        if name:
            result.append({"id": str(_first(tag.get("id"), tag.get("tag_id"))), "name": name})
    return result


def _stream_items(stream_map: Any) -> list[dict[str, Any]]:
    streams: list[dict[str, Any]] = []
    for codec_group, values in _dict(stream_map).items():
        for value in _list(values):
            stream = _dict(value)
            master_url = _media_url(stream.get("master_url"))
            if not master_url:
                continue
            backup_urls = [
                _media_url(url) for url in _list(stream.get("backup_urls")) if isinstance(url, str) and url
            ]
            streams.append(
                {
                    "codec_group": str(codec_group),
                    "codec": str(_first(stream.get("video_codec"), codec_group)),
                    "format": str(_first(stream.get("format"), "mp4")),
                    "quality": str(_first(stream.get("quality_type"), stream.get("stream_desc"))),
                    "stream_type": stream.get("stream_type"),
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "fps": stream.get("fps"),
                    "video_bitrate": stream.get("video_bitrate"),
                    "avg_bitrate": stream.get("avg_bitrate"),
                    "size": stream.get("size"),
                    "duration_ms": _first(stream.get("video_duration"), stream.get("duration"), default=None),
                    "master_url": master_url,
                    "backup_urls": backup_urls,
                    "default": bool(stream.get("default_stream", False)),
                }
            )
    unique: dict[str, dict[str, Any]] = {}
    for stream in streams:
        unique.setdefault(stream["master_url"], stream)
    return list(unique.values())


def _stream_score(stream: dict[str, Any]) -> tuple[int, int, int, int]:
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    return (
        width * height,
        int(stream.get("video_bitrate") or stream.get("avg_bitrate") or 0),
        int(stream.get("size") or 0),
        int(bool(stream.get("default"))),
    )


def _best_stream(streams: list[dict[str, Any]]) -> dict[str, Any]:
    return max(streams, key=_stream_score) if streams else {}


def _best_browser_stream(streams: list[dict[str, Any]]) -> dict[str, Any]:
    compatible = [
        stream
        for stream in streams
        if any(
            marker in str(_first(stream.get("codec"), stream.get("codec_group"))).lower()
            for marker in ("h264", "avc", "ef4")
        )
    ]
    return max(compatible, key=_stream_score) if compatible else _best_stream(streams)


def normalize_video(card: dict[str, Any]) -> dict[str, Any] | None:
    video = _dict(card.get("video"))
    if not video:
        return None
    media = _dict(video.get("media"))
    streams = _stream_items(media.get("stream"))
    if not streams and isinstance(video.get("media_v2"), str):
        try:
            media_v2 = json.loads(video["media_v2"])
        except (TypeError, ValueError):
            media_v2 = {}
        streams = _stream_items(_dict(media_v2).get("stream"))
    best = _best_stream(streams)
    playable = _best_browser_stream(streams)
    media_video = _dict(media.get("video"))
    duration_ms = best.get("duration_ms")
    if not duration_ms:
        seconds = _first(media_video.get("duration"), _dict(video.get("capa")).get("duration"), default=None)
        duration_ms = int(seconds * 1000) if isinstance(seconds, (int, float)) else None
    return {
        "video_id": str(_first(media.get("video_id"), media_video.get("biz_id"))),
        "duration_ms": duration_ms,
        "best_url": str(best.get("master_url", "")),
        "playable_url": str(playable.get("master_url", "")),
        "stream_count": len(streams),
        "streams": streams,
    }


def _image_variants(image: dict[str, Any]) -> list[dict[str, str]]:
    variants: list[dict[str, str]] = []
    for info in _list(image.get("info_list")):
        info = _dict(info)
        url = _media_url(info.get("url"))
        if url:
            variants.append({"scene": str(info.get("image_scene", "")), "url": url})
    for scene, field in (("WB_DFT", "url_default"), ("WB_PRV", "url_pre"), ("", "url")):
        url = _media_url(image.get(field))
        if url and all(item["url"] != url for item in variants):
            variants.append({"scene": scene, "url": url})
    return variants


def normalize_image_items(card: dict[str, Any]) -> list[dict[str, Any]]:
    source_images = _list(card.get("image_list"))
    if not source_images and isinstance(card.get("cover"), dict):
        source_images = [card["cover"]]
    result: list[dict[str, Any]] = []
    for index, raw_image in enumerate(source_images):
        image = _dict(raw_image)
        variants = _image_variants(image)
        default_url = _media_url(
            _first(
                image.get("url_default"),
                next((item["url"] for item in variants if item["scene"] == "WB_DFT"), ""),
                image.get("url_pre"),
                variants[0]["url"] if variants else "",
            )
        )
        if not default_url:
            continue
        live_streams = _stream_items(image.get("stream"))
        live_best = _best_stream(live_streams)
        result.append(
            {
                "index": index,
                "width": image.get("width"),
                "height": image.get("height"),
                "file_id": str(image.get("file_id", "")),
                "url": default_url,
                "preview_url": _media_url(_first(image.get("url_pre"), default_url)),
                "variants": variants,
                "live_photo": bool(image.get("live_photo", False)),
                "live_photo_url": str(live_best.get("master_url", "")),
            }
        )
    return result


def _image_urls(card: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(item["url"] for item in normalize_image_items(card)))


def normalize_note(item: dict[str, Any]) -> dict[str, Any]:
    card = _dict(item.get("note_card")) or item
    user = _dict(card.get("user"))
    interact = _dict(card.get("interact_info"))
    note_id = str(_first(item.get("id"), item.get("note_id"), card.get("note_id")))
    xsec_token = str(_first(item.get("xsec_token"), card.get("xsec_token")))
    xsec_source = str(_first(item.get("xsec_source"), card.get("xsec_source"), "pc_search"))
    counts = {
        "liked": _first(interact.get("liked_count"), card.get("liked_count"), default="0"),
        "collected": _first(interact.get("collected_count"), card.get("collected_count"), default="0"),
        "comment": _first(interact.get("comment_count"), card.get("comment_count"), default="0"),
        "share": _first(interact.get("share_count"), card.get("share_count"), default="0"),
    }
    image_items = normalize_image_items(card)
    video = normalize_video(card)
    return {
        "note_id": note_id,
        "xsec_token": xsec_token,
        "xsec_source": xsec_source,
        "type": str(_first(card.get("type"), item.get("model_type"))),
        "title": str(_first(card.get("title"), card.get("display_title"))),
        "desc": str(_first(card.get("desc"), card.get("description"))),
        "author": {
            "user_id": str(_first(user.get("user_id"), user.get("id"))),
            "nickname": str(_first(user.get("nickname"), user.get("nick_name"), user.get("name"))),
            "avatar": str(_first(user.get("avatar"), user.get("image"))),
        },
        "counts": {key: {"display": str(value), "value": parse_display_count(value)} for key, value in counts.items()},
        "tags": normalize_tags(_first(card.get("tag_list"), card.get("tags"), default=[])),
        "images": list(dict.fromkeys(image["url"] for image in image_items)),
        "image_count": len(image_items),
        "image_items": image_items,
        "video": video,
        "time": card.get("time"),
        "last_update_time": card.get("last_update_time"),
        "note_url": f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else "",
    }


def normalize_author(payload: dict[str, Any]) -> dict[str, Any]:
    basic = _dict(payload.get("basic_info")) or payload
    interactions = _list(payload.get("interactions"))
    metrics: dict[str, int | None] = {}
    metric_visibility: dict[str, bool | None] = {}
    for item in interactions:
        item = _dict(item)
        metric_type = str(_first(item.get("type"), item.get("name")))
        if metric_type:
            metrics[metric_type] = parse_display_count(_first(item.get("count"), item.get("value")))
            metric_visibility[metric_type] = item.get("show") if isinstance(item.get("show"), bool) else None
    user_id = str(_first(basic.get("user_id"), payload.get("user_id"), basic.get("id")))
    profile_tags = [str(item.get("name")) for item in _list(payload.get("tags")) if isinstance(item, dict) and item.get("name")]
    age = None
    for label in profile_tags:
        match = re.fullmatch(r"\s*(\d{1,3})\s*岁\s*", label)
        if match and 0 < int(match.group(1)) <= 120:
            age = int(match.group(1))
            break
    received_likes = parse_display_count(payload.get("liked"))
    received_collections = parse_display_count(payload.get("collected"))
    interaction_total = metrics.get("interaction")
    if interaction_total is None and received_likes is not None and received_collections is not None:
        interaction_total = received_likes + received_collections
    tab_public = _dict(payload.get("tab_public"))
    collection_note = _dict(tab_public.get("collectionNote"))
    collection_public = bool(tab_public.get("collection"))
    collection_visible = bool(collection_note.get("display"))
    collection_locked = bool(collection_note.get("lock"))
    collection_is_private = not collection_public or not collection_visible or collection_locked
    return {
        "user_id": user_id,
        "nickname": str(_first(basic.get("nickname"), basic.get("nick_name"), basic.get("name"))),
        "red_id": str(_first(basic.get("red_id"), payload.get("red_id"))),
        "desc": str(_first(basic.get("desc"), basic.get("description"), payload.get("desc"))),
        "avatar": str(_first(basic.get("images"), basic.get("avatar"), basic.get("image"))),
        "ip_location": str(_first(basic.get("ip_location"), payload.get("ip_location"))),
        "gender": basic.get("gender"),
        "metrics": metrics,
        "metric_visibility": metric_visibility,
        "age": age,
        "profile_tags": profile_tags,
        "received": {
            "likes": received_likes,
            "collections": received_collections,
            "likes_and_collections": interaction_total,
            "posted_notes": parse_display_count(payload.get("posted")),
        },
        "following_users": {
            "count": metrics.get("follows"),
            "available": False,
            "items": [],
            "reason": "not_exposed_by_current_web_protocol",
        },
        "followers": {
            "count": metrics.get("fans"),
            "available": False,
            "items": [],
            "reason": "not_exposed_by_current_web_protocol",
        },
        "collected_notes": {
            "visibility": "private" if collection_is_private else "public",
            "is_private": collection_is_private,
            "available": not collection_is_private,
            "reason": "private" if collection_is_private else None,
            "count": int(collection_note.get("count") or 0),
            "items": [],
        },
        "profile_url": f"https://www.xiaohongshu.com/user/profile/{user_id}" if user_id else "",
    }


def normalize_search_user(item: dict[str, Any]) -> dict[str, Any]:
    user_id = str(_first(item.get("id"), item.get("user_id")))
    return {
        "user_id": user_id,
        "nickname": str(_first(item.get("name"), item.get("nickname"))),
        "red_id": str(item.get("red_id") or ""),
        "avatar": _media_url(_first(item.get("image"), item.get("avatar"))),
        "fans": parse_display_count(item.get("fans")),
        "note_count": parse_display_count(item.get("note_count")),
        "followed": bool(item.get("followed", False)),
        "xsec_token": str(item.get("xsec_token") or ""),
        "profile_url": str(item.get("link") or (f"https://www.xiaohongshu.com/user/profile/{user_id}" if user_id else "")),
    }


def normalize_comment(item: dict[str, Any]) -> dict[str, Any]:
    user = _dict(_first(item.get("user_info"), item.get("user"), default={}))
    sub_comments = [normalize_comment(_dict(value)) for value in _list(item.get("sub_comments"))]
    target = _dict(item.get("target_comment"))
    target_user = _dict(_first(target.get("user_info"), target.get("user"), default={}))
    return {
        "comment_id": str(_first(item.get("id"), item.get("comment_id"))),
        "content": str(_first(item.get("content"), item.get("text"))),
        "like_count": parse_display_count(_first(item.get("like_count"), item.get("liked_count"), default=0)),
        "create_time": _first(item.get("create_time"), item.get("time"), default=None),
        "ip_location": str(_first(item.get("ip_location"), item.get("ip_location_info"))),
        "author": {
            "user_id": str(_first(user.get("user_id"), user.get("id"))),
            "nickname": str(_first(user.get("nickname"), user.get("name"))),
            "avatar": str(_first(user.get("image"), user.get("avatar"))),
        },
        "sub_comments": sub_comments,
        "sub_comment_count": int(item.get("sub_comment_count") or len(sub_comments)),
        "sub_comment_has_more": bool(item.get("sub_comment_has_more", False)),
        "sub_comment_cursor": str(item.get("sub_comment_cursor", "")),
        "target_comment": {
            "comment_id": str(_first(target.get("id"), target.get("comment_id"))),
            "author": {
                "user_id": str(_first(target_user.get("user_id"), target_user.get("id"))),
                "nickname": str(_first(target_user.get("nickname"), target_user.get("name"))),
            },
        } if target else None,
    }


def normalize_many_notes(items: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in items:
        if not isinstance(value, dict):
            continue
        note = normalize_note(value)
        if note["type"] not in {"normal", "video"}:
            continue
        if not re.fullmatch(r"[0-9a-f]{24}", note["note_id"], flags=re.IGNORECASE):
            continue
        result.append(note)
    return result
