from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import pickle

from fastapi import FastAPI
from fastapi.testclient import TestClient

from collector.weekly.analysis import analyze
from collector.weekly.dashboard import project
from collector.weekly.manager import Manager, default_config
from collector.weekly.routes import router
from collector.weekly.sentiment import merge_labels, train
from collector.weekly.store import Store
from collector.weekly.topics import topic_input, tokenize_chinese


def store(tmp_path):
    s = Store(tmp_path)
    s.meta(job_id='a'*32, config={**default_config(), 'svm_semantic_features':False}, status='paused')
    return s


def test_meta_updates_are_atomic_and_dataset_revision_excludes_status_updates(tmp_path):
    s = store(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: s.meta(**{f'field_{i}': i}), range(20)))
    assert all(s.meta()[f'field_{i}'] == i for i in range(20))
    assert s.get('meta', 'dataset') is None
    s.put('note', 'n1', {})
    revision = s.get('meta', 'dataset')['revision']
    s.meta(analysis_status='running')
    assert s.get('meta', 'dataset')['revision'] == revision
    s.put('comment', 'c1', {})
    assert s.get('meta', 'dataset')['revision'] == revision + 1


def test_human_labels_win_over_stale_csv(tmp_path):
    s = store(tmp_path)
    s.put('labels', 'sentiment', {'c1': {'label':'negative', 'source':'human_review'}})
    (tmp_path/'sentiment-labels.csv').write_text('id,label,source\nc1,positive,ai_assisted_review\n',encoding='utf-8-sig')
    assert merge_labels(s)['c1']['label'] == 'negative'


def test_grouped_retraining_keeps_frozen_holdout_and_separate_evaluation_artifact(tmp_path):
    s = store(tmp_path)
    docs, labels = [], {}
    for i in range(90):
        label = ['positive','neutral','negative'][i%3]
        phrase = {'positive':'很好用喜欢', 'neutral':'请问教程在哪里', 'negative':'效果很差太贵'}[label]
        key = f'c{i}'
        docs.append({'id':key, 'note_id':f'n{i//3}', 'kind':'comment', 'text':f'{phrase} 第{i}次体验'})
        labels[key] = {'label':label, 'source':'human_review'}
    s.put('labels','sentiment',labels)
    first = train(s, docs)
    for i in range(90,105):
        label=['positive','neutral','negative'][i%3]
        docs.append({'id':f'c{i}', 'note_id':f'n{i//3}', 'kind':'comment', 'text':f'追加样本{i} {label}'})
        labels[f'c{i}']={'label':label,'source':'human_review'}
    s.put('labels','sentiment',labels)
    second = train(s, docs)
    assert set(first['test_ids']) == set(second['test_ids'])
    assert second['train_count'] > first['train_count']
    assert second['reload_verified'] is True
    assert (tmp_path/'training-history'/second['evaluation_model']).exists()
    split = json.loads((tmp_path/'sentiment-evaluation-split.json').read_text(encoding='utf-8'))
    reserved = set(split['reserved_note_ids'])
    assert all(next(d['note_id'] for d in docs if d['id']==key) in reserved for key in second['test_ids'])


def test_topic_tokenizer_is_serializable_and_low_information_texts_are_excluded():
    assert pickle.loads(pickle.dumps(tokenize_chinese)) is tokenize_chinese
    assert not topic_input('收到啦！帮你蹲后续，有更新喊你')
    assert not topic_input('@点点 更新提醒我')
    assert not topic_input('哈哈哈哈哈哈')
    assert topic_input('这个工具的包装和价格值得讨论')
    words=tokenize_chinese('！，，。。。 libtv 积分价格很好，生成效果很好！')
    assert '积分' in words
    assert all(len(word)>=2 and word not in {'！','，','。'} for word in words)


def test_semantic_transformer_saves_only_model_identity_and_uses_fixed_features(monkeypatch):
    import numpy as np
    from collector.weekly import semantic
    class FakeEncoder:
        def encode(self, texts, **kwargs):
            return np.array([[len(text), 1., 0.] for text in texts],dtype=np.float32)
    monkeypatch.setattr(semantic,'encoder',lambda name:FakeEncoder())
    transformer=semantic.FixedMiniLM('offline-fixture')
    values=transformer.fit_transform(['非常好','太差'])
    restored=pickle.loads(pickle.dumps(transformer))
    assert restored.__dict__=={'model_name':'offline-fixture'}
    assert np.array_equal(values,restored.transform(['非常好','太差']))


def test_dashboard_series_missing_fields_and_pending_denominator_are_truthful():
    report={'config':default_config(),'generated_at':'2026-10-26T00:00:00+00:00','collection':{'notes':3,'notes_complete':1},'models':{'sentiment':{'state':'trained'}}}
    notes={
        'a':{'id':'a','title':'libtv','date':'2026-10-20','detail_done':True,'comments_complete':True,'brands':['libtv'],'counts':{k:{'value':2} for k in ['liked','collected','comment','share']}},
        'b':{'id':'b','title':'即梦','date':'2026-10-21','detail_done':True,'comments_complete':False,'brands':['即梦'],'counts':{}},
        'c':{'id':'c','title':'updream','date':None,'detail_done':False,'comments_complete':False,'brands':['updream'],'counts':{}},
    }
    docs=[{'id':f'c{i}','kind':'comment','note_id':'a','date':'2026-10-20','brands':['libtv'],'text':'生成效果很好'} for i in range(4)]
    result=project(report,notes,docs,{},[],{'c0':'positive','c1':'negative','c2':'pending'})
    assert result['kpis']['positive_rate'] == .5
    assert result['kpis']['pending_texts'] == 2
    assert result['kpis']['volume'] == 1
    assert sum(row['volume'] for row in result['trend']) == 1
    assert result['kpis']['interactions'] == 8
    assert result['competitors'][1]['interactions'] is None
    assert result['competitors'][2]['volume'] == 0
    assert result['sample_quality']['growth_available'] is False
    other=project(report,notes,docs,{},[],{},brand='即梦')
    assert other['kpis']['positive_rate'] is None


def test_report_projection_and_snapshot_endpoints_use_local_data_only(tmp_path):
    m=Manager(tmp_path);s=Store(m.root/('a'*32));s.meta(job_id='a'*32,config=default_config(),status='paused')
    s.put('note','n1',{'detail_done':True,'complete':True,'brands':['libtv'],'search':{},'detail':{'title':'libtv 实际反馈','time':datetime(2026,10,20,tzinfo=timezone.utc).timestamp()*1000,'counts':{}}})
    analyze(s,run_topics=False)
    async def service(): return object()
    app=FastAPI();app.include_router(router(m,service,lambda request:None));c=TestClient(app)
    response=c.get(f'/v1/xhs/weekly/jobs/{"a"*32}/report')
    assert response.status_code==200
    value=response.json()
    assert value['dashboard']['kpis']['volume']==1
    assert value['stale'] is False
    assert '_analysis' not in value
    assert c.get(f'/v1/xhs/weekly/jobs/{"a"*32}/report?brand=other').status_code==422
    snapshots=c.get(f'/v1/xhs/weekly/jobs/{"a"*32}/snapshots').json()
    archived=c.get(f'/v1/xhs/weekly/jobs/{"a"*32}/report',params={'snapshot':snapshots[0]['id']}).json()
    assert archived['dashboard']['kpis']['volume']==1
    assert c.get(f'/v1/xhs/weekly/jobs/{"a"*32}/report',params={'snapshot':'../secret'}).status_code==422
