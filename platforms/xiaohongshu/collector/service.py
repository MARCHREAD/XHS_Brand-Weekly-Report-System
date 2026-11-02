from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .client import XhsClient
from .config import ConfigurationError, Settings
from .enrichment import OpenAIEnricher
from .errors import XhsUpstreamError
from .normalizers import (
    normalize_author,
    normalize_comment,
    normalize_many_notes,
    normalize_note,
    normalize_search_user,
)
from .pgy import (
    PgyBloggerDetailRequest,
    PgyBloggerSearchRequest,
    PgyNoteDetailRequest,
    PgySimilarBloggerRequest,
    pgy_business_data,
    pgy_envelope,
    tree_paths_by_name,
)
from .runtime import AsyncTTLCache, SessionPool
from .signing import XhsSigner


TraceCallback = Callable[[dict[str, Any]], Awaitable[None]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_key(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _error_text(error: BaseException) -> str:
    return str(error)[:300] or error.__class__.__name__


class CollectorService:
    def __init__(
        self,
        settings: Settings,
        client: XhsClient | None = None,
        *,
        pool: SessionPool | None = None,
        xhs_fallback_pool: SessionPool | None = None,
        cache: AsyncTTLCache | None = None,
    ) -> None:
        self.settings = settings
        self.pool = pool or SessionPool(settings, [client] if client else None)
        self.xhs_fallback_pool = xhs_fallback_pool
        self.cache = cache or AsyncTTLCache(enabled=settings.cache_enabled)
        self.enricher = OpenAIEnricher(settings)
        self._id_signer = client.signer if client else XhsSigner()
        self._gpt_semaphore = asyncio.Semaphore(settings.gpt_concurrency)

    async def _emit(self, trace: TraceCallback | None, event: dict[str, Any]) -> None:
        if trace is not None:
            await trace(event)

    async def _execute(
        self,
        *,
        stage: str,
        interface: str,
        target: str,
        cache_key: str,
        ttl_seconds: float,
        operation: Callable[[XhsClient], dict[str, Any]],
        summarize: Callable[[dict[str, Any]], dict[str, Any]],
        trace: TraceCallback | None,
        pool: SessionPool | None = None,
    ) -> dict[str, Any]:
        event_id = uuid4().hex
        started_at = _utc_now()
        started = time.perf_counter()
        await self._emit(
            trace,
            {
                "id": event_id,
                "stage": stage,
                "interface": interface,
                "target": target,
                "status": "running",
                "started_at": started_at,
            },
        )
        pool_meta: dict[str, Any] = {}
        runtime_pool = pool or self.pool

        async def fetch() -> dict[str, Any]:
            run = await runtime_pool.run(operation)
            pool_meta.update(worker_id=run.worker_id, queue_wait_ms=run.queue_wait_ms)
            return run.value

        try:
            value, cache_state = await self.cache.get_or_create(cache_key, ttl_seconds, fetch)
        except BaseException as exc:
            await self._emit(
                trace,
                {
                    "id": event_id,
                    "stage": stage,
                    "interface": interface,
                    "target": target,
                    "status": "error",
                    "started_at": started_at,
                    "finished_at": _utc_now(),
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "error": _error_text(exc),
                    **pool_meta,
                },
            )
            raise

        status = {
            "cache_hit": "cache_hit",
            "singleflight": "singleflight",
        }.get(cache_state, "success")
        await self._emit(
            trace,
            {
                "id": event_id,
                "stage": stage,
                "interface": interface,
                "target": target,
                "status": status,
                "cache": cache_state,
                "started_at": started_at,
                "finished_at": _utc_now(),
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "response": summarize(value),
                **pool_meta,
            },
        )
        return value

    async def homefeed(
        self,
        category: str,
        cursor_score: str,
        num: int,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        data = await self._execute(
            stage="homefeed",
            interface="POST /api/sns/web/v1/homefeed",
            target=category,
            cache_key=_stable_key("homefeed", [category, cursor_score, num]),
            ttl_seconds=self.settings.cache_homefeed_seconds,
            operation=lambda client: client.homefeed(category=category, cursor_score=cursor_score, num=num),
            summarize=lambda value: {
                "item_count": len(value.get("items", [])),
                "has_cursor": bool(value.get("cursor_score")),
            },
            trace=trace,
        )
        return {
            "items": normalize_many_notes(data.get("items", [])),
            "cursor_score": data.get("cursor_score", ""),
        }

    async def pgy_note_detail(
        self,
        request: PgyNoteDetailRequest,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        note_id, xsec_token, xsec_source = request.parameters()

        try:
            return await self._execute(
                stage="pgy_note_detail",
                interface="GET /api/solar/index/note_detail",
                target=note_id,
                cache_key=_stable_key("pgy-note", request.model_dump()),
                ttl_seconds=self.settings.cache_note_seconds,
                operation=lambda client: client.pgy_note_detail(note_id),
                summarize=lambda value: {
                    "success": value.get("success"),
                    "has_data": pgy_business_data(value) is not None,
                },
                trace=trace,
            )
        except XhsUpstreamError as exc:
            if str(exc.upstream_code) != "-10040000":
                raise
        if self.xhs_fallback_pool is None:
            raise ConfigurationError("No active XHS session is available for Pgy note fallback")

        xhs_data = await self._execute(
            stage="pgy_note_detail_fallback",
            interface="POST /api/sns/web/v1/feed",
            target=note_id,
            cache_key=_stable_key("pgy-note-fallback", request.model_dump()),
            ttl_seconds=self.settings.cache_note_seconds,
            operation=lambda client: client.note_detail(
                note_id,
                xsec_token,
                xsec_source=xsec_source,
            ),
            summarize=lambda value: {"item_count": len(value.get("items", []))},
            trace=trace,
            pool=self.xhs_fallback_pool,
        )
        items = xhs_data.get("items", [])
        data = normalize_note(items[0]) if items else {"note_id": note_id, "found": False}
        author_id = str(data.get("author", {}).get("user_id") or "")
        pgy_metrics: dict[str, Any] = {}
        if author_id:
            def fetch_metrics(client: XhsClient) -> dict[str, Any]:
                page_size = 20
                page_num = 1
                max_pages = 50
                note_case: dict[str, Any] | None = None
                total = 0
                while page_num <= max_pages:
                    case_data = pgy_business_data(
                        client.pgy_blogger_note_cases(
                            author_id,
                            page_num=page_num,
                            page_size=page_size,
                        )
                    ) or {}
                    rows = case_data.get("list") or []
                    note_case = next(
                        (
                            row
                            for row in rows
                            if str(row.get("noteId") or row.get("note_id") or "") == note_id
                        ),
                        None,
                    )
                    total = int(case_data.get("total") or total or 0)
                    if note_case is not None or not rows or page_num * page_size >= total:
                        break
                    page_num += 1

                preferred_business = 1 if note_case and note_case.get("brandName") else 0
                rate_note: dict[str, Any] | None = None
                for date_type in (1, 2):
                    for business in (preferred_business, 1 - preferred_business):
                        rate_data = pgy_business_data(
                            client.pgy_blogger_notes_rate(
                                author_id,
                                business=business,
                                date_type=date_type,
                            )
                        ) or {}
                        rate_note = next(
                            (
                                row
                                for row in rate_data.get("notes") or []
                                if str(row.get("noteId") or row.get("note_id") or "") == note_id
                            ),
                            None,
                        )
                        if rate_note is not None:
                            break
                    if rate_note is not None:
                        break
                return {
                    "note_case": note_case,
                    "rate_note": rate_note,
                    "case_total": total,
                    "pages_checked": page_num,
                }

            pgy_metrics = await self._execute(
                stage="pgy_blogger_note_metrics",
                interface=(
                    "GET /api/solar/kol/data_v2/notes_detail + "
                    "GET /api/solar/kol/data_v3/notes_rate"
                ),
                target=note_id,
                cache_key=_stable_key("pgy-blogger-note-metrics", [author_id, note_id]),
                ttl_seconds=self.settings.cache_note_seconds,
                operation=fetch_metrics,
                summarize=lambda value: {
                    "case_match": value.get("note_case") is not None,
                    "rate_match": value.get("rate_note") is not None,
                    "case_total": value.get("case_total", 0),
                    "pages_checked": value.get("pages_checked", 0),
                },
                trace=trace,
            )

        note_case = pgy_metrics.get("note_case") or {}
        rate_note = pgy_metrics.get("rate_note") or {}
        merged_metrics = {**note_case, **rate_note}
        data.update(
            {
                "impNum": merged_metrics.get("impNum"),
                "readNum": merged_metrics.get("readNum"),
                "likeNum": merged_metrics.get("likeNum"),
                "favNum": merged_metrics.get("favNum", merged_metrics.get("collectNum")),
                "cmtNum": merged_metrics.get("cmtNum"),
            }
        )
        if rate_note:
            data["data_source"] = "pgy_blogger_metrics+xhs_web"
            data["pgy_access"] = "matched"
        elif note_case:
            data["data_source"] = "pgy_blogger_note_case+xhs_web"
            data["pgy_access"] = "partial"
        else:
            data["data_source"] = "xhs_web_fallback"
            data["pgy_access"] = "not_listed"
        if merged_metrics:
            data["pgy_raw"] = merged_metrics
        return pgy_envelope(data)

    async def pgy_blogger_detail(
        self,
        request: PgyBloggerDetailRequest,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        def fetch(client: XhsClient) -> dict[str, Any]:
            sections = {
                "profile": pgy_business_data(client.pgy_blogger_profile(request.user_id)),
                "data_summary": pgy_business_data(
                    client.pgy_blogger_data_summary(request.user_id, request.business)
                ),
                "fans_summary": pgy_business_data(
                    client.pgy_blogger_fans_summary(request.user_id)
                ),
                "fans_profile": pgy_business_data(
                    client.pgy_blogger_fans_profile(request.user_id)
                ),
                "fans_history": pgy_business_data(
                    client.pgy_blogger_fans_history(
                        request.user_id,
                        request.increase_type,
                        request.date_type,
                    )
                ),
            }
            return pgy_envelope(sections)

        return await self._execute(
            stage="pgy_blogger_detail",
            interface="GET Pgy blogger profile and data sections",
            target=request.user_id,
            cache_key=_stable_key("pgy-blogger", request.model_dump()),
            ttl_seconds=self.settings.cache_author_seconds,
            operation=fetch,
            summarize=lambda value: {
                "success": value.get("success"),
                "sections": sorted((pgy_business_data(value) or {}).keys()),
            },
            trace=trace,
        )

    async def pgy_similar_bloggers(
        self,
        request: PgySimilarBloggerRequest,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        def fetch(client: XhsClient) -> dict[str, Any]:
            kols: list[dict[str, Any]] = []
            seen: set[str] = set()
            merged: dict[str, Any] = {}
            total = 0
            pages_fetched = 0
            pages_attempted = 0
            failed_pages: list[dict[str, Any]] = []
            last_page = request.page_num - 1
            for page_num in range(request.page_num, request.page_num + request.pages):
                pages_attempted += 1
                last_page = page_num
                try:
                    page = pgy_business_data(
                        client.pgy_similar_bloggers(request.user_id, page_num, request.page_size)
                    ) or {}
                except XhsUpstreamError as exc:
                    if exc.auth_failure:
                        raise
                    failed_pages.append({"page": page_num, "error": _error_text(exc)})
                    continue
                rows = page.get("kols") or []
                if not merged:
                    merged = dict(page)
                total = int(page.get("total") or total or 0)
                pages_fetched += 1
                last_page = page_num
                for row in rows:
                    identity = str(row.get("userId") or row.get("user_id") or "")
                    if identity and identity in seen:
                        continue
                    if identity:
                        seen.add(identity)
                    kols.append(row)
                if not rows or (total > 0 and len(kols) >= total):
                    break
            merged.update(
                {
                    "kols": kols,
                    "total": total,
                    "pages_requested": request.pages,
                    "pages_fetched": pages_fetched,
                    "pages_attempted": pages_attempted,
                    "failed_pages": failed_pages,
                    "start_page": request.page_num,
                    "last_page": last_page,
                    "page_size": request.page_size,
                    "returned": len(kols),
                }
            )
            return pgy_envelope(merged)

        return await self._execute(
            stage="pgy_similar_bloggers",
            interface="GET /api/solar/kol/get_similar_kol",
            target=request.user_id,
            cache_key=_stable_key("pgy-similar", request.model_dump()),
            ttl_seconds=self.settings.cache_search_seconds,
            operation=fetch,
            summarize=lambda value: {
                "success": value.get("success"),
                "item_count": len((pgy_business_data(value) or {}).get("kols", [])),
                "total": (pgy_business_data(value) or {}).get("total"),
                "failed_pages": len((pgy_business_data(value) or {}).get("failed_pages", [])),
            },
            trace=trace,
        )

    async def pgy_filter_options(
        self,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        def fetch(client: XhsClient) -> dict[str, Any]:
            config = pgy_business_data(client.pgy_filter_config()) or {}
            content_tags = pgy_business_data(client.pgy_content_tags()) or []
            consumer = pgy_business_data(client.pgy_consumer_behavior()) or {}
            blogger_areas = pgy_business_data(client.pgy_areas(blogger=True)) or {}
            fans_areas = pgy_business_data(client.pgy_areas()) or {}
            activities = pgy_business_data(client.pgy_activities()) or []
            special_industry = pgy_business_data(client.pgy_special_industry()) or {}
            data = dict(config) if isinstance(config, dict) else {"config": config}
            data.update(
                {
                    "contentTags": content_tags,
                    "consumerBehavior": (
                        consumer.get("consumeBehaviorTag", consumer)
                        if isinstance(consumer, dict)
                        else consumer
                    ),
                    "areas": blogger_areas.get("list", blogger_areas)
                    if isinstance(blogger_areas, dict)
                    else blogger_areas,
                    "fansAreas": fans_areas.get("list", fans_areas)
                    if isinstance(fans_areas, dict)
                    else fans_areas,
                    "activities": activities,
                    "contentScenes": (
                        special_industry.get("industryTag", special_industry)
                        if isinstance(special_industry, dict)
                        else special_industry
                    ),
                }
            )
            return pgy_envelope(data)

        return await self._execute(
            stage="pgy_filter_options",
            interface="GET Pgy blogger filter dictionaries",
            target="blogger-square",
            cache_key="pgy-filter-options",
            ttl_seconds=3600,
            operation=fetch,
            summarize=lambda value: {
                "success": value.get("success"),
                "dictionary_keys": sorted((pgy_business_data(value) or {}).keys()),
            },
            trace=trace,
        )

    async def pgy_search_bloggers(
        self,
        request: PgyBloggerSearchRequest,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        fans_locations: list[str] | None = None
        if request.fans.location:
            options = await self.pgy_filter_options(trace=trace)
            option_data = pgy_business_data(options) or {}
            nodes = option_data.get("fansAreas", []) if isinstance(option_data, dict) else []
            fans_locations = tree_paths_by_name(nodes if isinstance(nodes, list) else [], request.fans.location)
        payload = request.to_upstream(fans_locations=fans_locations)

        def fetch(client: XhsClient) -> dict[str, Any]:
            track_request = dict(payload)
            track_request.pop("trackId", None)
            track_error = ""
            track_id = request.track_id
            if not track_id:
                try:
                    track = pgy_business_data(client.pgy_blogger_track(track_request)) or {}
                except XhsUpstreamError as exc:
                    if exc.auth_failure:
                        raise
                    track = {}
                    track_error = _error_text(exc)
                track_id = track.get("trackId") if isinstance(track, dict) else None
            kols: list[dict[str, Any]] = []
            seen: set[str] = set()
            merged: dict[str, Any] = {}
            total = 0
            pages_fetched = 0
            pages_attempted = 0
            failed_pages: list[dict[str, Any]] = []
            last_page = request.page_num - 1
            for page_num in range(request.page_num, request.page_num + request.pages):
                pages_attempted += 1
                last_page = page_num
                list_request = dict(payload)
                list_request["pageNum"] = page_num
                if track_id:
                    list_request["trackId"] = track_id
                try:
                    page = pgy_business_data(client.pgy_blogger_search(list_request)) or {}
                except XhsUpstreamError as exc:
                    if exc.auth_failure:
                        raise
                    failed_pages.append({"page": page_num, "error": _error_text(exc)})
                    continue
                rows = page.get("kols") or []
                if not merged:
                    merged = dict(page)
                total = int(page.get("total") or total or 0)
                pages_fetched += 1
                last_page = page_num
                for row in rows:
                    identity = str(row.get("userId") or row.get("user_id") or "")
                    if identity and identity in seen:
                        continue
                    if identity:
                        seen.add(identity)
                    kols.append(row)
                if not rows or (total > 0 and total < 5000 and len(kols) >= total):
                    break
            merged.update(
                {
                    "kols": kols,
                    "total": total,
                    "pages_requested": request.pages,
                    "pages_fetched": pages_fetched,
                    "pages_attempted": pages_attempted,
                    "failed_pages": failed_pages,
                    "start_page": request.page_num,
                    "last_page": last_page,
                    "page_size": request.page_size,
                    "returned": len(kols),
                    "track_error": track_error or None,
                    "trackId": track_id or merged.get("trackId"),
                }
            )
            return pgy_envelope(merged)

        return await self._execute(
            stage="pgy_blogger_search",
            interface="POST /api/solar/cooperator/blogger/track + /blogger/v2",
            target=request.keyword or request.similar_user_id or "filters",
            cache_key=_stable_key("pgy-search", request.model_dump()),
            ttl_seconds=self.settings.cache_search_seconds,
            operation=fetch,
            summarize=lambda value: {
                "success": value.get("success"),
                "item_count": len((pgy_business_data(value) or {}).get("kols", [])),
                "total": (pgy_business_data(value) or {}).get("total"),
                "failed_pages": len((pgy_business_data(value) or {}).get("failed_pages", [])),
            },
            trace=trace,
        )

    async def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        sort: str,
        note_type: int,
        search_id: str | None = None,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        resolved_search_id = search_id or self._id_signer.search_id()
        data = await self._execute(
            stage="search",
            interface="POST /api/sns/web/v2/search/notes",
            target=f"{keyword} · page {page}",
            cache_key=_stable_key("search", [keyword, page, page_size, sort, note_type]),
            ttl_seconds=self.settings.cache_search_seconds,
            operation=lambda client: client.search_notes(
                keyword,
                page=page,
                page_size=page_size,
                search_id=resolved_search_id,
                sort=sort,
                note_type=note_type,
            ),
            summarize=lambda value: {
                "raw_item_count": len(value.get("items", [])),
                "note_count": len(normalize_many_notes(value.get("items", []))),
                "has_more": bool(value.get("has_more")),
            },
            trace=trace,
        )
        return {
            "items": normalize_many_notes(data.get("items", [])),
            "has_more": bool(data.get("has_more", False)),
            "search_id": resolved_search_id,
        }

    async def search_pages(
        self,
        keyword: str,
        pages: int,
        sort: str,
        note_type: int,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        search_id = self._id_signer.search_id()
        items: list[dict[str, Any]] = []
        fetched_pages = 0
        has_more = True
        for page in range(1, pages + 1):
            result = await self.search(
                keyword,
                page,
                20,
                sort,
                note_type,
                search_id,
                trace,
            )
            fetched_pages += 1
            items.extend(result["items"])
            has_more = bool(result["has_more"])
            if not has_more:
                break
        return {
            "items": items,
            "requested_pages": pages,
            "fetched_pages": fetched_pages,
            "has_more": has_more,
            "search_id": search_id,
        }

    async def note(
        self,
        note_id: str,
        xsec_token: str,
        xsec_source: str,
        use_gpt: bool,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        token_hash = hashlib.sha256(xsec_token.encode("utf-8")).hexdigest()[:12]
        data = await self._execute(
            stage="detail",
            interface="POST /api/sns/web/v1/feed",
            target=note_id,
            cache_key=_stable_key("note", [note_id, token_hash, xsec_source]),
            ttl_seconds=self.settings.cache_note_seconds,
            operation=lambda client: client.note_detail(note_id, xsec_token, xsec_source=xsec_source),
            summarize=lambda value: {"item_count": len(value.get("items", []))},
            trace=trace,
        )
        items = data.get("items", [])
        if not items:
            return {"note_id": note_id, "found": False}
        normalized = normalize_note(items[0])
        normalized["found"] = True
        if use_gpt:
            normalized["gpt"] = await self._enrich(normalized, trace)
        return normalized

    async def author(
        self,
        user_id: str,
        trace: TraceCallback | None = None,
        *,
        xsec_token: str = "",
        xsec_source: str = "pc_search",
    ) -> dict[str, Any]:
        token_hash = hashlib.sha256(xsec_token.encode("utf-8")).hexdigest()[:12]
        data = await self._execute(
            stage="author",
            interface="GET /api/sns/web/v1/user/otherinfo",
            target=user_id,
            cache_key=_stable_key("author", [user_id, token_hash, xsec_source]),
            ttl_seconds=self.settings.cache_author_seconds,
            operation=lambda client: client.user_profile(
                user_id,
                xsec_token=xsec_token,
                xsec_source=xsec_source,
            ),
            summarize=lambda value: {
                "fields": sorted(value)[:12],
                "has_basic_info": isinstance(value.get("basic_info"), dict),
            },
            trace=trace,
        )
        profile = normalize_author({**data, "user_id": user_id})
        profile["xsec_token"] = xsec_token
        profile["xsec_source"] = xsec_source if xsec_token else ""
        profile["xsec_token_available"] = bool(xsec_token)
        return profile

    async def search_users(
        self,
        keyword: str,
        pages: int,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        search_id = self._id_signer.search_id()
        users: list[dict[str, Any]] = []
        fetched_pages = 0
        has_more = True
        for page in range(1, pages + 1):
            data = await self._execute(
                stage="user_search",
                interface="POST /api/sns/web/v1/search/usersearch",
                target=f"{keyword} · page {page}",
                cache_key=_stable_key("user-search", [keyword, page]),
                ttl_seconds=self.settings.cache_search_seconds,
                operation=lambda client, current_page=page: client.search_users(
                    keyword,
                    page=current_page,
                    page_size=15,
                    search_id=search_id,
                    request_id=self._id_signer.search_request_id(),
                ),
                summarize=lambda value: {
                    "user_count": len(value.get("users", [])),
                    "has_more": bool(value.get("has_more")),
                },
                trace=trace,
            )
            fetched_pages += 1
            page_users = [normalize_search_user(item) for item in data.get("users", []) if isinstance(item, dict)]

            async def enrich(user: dict[str, Any]) -> dict[str, Any]:
                try:
                    profile = await self.author(
                        user["user_id"],
                        trace,
                        xsec_token=user["xsec_token"],
                        xsec_source="pc_search",
                    )
                except BaseException as exc:
                    return {
                        **user,
                        "profile": {
                            "user_id": user["user_id"],
                            "found": False,
                            "error": _error_text(exc),
                        },
                    }
                profile["found"] = True
                collections = profile["collected_notes"]
                if collections["visibility"] == "public":
                    try:
                        collections["items"] = await self._collect_user_collections(user["user_id"], trace)
                    except BaseException as exc:
                        collections["available"] = False
                        collections["reason"] = "upstream_temporarily_unavailable"
                        collections["error"] = _error_text(exc)
                    else:
                        collections["count"] = max(collections["count"], len(collections["items"]))
                return {**user, "profile": profile}

            users.extend(await asyncio.gather(*(enrich(user) for user in page_users if user["user_id"])))
            has_more = bool(data.get("has_more", False))
            if not has_more:
                break
        return {
            "items": users,
            "requested_pages": pages,
            "fetched_pages": fetched_pages,
            "has_more": has_more,
            "search_id": search_id,
        }

    async def _collect_user_collections(
        self,
        user_id: str,
        trace: TraceCallback | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = ""
        seen_cursors: set[str] = set()
        while cursor not in seen_cursors:
            seen_cursors.add(cursor)
            data = await self._execute(
                stage="user_collections",
                interface="GET /api/sns/web/v2/note/collect/page",
                target=f"{user_id} · cursor {bool(cursor)}",
                cache_key=_stable_key("user-collections", [user_id, cursor]),
                ttl_seconds=self.settings.cache_author_notes_seconds,
                operation=lambda client, current_cursor=cursor: client.user_collections(
                    user_id,
                    cursor=current_cursor,
                ),
                summarize=lambda value: {
                    "item_count": len(value.get("notes", value.get("items", []))),
                    "has_more": bool(value.get("has_more")),
                },
                trace=trace,
            )
            items.extend(normalize_many_notes(data.get("notes", data.get("items", []))))
            if not data.get("has_more"):
                break
            next_cursor = str(data.get("cursor") or "")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return items

    async def author_notes(
        self,
        user_id: str,
        cursor: str,
        num: int,
        xsec_token: str,
        xsec_source: str,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        token_hash = hashlib.sha256(xsec_token.encode("utf-8")).hexdigest()[:12]
        data = await self._execute(
            stage="author_notes",
            interface="GET /api/sns/web/v1/user_posted",
            target=user_id,
            cache_key=_stable_key("author-notes", [user_id, cursor, num, token_hash, xsec_source]),
            ttl_seconds=self.settings.cache_author_notes_seconds,
            operation=lambda client: client.user_notes(
                user_id,
                cursor=cursor,
                num=num,
                xsec_token=xsec_token,
                xsec_source=xsec_source,
            ),
            summarize=lambda value: {
                "item_count": len(value.get("notes", value.get("items", []))),
                "has_more": bool(value.get("has_more")),
            },
            trace=trace,
        )
        return {
            "items": normalize_many_notes(data.get("notes", data.get("items", []))),
            "cursor": data.get("cursor", ""),
            "has_more": bool(data.get("has_more", False)),
        }

    async def comments(
        self,
        note_id: str,
        xsec_token: str,
        cursor: str,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        token_hash = hashlib.sha256(xsec_token.encode("utf-8")).hexdigest()[:12]
        data = await self._execute(
            stage="comments",
            interface="GET /api/sns/web/v2/comment/page",
            target=f"{note_id} · cursor {bool(cursor)}",
            cache_key=_stable_key("comments", [note_id, cursor, token_hash]),
            ttl_seconds=self.settings.cache_comments_seconds,
            operation=lambda client: client.comments(note_id, xsec_token, cursor=cursor),
            summarize=lambda value: {
                "comment_count": len(value.get("comments", [])),
                "has_more": bool(value.get("has_more")),
                "has_cursor": bool(value.get("cursor")),
            },
            trace=trace,
        )
        comments = [normalize_comment(item) for item in data.get("comments", []) if isinstance(item, dict)]

        async def hydrate_sub_comments(comment: dict[str, Any]) -> dict[str, Any]:
            if not comment["sub_comment_has_more"]:
                return comment
            additional, cursor, has_more = await self._collect_sub_comments(
                note_id,
                comment["comment_id"],
                xsec_token,
                comment["sub_comment_cursor"],
                trace,
            )
            combined = [*comment["sub_comments"], *additional]
            unique: dict[str, dict[str, Any]] = {}
            for sub_comment in combined:
                comment_id = sub_comment.get("comment_id", "")
                if comment_id:
                    unique.setdefault(comment_id, sub_comment)
            comment["sub_comments"] = list(unique.values())
            comment["sub_comment_count"] = max(
                int(comment.get("sub_comment_count") or 0),
                len(comment["sub_comments"]),
            )
            comment["sub_comment_cursor"] = cursor
            comment["sub_comment_has_more"] = has_more
            return comment

        hydrated = await asyncio.gather(*(hydrate_sub_comments(comment) for comment in comments))
        return {
            "comments": hydrated,
            "cursor": data.get("cursor", ""),
            "has_more": bool(data.get("has_more", False)),
        }

    async def sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str,
        cursor: str,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        token_hash = hashlib.sha256(xsec_token.encode("utf-8")).hexdigest()[:12]
        data = await self._execute(
            stage="sub_comments",
            interface="GET /api/sns/web/v2/comment/sub/page",
            target=f"{root_comment_id} · cursor {bool(cursor)}",
            cache_key=_stable_key("sub-comments", [note_id, root_comment_id, cursor, token_hash]),
            ttl_seconds=self.settings.cache_comments_seconds,
            operation=lambda client: client.sub_comments(
                note_id,
                root_comment_id,
                xsec_token,
                cursor=cursor,
            ),
            summarize=lambda value: {
                "comment_count": len(value.get("comments", [])),
                "has_more": bool(value.get("has_more")),
                "has_cursor": bool(value.get("cursor")),
            },
            trace=trace,
        )
        return {
            "comments": [normalize_comment(item) for item in data.get("comments", []) if isinstance(item, dict)],
            "cursor": str(data.get("cursor", "")),
            "has_more": bool(data.get("has_more", False)),
        }

    async def _collect_sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str,
        cursor: str,
        trace: TraceCallback | None,
    ) -> tuple[list[dict[str, Any]], str, bool]:
        comments: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()
        has_more = True
        while has_more and cursor not in seen_cursors:
            seen_cursors.add(cursor)
            result = await self.sub_comments(
                note_id,
                root_comment_id,
                xsec_token,
                cursor,
                trace,
            )
            comments.extend(result["comments"])
            next_cursor = result["cursor"]
            has_more = result["has_more"]
            if not next_cursor or next_cursor == cursor:
                has_more = False
            cursor = next_cursor
        return comments, cursor, has_more

    async def _enrich(self, note: dict[str, Any], trace: TraceCallback | None) -> dict[str, Any]:
        key = _stable_key("gpt", [note.get("title", ""), note.get("desc", ""), note.get("tags", [])])
        event_id = uuid4().hex
        started_at = _utc_now()
        started = time.perf_counter()
        await self._emit(
            trace,
            {
                "id": event_id,
                "stage": "gpt",
                "interface": "OpenAI responses.parse",
                "target": note.get("note_id", "note"),
                "status": "running",
                "started_at": started_at,
            },
        )

        async def create() -> dict[str, Any]:
            async with self._gpt_semaphore:
                return await asyncio.to_thread(self.enricher.enrich, note)

        try:
            value, cache_state = await self.cache.get_or_create(key, 86_400, create)
        except BaseException as exc:
            await self._emit(
                trace,
                {
                    "id": event_id,
                    "stage": "gpt",
                    "interface": "OpenAI responses.parse",
                    "target": note.get("note_id", "note"),
                    "status": "error",
                    "started_at": started_at,
                    "finished_at": _utc_now(),
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "error": _error_text(exc),
                },
            )
            raise
        status = {"cache_hit": "cache_hit", "singleflight": "singleflight"}.get(cache_state, "success")
        await self._emit(
            trace,
            {
                "id": event_id,
                "stage": "gpt",
                "interface": "OpenAI responses.parse",
                "target": note.get("note_id", "note"),
                "status": status,
                "cache": cache_state,
                "started_at": started_at,
                "finished_at": _utc_now(),
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "response": {
                    "summary_length": len(value.get("summary", "")),
                    "topic_count": len(value.get("topics", [])),
                    "keyword_count": len(value.get("keywords", [])),
                },
            },
        )
        return value

    async def _collect_comment_pages(
        self,
        note_id: str,
        xsec_token: str,
        page_count: int,
        trace: TraceCallback | None,
    ) -> tuple[list[dict[str, Any]], str]:
        comments: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(page_count):
            result = await self.comments(note_id, xsec_token, cursor, trace)
            comments.extend(result["comments"])
            cursor = result["cursor"]
            if not result["has_more"]:
                break
        return comments, cursor

    async def collect_keyword(
        self,
        keyword: str,
        *,
        pages: int,
        page_size: int,
        note_limit: int,
        include_details: bool,
        include_authors: bool,
        include_comments: bool,
        comment_pages: int,
        use_gpt: bool,
        save: bool,
        sort: str,
        note_type: int,
        trace: TraceCallback | None = None,
    ) -> dict[str, Any]:
        search_id = self._id_signer.search_id()
        notes: list[dict[str, Any]] = []
        seen_notes: set[str] = set()
        for page in range(1, pages + 1):
            result = await self.search(keyword, page, page_size, sort, note_type, search_id, trace)
            for note in result["items"]:
                note_id = note.get("note_id", "")
                if not note_id or note_id in seen_notes:
                    continue
                seen_notes.add(note_id)
                notes.append(note)
                if len(notes) >= note_limit:
                    break
            if len(notes) >= note_limit or not result["has_more"]:
                break

        async def hydrate(search_note: dict[str, Any]) -> dict[str, Any]:
            record: dict[str, Any] = {"search": search_note}
            errors: dict[str, str] = {}
            note_id = search_note["note_id"]
            xsec_token = search_note.get("xsec_token", "")
            xsec_source = search_note.get("xsec_source", "pc_search")
            author_id = search_note.get("author", {}).get("user_id")
            work: dict[str, Awaitable[Any]] = {}
            if include_details and xsec_token:
                work["note"] = self.note(note_id, xsec_token, xsec_source, use_gpt, trace)
            elif use_gpt:
                work["gpt"] = self._enrich(search_note, trace)
            if include_authors and author_id:
                work["author"] = self.author(
                    author_id,
                    trace,
                    xsec_token=xsec_token,
                    xsec_source=xsec_source,
                )
            if include_comments and xsec_token:
                work["comments"] = self._collect_comment_pages(note_id, xsec_token, comment_pages, trace)

            names = list(work)
            outcomes = await asyncio.gather(*work.values(), return_exceptions=True)
            for name, outcome in zip(names, outcomes, strict=True):
                if isinstance(outcome, BaseException):
                    errors[name] = _error_text(outcome)
                    continue
                if name == "comments":
                    record["comments"], record["comments_cursor"] = outcome
                else:
                    record[name] = outcome
            if errors:
                record["errors"] = errors
            return record

        records = await asyncio.gather(*(hydrate(note) for note in notes))
        output_path: Path | None = None
        if save:
            event_id = uuid4().hex
            started = time.perf_counter()
            await self._emit(
                trace,
                {
                    "id": event_id,
                    "stage": "save",
                    "interface": "JSONL writer",
                    "target": keyword,
                    "status": "running",
                    "started_at": _utc_now(),
                },
            )
            output_path = await asyncio.to_thread(self._persist, keyword, records)
            await self._emit(
                trace,
                {
                    "id": event_id,
                    "stage": "save",
                    "interface": "JSONL writer",
                    "target": keyword,
                    "status": "success",
                    "finished_at": _utc_now(),
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "response": {"records": len(records), "path": str(output_path)},
                },
            )
        return {
            "keyword": keyword,
            "search_id": search_id,
            "count": len(records),
            "items": records,
            "output_path": str(output_path) if output_path else None,
        }

    async def runtime_snapshot(self) -> dict[str, Any]:
        pool, cache = await asyncio.gather(self.pool.snapshot(), self.cache.snapshot())
        return {"pool": pool, "cache": cache, "gpt_concurrency": self.settings.gpt_concurrency}

    def _persist(self, keyword: str, records: list[dict[str, Any]]) -> Path:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", keyword).strip("-") or "keyword"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = (self.settings.output_dir / f"{stamp}-{slug}.jsonl").resolve()
        if self.settings.output_dir.resolve() not in destination.parents:
            raise ValueError("Output path escaped the configured output directory")
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return destination
