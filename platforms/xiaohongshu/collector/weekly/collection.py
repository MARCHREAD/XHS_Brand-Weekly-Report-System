from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from ..errors import XhsUpstreamError
from ..normalizers import normalize_comment, normalize_note
from .store import Store, now


class Paused(RuntimeError):
    pass


def error_kind(exc):
    if isinstance(exc, XhsUpstreamError):
        if exc.auth_failure:
            return "login_required"
        if exc.upstream_code == 300013 or exc.upstream_status == 429:
            return "rate_limited"
        if exc.upstream_status in {403, 429, 461, 471} or exc.upstream_code in {300012, -100, -101}:
            return "verification_required"
    return "upstream_error"


class Adapter:
    """Reuse the workbench's signer, HTTP client, session pool and rate limiter."""

    def __init__(self, service):
        self.service = service

    def search_id(self):
        return self.service._id_signer.search_id()

    async def search(self, keyword, page, search_id, sort):
        return await self.service.search(keyword, page, 20, sort, 0, search_id)

    async def detail(self, note):
        result = await self.service.pool.run(lambda c: c.note_detail(note["note_id"], note["xsec_token"], xsec_source=note.get("xsec_source") or "pc_search"))
        items = result.value.get("items", [])
        if not items:
            return {"note_id": note["note_id"], "found": False}
        detail = normalize_note(items[0])
        card = items[0].get("note_card") or items[0]
        mapping = {"liked": "liked_count", "collected": "collected_count", "comment": "comment_count", "share": "share_count"}
        for metric, field in mapping.items():
            if field not in card.get("interact_info", {}) and field not in card:
                detail["counts"][metric]["value"] = None
        detail["found"] = True
        return detail

    async def comments(self, note, cursor):
        result = await self.service.pool.run(lambda c: c.comments(note["note_id"], note["xsec_token"], cursor=cursor))
        return self._page(result.value)

    async def replies(self, note, root_id, cursor):
        result = await self.service.pool.run(lambda c: c.sub_comments(note["note_id"], root_id, note["xsec_token"], cursor=cursor))
        return self._page(result.value)

    @staticmethod
    def _page(data):
        if not isinstance(data, dict) or not isinstance(data.get("comments"), list) or not isinstance(data.get("has_more"), bool):
            raise ValueError("Unexpected comment pagination schema; preserving checkpoint")
        return {"comments": [normalize_comment(c) for c in data["comments"] if isinstance(c, dict)], "has_more": data["has_more"], "cursor": str(data.get("cursor") or "")}


