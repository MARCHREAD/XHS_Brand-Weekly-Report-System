from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from .store import Store, atomic_json, now


LABELS = ["negative", "neutral", "positive"]
STOP_WORDS = ["的", "了", "是", "我", "你", "他", "她", "和", "在", "就", "都", "也", "这个", "那个", "一个", "我们", "你们", "可以", "视频", "笔记", "小红书"]


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"https?://\S+|\[[^\]]{1,20}\]", " ", str(text or ""))).strip()


def published(value):
    if not value:
        return None
    try:
        number = float(value)
        if number > 1e11:
            number /= 1000
        return datetime.fromtimestamp(number, timezone(timedelta(hours=8))).date().isoformat()
    except (ValueError, TypeError, OSError):
        return None


def corpus(store):
    """Brand attribution uses observed text, not just the search term."""
    config = store.meta()["config"]
    brands = [config["primary"], *config["competitors"]]
    notes, docs = {}, []
    for key, record in store.items("note"):
        note = record.get("detail") or record["search"]
        text = clean(f"{note.get('title', '')} {note.get('desc', '')}")
        matches = [brand for brand in brands if brand.casefold() in text.casefold()]
        notes[key] = {"id": key, "title": note.get("title", ""), "text": text, "brands": matches, "search_brands": record["brands"], "date": published(note.get("time")), "counts": note.get("counts", {}), "detail_done": record.get("detail_done", False), "comments_complete": record.get("complete", False)}
        if len(text) >= 6 and record.get("detail_done") and matches:
            docs.append({"id": f"note:{key}", "note_id": key, "kind": "note", "text": text, "date": notes[key]["date"], "brands": matches})
    for key, record in store.items("comment"):
        parent = notes.get(record["note_id"])
        if not parent or not parent["brands"]:
            continue
        c = record["comment"]
        text = clean(c.get("content"))
        if len(text) >= 2:
            # These are thread-level attributions, not an aspect-specific sentiment claim.
            docs.append({"id": f"comment:{key}", "note_id": parent["id"], "kind": "comment", "text": text, "date": published(c.get("create_time")), "brands": parent["brands"]})
    return notes, docs


def ensure_annotation_queue(store, docs):
    from .sentiment import merge_labels
    existing = merge_labels(store)
    path = store.directory / "sentiment-labels.csv"
    rows = []
    seen = set()
    for doc in docs:
        if doc["kind"] != "comment" or doc["text"] in seen:
            continue
        seen.add(doc["text"])
        row = {"id": doc["id"], "note_id": doc["note_id"], "text": doc["text"], "label": existing.get(doc["id"], {}).get("label", ""), "source": existing.get(doc["id"], {}).get("source", "")}
        rows.append(row)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "note_id", "text", "label", "source"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def train_sentiment(store):
    from .sentiment import train
    return train(store, corpus(store)[1])


def topics(store, docs):
    from .topics import train_topics
    return train_topics(store, docs)


