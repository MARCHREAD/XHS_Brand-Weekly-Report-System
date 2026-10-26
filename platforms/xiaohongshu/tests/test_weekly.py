import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from collector.weekly.analysis import build_report, corpus, ensure_annotation_queue, train_sentiment
from collector.weekly.collection import Collector
from collector.weekly.manager import Manager, default_config
from collector.weekly.routes import router
from collector.weekly.store import Store


class FixtureAdapter:
    def __init__(self, stall=False):
        self.calls = []
        self.stall = stall

    def search_id(self):
        return "offline-search-id"

    async def search(self, keyword, page, search_id, sort):
        self.calls.append((keyword, page, sort))
        return {"items": [{"note_id": "n1", "xsec_token": "offline-only", "title": keyword}], "has_more": False}

    async def detail(self, note):
        return {"note_id": "n1", "title": "libtv 视频测试", "desc": "效果体验", "time": 1792404000000, "found": True, "counts": {}}

    async def comments(self, note, cursor):
        if not cursor:
            return {"comments": [{"comment_id": "c1", "content": "好用", "sub_comment_has_more": True, "sub_comment_cursor": "s1", "sub_comments": [{"comment_id": "r0", "content": "回复"}]}], "has_more": True, "cursor": "p2"}
        return {"comments": [{"comment_id": "c2", "content": "你好", "sub_comments": []}], "has_more": self.stall, "cursor": "p2"}

    async def replies(self, note, root_id, cursor):
        return {"comments": [{"comment_id": "r1" if cursor == "s1" else "r2", "content": "子评论"}], "has_more": cursor == "s1", "cursor": "s2" if cursor == "s1" else ""}


def store_fixture(tmp_path):
    s = Store(tmp_path)
    s.meta(job_id="a" * 32, config=default_config(), status="created")
    return s


def test_all_main_and_sub_pages_are_persisted_and_resume_deduplicates(tmp_path):
    s = store_fixture(tmp_path)
    a = FixtureAdapter()
    asyncio.run(Collector(s, a).run())
    assert s.count("comment") == 5
    assert s.get("note", "n1")["complete"] is True
    calls = len(a.calls)
    asyncio.run(Collector(s, a).run())
    assert s.count("comment") == 5
    assert len(a.calls) == calls
    assert {sort for _, _, sort in a.calls} == {"time_descending", "general", "popularity_descending"}


def test_stalled_cursor_never_becomes_complete(tmp_path):
    s = store_fixture(tmp_path)
    asyncio.run(Collector(s, FixtureAdapter(stall=True)).run())
    assert s.meta()["status"] == "partial"
    assert s.get("note", "n1")["comments"]["stop_reason"] == "cursor_stalled"
    assert s.get("note", "n1")["complete"] is False


def test_search_reaches_100_nonempty_pages_across_sorts_without_50_note_cap(tmp_path):
    class Adapter(FixtureAdapter):
        async def search(self, keyword, page, search_id, sort):
            self.calls.append((keyword, page, sort))
            return {"items": [{"note_id": f"{keyword}-{sort}-{page}", "title": keyword}], "has_more": page < 50}
    s = store_fixture(tmp_path)
    a = Adapter()
    asyncio.run(Collector(s, a).run())
    assert len(a.calls) == 300
    assert s.count("note") == 300
    for word in ["libtv", "即梦", "updream"]:
        assert sum(v["nonempty_pages"] for _, v in s.items("search") if v["keyword"] == word) == 100
    assert s.meta()["status"] == "partial"  # fixture has no observed detail token


def test_weekly_report_filters_publication_date_and_keeps_missing_sentiment(tmp_path):
    s = store_fixture(tmp_path)
    s.put("note", "one", {"search": {}, "detail_done": True, "complete": False, "brands": ["libtv"], "detail": {"title": "libtv 使用反馈", "time": datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1000, "counts": {}}})
    s.put("note", "two", {"search": {"title": "无日期 libtv"}, "brands": ["libtv"], "complete": False})
    notes, docs = corpus(s)
    report = build_report(s, notes, docs)
    assert report["demo"] is False
    assert report["brands"][0]["volume"] == 1
    assert report["brands"][0]["positive_rate"] is None
    assert report["brands"][0]["interactions"] is None
    assert report["quality"]["undated_notes"] == 1
    assert report["models"]["sentiment"]["state"] == "awaiting_labels"


def test_annotation_csv_is_not_erased_when_queue_is_refreshed(tmp_path):
    s = store_fixture(tmp_path)
    docs = [{"kind": "comment", "id": "c1", "note_id": "n1", "text": "产品好用"}]
    ensure_annotation_queue(s, docs)
    p = tmp_path / "sentiment-labels.csv"
    p.write_text('id,note_id,text,label,source\nc1,n1,产品好用,positive,human_review\n', encoding="utf-8-sig")
    assert ensure_annotation_queue(s, docs)[0]["label"] == "positive"


def test_real_model_training_requires_reviewed_labels(tmp_path):
    s = store_fixture(tmp_path)
    with pytest.raises(ValueError, match="45 reviewed"):
        train_sentiment(s)
    assert not (tmp_path / "sentiment-svm.joblib").exists()


def test_weekly_api_validates_100_pages_without_live_egress(tmp_path, monkeypatch):
    m = Manager(tmp_path)
    async def service():
        return object()
    app = FastAPI()
    app.include_router(router(m, service, lambda request: None))
    monkeypatch.setattr(m, "create", lambda config: {"config": config})
    c = TestClient(app)
    assert c.post('/v1/xhs/weekly/jobs', json={"search_pages": 99}).status_code == 422
    r = c.post('/v1/xhs/weekly/jobs', json={"search_pages": 100})
    assert r.status_code == 202
    assert r.json()["config"]["primary"] == "libtv"
    assert c.get('/v1/xhs/weekly/jobs/invalid/report').status_code == 404
