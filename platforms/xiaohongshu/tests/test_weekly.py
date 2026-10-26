import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from collector.weekly.analysis import build_report, corpus, ensure_annotation_queue, train_sentiment
from collector.weekly.collection import Collector, run_with_backoff
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


def test_deferred_note_runs_last_and_resumes_saved_reply_cursor(tmp_path):
    s = store_fixture(tmp_path)
    for word in ['libtv', '即梦', 'updream']:
        s.put('search',word,{'keyword':word,'nonempty_pages':100,'stop_reason':'target_reached'})
    s.put('note','z-delayed',{'search':{'note_id':'z-delayed','xsec_token':'offline'},'brands':['libtv'],'detail_done':True,'complete':False,'deferred':True,'comments':{'cursor':'main-end','seen':[''],'pages':79,'complete':True}})
    s.put('note','a-next',{'search':{'note_id':'a-next','xsec_token':'offline'},'brands':['libtv'],'detail_done':False,'complete':False})
    s.put('root','z-delayed:r',{'note_id':'z-delayed','root_id':'r','cursor':'saved-reply-cursor','seen':['earlier'],'complete':False})
    s.put('comment','existing',{'note_id':'z-delayed','comment':{'comment_id':'existing','content':'already saved'}})
    assert s.summary()['notes_deferred']==1
    assert s.summary()['notes_incomplete']==2
    calls=[]
    class Adapter(FixtureAdapter):
        async def comments(self,note,cursor):
            calls.append(('main',note['note_id'],cursor))
            return {'comments':[],'has_more':False,'cursor':''}
        async def replies(self,note,root_id,cursor):
            calls.append(('reply',note['note_id'],cursor))
            return {'comments':[],'has_more':False,'cursor':''}
    asyncio.run(Collector(s,Adapter()).run())
    assert calls==[('main','a-next',''),('reply','z-delayed','saved-reply-cursor')]
    assert s.get('comment','existing')['comment']['content']=='already saved'
    assert s.get('note','z-delayed')['comments']['pages']==79
    assert s.get('note','z-delayed')['complete'] is True
    assert s.summary()['notes_deferred']==0
    assert s.summary()['status']=='completed'


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


def test_stale_worker_handle_does_not_mark_new_worker_interrupted(tmp_path):
    manager=Manager(tmp_path)
    job_id='b'*32
    s=Store(manager.root/job_id)
    s.meta(job_id=job_id,status='running',pid=200,created_at='2026-10-26')
    class ExitedProcess:
        pid=100
        returncode=0
        def poll(self): return 0
    manager.processes[(job_id,'collect')]=ExitedProcess()
    assert manager.latest()[0]['status']=='running'
    s.meta(pid=100)
    assert manager.latest()[0]['status']=='interrupted'


def test_frequency_limit_waits_before_retry_without_live_requests(tmp_path, monkeypatch):
    from collector.weekly import collection
    s=store_fixture(tmp_path)
    instant=[datetime(2026,10,26,tzinfo=timezone.utc)]
    calls=[]
    class FakeCollector:
        def __init__(self,store,adapter):self.store=store
        async def run(self):
            calls.append(instant[0])
            self.store.meta(status='rate_limited' if len(calls)==1 else 'completed')
    async def advance(seconds): instant[0]+=timedelta(seconds=seconds)
    monkeypatch.setattr(collection,'Collector',FakeCollector)
    asyncio.run(run_with_backoff(s,object(),cooldown_seconds=30,tick_seconds=5,clock=lambda:instant[0],sleep=advance))
    assert len(calls)==2
    assert (calls[1]-calls[0]).total_seconds()==30
    assert s.meta()['status']=='completed'


def test_cooldown_can_be_paused_without_starting_collection(tmp_path):
    s=store_fixture(tmp_path)
    start=datetime(2026,10,26,tzinfo=timezone.utc)
    s.meta(cooldown_until=(start+timedelta(minutes=30)).isoformat())
    async def pause(seconds):s.meta(status='pause_requested')
    asyncio.run(run_with_backoff(s,object(),clock=lambda:start,sleep=pause))
    assert s.meta()['status']=='paused'
    assert s.meta()['cooldown_until'] is not None