def build_report(store, notes, docs, lookup=None, topic_info=None, topic_model=None, sentiment=None, metrics=None):
    config = store.meta()["config"]
    start, end = config["week_start"], config["week_end"]
    previous_start = (date.fromisoformat(start) - timedelta(days=7)).isoformat()
    lookup, topic_info, sentiment = lookup or {}, topic_info or [], sentiment or {}
    weekly_notes = [n for n in notes.values() if n["date"] and start <= n["date"] <= end and n["brands"]]
    current_docs = [d for d in docs if d["date"] and start <= d["date"] <= end]
    by_brand = []
    for brand in [config["primary"], *config["competitors"]]:
        subset = [n for n in weekly_notes if brand in n["brands"]]
        text_subset = [d for d in current_docs if brand in d["brands"] and d["kind"] == "comment"]
        dist = Counter(sentiment[d["id"]] for d in text_subset if d["id"] in sentiment)
        complete_counts, interactions = 0, 0
        for n in subset:
            counts = [n["counts"].get(k, {}).get("value") for k in ["liked", "collected", "comment", "share"]]
            if all(isinstance(x, int) for x in counts):
                interactions += sum(counts)
                complete_counts += 1
        valid = sum(dist[label] for label in LABELS)
        by_brand.append({"brand": brand, "volume": len(subset), "interactions": interactions if complete_counts else None, "complete_metric_notes": complete_counts, "collected_history_notes": sum(brand in n["brands"] for n in notes.values()), "sentiment": {label: dist[label] for label in LABELS}, "positive_rate": dist["positive"] / valid if valid else None, "pending_texts": dist["pending"], "weekly_comment_texts": len(text_subset)})
    topic_results = []
    for topic in topic_info:
        selected = [d for d in current_docs if lookup.get(d["text"]) == topic["id"]]
        if not selected:
            continue
        dist = Counter(sentiment[d["id"]] for d in selected if d["id"] in sentiment)
        topic_results.append({**topic, "weekly_texts": len(selected), "weekly_notes": len({d["note_id"] for d in selected}), "sentiment": dict(dist), "evidence": [{"note_id": d["note_id"], "text": d["text"][:300], "kind": d["kind"]} for d in selected[:5]]})
    topic_results.sort(key=lambda x: x["weekly_texts"], reverse=True)
    history_topics = []
    for topic in topic_info:
        selected = [d for d in docs if lookup.get(d["text"]) == topic["id"]]
        history_topics.append({**topic, "scope": "collected_history", "text_count": len(selected), "evidence": [{"note_id": d["note_id"], "text": d["text"][:240], "date": d["date"]} for d in selected[:3]]})
    return {"source": "xiaohongshu_live_collection", "demo": False, "generated_at": now(), "config": config, "collection": store.summary(), "brands": by_brand, "topics": topic_results, "history_topics": history_topics, "models": {"topic": topic_model or {"state": "not_trained"}, "sentiment": {"state": "trained" if metrics else "awaiting_labels", "metrics": metrics}}, "quality": {"dated_notes": sum(bool(n["date"]) for n in notes.values()), "undated_notes": sum(not n["date"] for n in notes.values()), "weekly_notes": len(weekly_notes), "weekly_texts": len(current_docs), "previous_window": [previous_start, start], "comparison_available": False, "notes": ["Samples are keyword search results, not the full platform.", "Brand attribution uses literal observed title/body; multi-brand notes can appear in more than one brand.", "Sentiment is attributed at thread level; it is not an aspect-specific brand opinion.", "Interaction values are capture-time cumulative snapshots, not interaction increments within the week.", "No prior collection baseline: growth rates and historical interaction deltas remain unavailable."]}}


def analyze(store, run_topics=True):
    store.meta(analysis_status="running", analysis_error=None, analysis_stage="preparing")
    input_revision = store.get("meta", "dataset", {}).get("revision", 0)
    notes, docs = corpus(store)
    ensure_annotation_queue(store, docs)
    lookup, info, topic_model = {}, [], {"state": "not_trained"}
    if run_topics:
        lookup, info, topic_model = topics(store, docs)
    sentiment, metrics = {}, None
    model_path = store.directory / "sentiment-svm.joblib"
    if model_path.exists():
        import joblib
        model = joblib.load(model_path)
        comments = [d for d in docs if d["kind"] == "comment"]
        if comments:
            import numpy as np
            texts = [d["text"] for d in comments]
            predictions = model.predict(texts)
            scores = np.sort(model.decision_function(texts), axis=1)
            margins = scores[:, -1] - scores[:, -2]
            sentiment = {d["id"]: str(label) if margin >= .2 else "pending" for d, label, margin in zip(comments, predictions, margins)}
        metrics = json.loads((store.directory / "sentiment-metrics.json").read_text(encoding="utf-8"))
    report = build_report(store, notes, docs, lookup, info, topic_model, sentiment, metrics)
    report["data_revision"] = input_revision
    from .dashboard import project
    report["dashboard"] = project(report, notes, docs, lookup, info, sentiment)
    report["_analysis"] = {"lookup": lookup, "topics": info, "predictions": sentiment}
    atomic_json(store.directory / "topic-info.json", info)
    history = store.directory / "report-history"
    history.mkdir(exist_ok=True)
    old_path = store.directory / "report.json"
    if old_path.exists():
        old = json.loads(old_path.read_text(encoding="utf-8"))
        stamp = old["generated_at"].replace(":", "").replace(".", "")
        atomic_json(history / f"{stamp}.json", old)
    stamp = report["generated_at"].replace(":", "").replace(".", "")
    atomic_json(history / f"{stamp}.json", report)
    atomic_json(store.directory / "report.json", report)
    atomic_json(store.directory / "sentiment-predictions.json", sentiment)
    store.meta(analysis_status="completed", analysis_stage="finished", analysis_finished_at=now(), annotation_rows=len([d for d in docs if d["kind"] == "comment"]))
    print(json.dumps({"topic": topic_model, "sentiment": report["models"]["sentiment"]["state"], "weekly_notes": report["quality"]["weekly_notes"]}, ensure_ascii=False))
    return report