class Collector:
    def __init__(self, store: Store, adapter: Any):
        self.store, self.adapter = store, adapter

    async def request(self, call):
        if self.store.meta().get("status") == "pause_requested":
            raise Paused("paused")
        for attempt in range(3):
            try:
                return await call()
            except Exception as exc:
                kind = error_kind(exc)
                if kind != "upstream_error":
                    raise Paused(kind) from exc
                # Only retry transport/5xx failures. Never retry business refusals in a loop.
                retry = not isinstance(exc, XhsUpstreamError) or (exc.upstream_status or 0) >= 500
                if not retry or attempt == 2:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))

    async def run(self):
        config = self.store.meta()["config"]
        self.store.meta(status="running", error=None, stage="search")
        try:
            for keyword in [config["primary"], *config["competitors"]]:
                for sort in dict.fromkeys([config["sort"], "general", "popularity_descending"]):
                    states = [s for _, s in self.store.items("search") if s["keyword"] == keyword]
                    fetched = sum(s.get("nonempty_pages", len([h for h in s.get("seen_pages", []) if h != hashlib.sha256(b"").hexdigest()])) for s in states)
                    if fetched >= config["search_pages"]:
                        break
                    await self.search(keyword, config, sort, config["search_pages"] - fetched)
            self.store.meta(stage="details_comments")
            pending_notes = sorted(self.store.items("note"), key=lambda row: (config["primary"] in row[1]["brands"], row[0]), reverse=True)
            for note_id, record in pending_notes:
                if record.get("complete"):
                    continue
                self.store.meta(current_note=note_id)
                try:
                    await self.hydrate(note_id, record)
                except Paused:
                    raise
                except Exception as exc:
                    record = self.store.get("note", note_id)
                    record["error"] = type(exc).__name__
                    self.store.put("note", note_id, record)
            summary = self.store.summary()
            anomalies = any(s.get("stop_reason") not in {"target_reached", "upstream_end"} for s in summary["searches"])
            status = "completed" if not summary["notes_incomplete"] and not anomalies else "partial"
            self.store.meta(status=status, stage="finished", current_note=None, finished_at=now())
        except Paused as exc:
            self.store.meta(status=str(exc), stage="paused", error=str(exc))
        except asyncio.CancelledError:
            self.store.meta(status="paused", stage="paused")
            raise
        except Exception as exc:
            self.store.meta(status="failed", error=type(exc).__name__)
            raise

    async def search(self, keyword, config, sort, remaining):
        key = keyword if sort == config["sort"] else f"{keyword}|{sort}"
        state = self.store.get("search", key, {"keyword": keyword, "sort": sort, "requested_pages": remaining, "fetched_pages": 0, "nonempty_pages": 0, "search_id": self.adapter.search_id(), "seen_pages": [], "status": "pending"})
        if state.get("stop_reason") in {"upstream_end", "target_reached", "repeated_page", "empty_nonterminal"}:
            return
        for page in range(state["fetched_pages"] + 1, state["requested_pages"] + 1):
            self.store.meta(current_keyword=keyword, current_page=page)
            result = await self.request(lambda: self.adapter.search(keyword, page, state["search_id"], sort))
            items = result.get("items")
            if not isinstance(items, list) or not isinstance(result.get("has_more"), bool):
                raise ValueError("Unexpected search pagination schema")
            signature = hashlib.sha256("|".join(sorted(n["note_id"] for n in items)).encode()).hexdigest()
            records = []
            for note in items:
                existing = self.store.get("note", note["note_id"], {"search": note, "brands": [], "complete": False, "detail_done": False})
                if keyword not in existing["brands"]:
                    existing["brands"].append(keyword)
                # Refresh proof tokens from the latest observed search result on resume.
                existing["search"] = note
                records.append(("note", note["note_id"], existing))
            state.update(fetched_pages=page, has_more=result["has_more"], status="running", sort=sort)
            if items and signature not in state["seen_pages"]:
                state["nonempty_pages"] = state.get("nonempty_pages", 0) + 1
            if not result["has_more"]:
                state.update(status="exhausted", stop_reason="upstream_end")
            elif not items:
                state.update(status="partial", stop_reason="empty_nonterminal")
            elif signature in state["seen_pages"]:
                state.update(status="partial", stop_reason="repeated_page")
            elif page == state["requested_pages"]:
                state.update(status="target_reached", stop_reason="target_reached")
            state["seen_pages"].append(signature)
            records.append(("search", key, state))
            self.store.put_many(records)
            if state.get("stop_reason"):
                break

    def save_comments(self, note_id, comments, root_id=""):
        records = []
        for c in comments:
            if not c.get("comment_id"):
                raise ValueError("Comment missing primary key")
            records.append(("comment", f"{note_id}:{c['comment_id']}", {"note_id": note_id, "root_id": root_id, "comment": {k: v for k, v in c.items() if k != "sub_comments"}, "captured_at": now()}))
            if not root_id:
                state_key = f"{note_id}:{c['comment_id']}"
                root = self.store.get("root", state_key)
                if root is None:
                    missing_replies = int(c.get("sub_comment_count") or 0) > len(c.get("sub_comments", []))
                    root = {"note_id": note_id, "root_id": c["comment_id"], "cursor": c.get("sub_comment_cursor") or "", "seen": [], "complete": not (c.get("sub_comment_has_more", False) or missing_replies)}
                    records.append(("root", state_key, root))
                for sub in c.get("sub_comments", []):
                    if sub.get("comment_id"):
                        records.append(("comment", f"{note_id}:{sub['comment_id']}", {"note_id": note_id, "root_id": c["comment_id"], "comment": sub, "captured_at": now()}))
        self.store.put_many(records)

    async def hydrate(self, note_id, record):
        note = record["search"]
        if not note.get("xsec_token"):
            record["error"] = "missing_observed_token"
            self.store.put("note", note_id, record)
            return
        if not record.get("detail_done"):
            detail = await self.request(lambda: self.adapter.detail(note))
            record.update(detail=detail, detail_done=bool(detail.get("found", True)), captured_at=now(), error=None)
            self.store.put("note", note_id, record)
        state = record.get("comments", {"cursor": "", "seen": [], "pages": 0, "complete": False})
        if state.get("stop_reason") == "cursor_stalled":
            state.pop("stop_reason")
        while not state["complete"] and not state.get("stop_reason"):
            cursor = state["cursor"]
            page = await self.request(lambda: self.adapter.comments(note, cursor))
            # Persist each page before advancing its cursor. Replaying after a crash is idempotent.
            self.save_comments(note_id, page["comments"])
            state["seen"].append(cursor)
            state["pages"] += 1
            if not page["has_more"]:
                state.update(complete=True, stop_reason="upstream_end")
            elif not page["cursor"] or page["cursor"] in state["seen"]:
                state["stop_reason"] = "cursor_stalled"
            state["cursor"] = page["cursor"]
            record["comments"] = state
            self.store.put("note", note_id, record)
        roots = [(key, r) for key, r in self.store.items("root") if r["note_id"] == note_id]
        for key, root in roots:
            if root.get("stop_reason") == "cursor_stalled":
                root.pop("stop_reason")
            while not root["complete"] and not root.get("stop_reason"):
                cursor = root["cursor"]
                page = await self.request(lambda: self.adapter.replies(note, root["root_id"], cursor))
                self.save_comments(note_id, page["comments"], root["root_id"])
                root["seen"].append(cursor)
                if not page["has_more"]:
                    root.update(complete=True, stop_reason="upstream_end")
                elif not page["cursor"] or page["cursor"] in root["seen"]:
                    root["stop_reason"] = "cursor_stalled"
                root["cursor"] = page["cursor"]
                self.store.put("root", key, root)
        record["complete"] = bool(record.get("detail_done") and state["complete"] and all(r["complete"] for _, r in roots))
        record["comments"] = state
        record["captured_at"] = now()
        self.store.put("note", note_id, record)
