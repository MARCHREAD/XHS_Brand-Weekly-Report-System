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
    existing = store.get("labels", "sentiment", {})
    path = store.directory / "sentiment-labels.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("label") in LABELS:
                    existing[row["id"]] = {"label": row["label"], "source": row.get("source") or "csv_review"}
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
    import joblib
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.pipeline import Pipeline
    from sklearn.svm import LinearSVC

    _, docs = corpus(store)
    by_id = {d["id"]: d for d in docs if d["kind"] == "comment"}
    labels = store.get("labels", "sentiment", {})
    path = store.directory / "sentiment-labels.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("label") in LABELS:
                    labels[row["id"]] = {"label": row["label"], "source": row.get("source") or "csv_review"}
    rows, seen = [], set()
    for key, annotation in labels.items():
        doc = by_id.get(key)
        if not doc or annotation.get("label") not in LABELS or doc["text"] in seen:
            continue
        seen.add(doc["text"])
        rows.append({**doc, **annotation})
    counts = Counter(r["label"] for r in rows)
    if len(rows) < 45 or any(counts[c] < 8 for c in LABELS):
        raise ValueError(f"Need at least 45 reviewed comments and 8 per class; observed {dict(counts)}")
    texts = np.array([r["text"] for r in rows])
    y = np.array([r["label"] for r in rows])
    # Whole notes stay in one side of the split. Text duplicates were removed beforehand.
    groups = np.array([r["note_id"] for r in rows])
    train = test = None
    for seed in range(42, 142):
        a, b = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=seed).split(texts, y, groups))
        if (len(a) >= len(rows) * .6 and len(b) >= 6
                and all(sum(y[a] == label) >= 5 and sum(y[b] == label) >= 2 for label in LABELS)):
            train, test = a, b
            break
    if train is None:
        raise ValueError("Need class coverage in distinct note groups for an honest holdout")
    model = Pipeline([("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(1, 3), min_df=1, max_features=40000, sublinear_tf=True)), ("svm", LinearSVC(C=1.0, class_weight="balanced", random_state=42))])
    model.fit(texts[train], y[train])
    predicted = model.predict(texts[test])
    report = classification_report(y[test], predicted, labels=LABELS, output_dict=True, zero_division=0)
    metrics = {"model": "TF-IDF character ngrams(1,3) + LinearSVC", "C": 1.0, "class_weight": "balanced", "train_count": len(train), "test_count": len(test), "classes": dict(counts), "label_sources": dict(Counter(r.get("source", "unknown") for r in rows)), "split": "grouped by note_id; identical texts deduplicated; TF-IDF fitted on training only; split constrained by class coverage and size, never by prediction scores", "classification_report": report, "confusion_matrix": confusion_matrix(y[test], predicted, labels=LABELS).tolist(), "label_order": LABELS, "test_ids": [rows[i]["id"] for i in test], "generated_at": now(), "independent_human_ground_truth": all(r.get("source") == "human_review" for r in rows), "experimental": True}
    # Production model refits reviewed examples after keeping the independent evaluation above.
    model.fit(texts, y)
    joblib.dump(model, store.directory / "sentiment-svm.joblib")
    atomic_json(store.directory / "sentiment-metrics.json", metrics)
    store.put("labels", "sentiment", labels)


def topics(store, docs):
    """Use the declared BERTopic algorithm, never substitute a keyword count silently."""
    import jieba
    import numpy as np
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    # Repeated solicitation/comments should not dominate topic fitting.
    unique = list(dict.fromkeys(d["text"] for d in docs if len(d["text"]) >= 6))
    if len(unique) < 20:
        return {}, [], {"state": "insufficient_samples", "sample_size": len(unique)}
    encoder_name = store.meta()["config"]["embedding_model"]
    store.meta(analysis_stage="embeddings")
    cached = Path.home() / ".cache/huggingface/hub" / ("models--" + encoder_name.replace("/", "--")) / "snapshots"
    snapshots = sorted(cached.glob("*")) if cached.exists() else []
    encoder = SentenceTransformer(str(snapshots[-1]) if snapshots else encoder_name, device="cpu")
    embeddings = encoder.encode(unique, show_progress_bar=True, batch_size=32, normalize_embeddings=True)
    store.meta(analysis_stage="bertopic")
    model = BERTopic(embedding_model=encoder, umap_model=UMAP(n_neighbors=min(15, len(unique) - 1), n_components=min(5, len(unique) - 2), min_dist=0.0, metric="cosine", random_state=42), hdbscan_model=HDBSCAN(min_cluster_size=max(3, min(15, len(unique) // 15)), min_samples=2, metric="euclidean", prediction_data=True), vectorizer_model=CountVectorizer(tokenizer=jieba.lcut, token_pattern=None, stop_words=STOP_WORDS), calculate_probabilities=False, verbose=True)
    assigned, _ = model.fit_transform(unique, embeddings)
    lookup = dict(zip(unique, map(int, assigned)))
    info = []
    for topic_id in sorted(set(assigned)):
        if topic_id == -1:
            continue
        words = model.get_topic(topic_id) or []
        info.append({"id": int(topic_id), "keywords": [w for w, _ in words[:8]], "training_count": int(sum(t == topic_id for t in assigned))})
    model.get_topic_info().to_csv(store.directory / "bertopic-topics.csv", index=False, encoding="utf-8-sig")
    np.save(store.directory / "topic-embeddings.npy", embeddings)
    atomic_json(store.directory / "topic-assignments.json", lookup)
    return lookup, info, {"state": "trained", "algorithm": "BERTopic: MiniLM + UMAP + HDBSCAN + c-TF-IDF", "embedding_model": encoder_name, "fit_sample_size": len(unique), "topic_count": len(info), "noise_count": sum(t == -1 for t in assigned), "fit_scope": "all collected history; weekly counts filtered separately"}


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
        by_brand.append({"brand": brand, "volume": len(subset), "interactions": interactions if complete_counts else None, "complete_metric_notes": complete_counts, "collected_history_notes": sum(brand in n["brands"] for n in notes.values()), "sentiment": {label: dist[label] for label in LABELS}, "positive_rate": dist["positive"] / sum(dist.values()) if dist else None, "weekly_comment_texts": len(text_subset)})
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
            predictions = model.predict([d["text"] for d in comments])
            sentiment = {d["id"]: str(label) for d, label in zip(comments, predictions)}
        metrics = json.loads((store.directory / "sentiment-metrics.json").read_text(encoding="utf-8"))
    report = build_report(store, notes, docs, lookup, info, topic_model, sentiment, metrics)
    atomic_json(store.directory / "report.json", report)
    atomic_json(store.directory / "sentiment-predictions.json", sentiment)
    store.meta(analysis_status="completed", analysis_stage="finished", analysis_finished_at=now(), annotation_rows=len([d for d in docs if d["kind"] == "comment"]))
    print(json.dumps({"topic": topic_model, "sentiment": report["models"]["sentiment"]["state"], "weekly_notes": report["quality"]["weekly_notes"]}, ensure_ascii=False))
    return report
