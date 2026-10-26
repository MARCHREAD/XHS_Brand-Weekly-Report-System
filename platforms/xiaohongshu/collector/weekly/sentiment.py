"""Grouped, reproducible sentiment training with an untouched holdout."""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json

from .store import atomic_json, now


LABELS = ["negative", "neutral", "positive"]


def merge_labels(store):
    labels = store.get("labels", "sentiment", {})
    path = store.directory / "sentiment-labels.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("label") not in LABELS:
                    continue
                previous = labels.get(row["id"], {})
                # A stale exported CSV must never overwrite a newer human UI annotation.
                if previous.get("source") == "human_review":
                    continue
                labels[row["id"]] = {"label": row["label"], "source": row.get("source") or "csv_review"}
    return labels


def train(store, docs):
    import joblib
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import GroupShuffleSplit, StratifiedGroupKFold, GridSearchCV
    from sklearn.pipeline import Pipeline, FeatureUnion
    from sklearn.svm import LinearSVC

    by_id = {doc["id"]: doc for doc in docs if doc["kind"] == "comment"}
    labels = merge_labels(store)
    # Prefer human review if identical texts happen to have different annotations.
    ordered = sorted(labels.items(), key=lambda row: row[1].get("source") != "human_review")
    rows, seen = [], set()
    for key, annotation in ordered:
        doc = by_id.get(key)
        if not doc or annotation.get("label") not in LABELS or doc["text"] in seen:
            continue
        seen.add(doc["text"])
        rows.append({**doc, **annotation})
    counts = Counter(row["label"] for row in rows)
    if len(rows) < 45 or any(counts[label] < 8 for label in LABELS):
        raise ValueError(f"Need at least 45 reviewed comments and 8 per class; observed {dict(counts)}")
    texts = np.array([r["text"] for r in rows])
    y = np.array([r["label"] for r in rows])
    groups = np.array([r["note_id"] for r in rows])
    split_path = store.directory / "sentiment-evaluation-split.json"
    previous_metrics = store.directory / "sentiment-metrics.json"
    if split_path.exists():
        split = json.loads(split_path.read_text(encoding="utf-8"))
    elif previous_metrics.exists():
        old = json.loads(previous_metrics.read_text(encoding="utf-8"))
        ids = set(old.get("test_ids", []))
        split = {"test_ids": sorted(ids), "reserved_note_ids": sorted({by_id[key]["note_id"] for key in ids if key in by_id}), "origin": "preserved previous evaluation holdout", "created_at": now()}
    else:
        split = None
    if split is None:
        for seed in range(42, 142):
            a, b = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=seed).split(texts, y, groups))
            if len(a) >= len(rows) * .6 and all(sum(y[a] == label) >= 5 and sum(y[b] == label) >= 2 for label in LABELS):
                split = {"test_ids": [rows[i]["id"] for i in b], "reserved_note_ids": sorted(set(groups[b])), "origin": "grouped holdout fixed before parameter search", "created_at": now()}
                break
    if split is None:
        raise ValueError("Need class coverage in distinct note groups for an honest holdout")
    atomic_json(split_path, split)
    test_ids, reserved = set(split["test_ids"]), set(split["reserved_note_ids"])
    test = np.array([i for i, row in enumerate(rows) if row["id"] in test_ids], dtype=int)
    heldout_texts = {rows[i]["text"] for i in test}
    train = np.array([i for i, row in enumerate(rows) if row["note_id"] not in reserved and row["text"] not in heldout_texts], dtype=int)
    if not len(test) or len(set(y[train])) < 3:
        raise ValueError("The fixed holdout or training classes are missing; review annotations")
    assert not set(groups[train]) & set(groups[test])
    store.meta(analysis_stage="svm_grouped_cv")
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), max_features=60000, sublinear_tf=True)
    use_semantics = store.meta()["config"].get("svm_semantic_features", False)
    if use_semantics:
        from .semantic import FixedMiniLM
        features = FeatureUnion([("tfidf", vectorizer), ("semantic", FixedMiniLM())], transformer_weights={"tfidf":1.0, "semantic":.5})
        pipeline = Pipeline([("features", features), ("svm", LinearSVC(class_weight="balanced", random_state=42, max_iter=10000))])
        parameters = {"features__tfidf__ngram_range": [(1, 3), (2, 4)], "svm__C": [.25, 1.0, 4.0]}
    else:
        pipeline = Pipeline([("tfidf", vectorizer), ("svm", LinearSVC(class_weight="balanced", random_state=42, max_iter=10000))])
        parameters = {"tfidf__ngram_range": [(1, 3), (2, 4)], "svm__C": [.25, 1.0, 4.0]}
    splits = list(StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=42).split(texts[train], y[train], groups[train]))
    usable_cv = len(set(groups[train])) >= 6 and all(len(set(y[train][a])) == 3 for a, _ in splits)
    best_params, cv_score = {}, None
    if usable_cv:
        search = GridSearchCV(pipeline, parameters, scoring="f1_macro", cv=splits, n_jobs=1, error_score="raise")
        search.fit(texts[train], y[train])
        model, best_params, cv_score = search.best_estimator_, search.best_params_, float(search.best_score_)
    else:
        model = pipeline.fit(texts[train], y[train])
    predictions = model.predict(texts[test])
    report = classification_report(y[test], predictions, labels=LABELS, output_dict=True, zero_division=0)
    comparison = None
    if previous_metrics.exists():
        old = json.loads(previous_metrics.read_text(encoding="utf-8"))
        comparison = {"generated_at": old["generated_at"], "train_count": old["train_count"], "test_count": old["test_count"], "accuracy": old["classification_report"]["accuracy"], "macro_f1": old["classification_report"]["macro avg"]["f1-score"], "negative_recall": old["classification_report"]["negative"]["recall"], "same_test_ids": set(old.get("test_ids", [])) == {rows[i]["id"] for i in test}}
    stamp = now().replace(":", "").replace(".", "")
    history = store.directory / "training-history"
    history.mkdir(exist_ok=True)
    eval_model = history / f"svm-evaluation-{stamp}.joblib"
    joblib.dump(model, eval_model)
    metrics = {"model": "character TF-IDF + LinearSVC", "class_weight": "balanced", "best_params": best_params, "cv_macro_f1": cv_score, "cv_splits": 3 if usable_cv else 0, "train_count": len(train), "test_count": len(test), "labeled_total": len(rows), "reserved_unscored_count": len(rows) - len(train) - len(test), "classes": dict(counts), "label_sources": dict(Counter(r.get("source", "unknown") for r in rows)), "training_label_sources": dict(Counter(rows[i].get("source", "unknown") for i in train)), "test_label_sources": dict(Counter(rows[i].get("source", "unknown") for i in test)), "split": "fixed test comment ids; whole note groups reserved; parameters selected by training-only grouped CV", "classification_report": report, "confusion_matrix": confusion_matrix(y[test], predictions, labels=LABELS).tolist(), "label_order": LABELS, "test_ids": [rows[i]["id"] for i in test], "generated_at": now(), "independent_human_ground_truth": all(rows[i].get("source") == "human_review" for i in test), "experimental": True, "previous_evaluation": comparison, "evaluation_model": eval_model.name, "pending_margin_threshold": .2}
    # Keep a separate frozen evaluation classifier. Refit production on all reviewed data.
    model.fit(texts, y)
    joblib.dump(model, store.directory / "sentiment-svm.joblib")
    loaded = joblib.load(store.directory / "sentiment-svm.joblib")
    assert loaded.predict([rows[0]["text"]])[0] in LABELS
    metrics["reload_verified"] = True
    metrics["features"] = "character TF-IDF + fixed MiniLM semantic vectors" if use_semantics else "character TF-IDF"
    metrics["encoder_finetuned"] = False
    metrics["artifact_sha256"] = hashlib.sha256((store.directory / "sentiment-svm.joblib").read_bytes()).hexdigest()
    atomic_json(history / f"svm-metrics-{stamp}.json", metrics)
    atomic_json(store.directory / "sentiment-metrics.json", metrics)
    store.put("labels", "sentiment", labels)
    return metrics
