from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re

from .store import atomic_json, now


def tokenize_chinese(text):
    import jieba
    return [token.strip() for token in jieba.lcut(text) if len(token.strip()) >= 2 and re.search(r"[A-Za-z\u4e00-\u9fff]", token)]


def topic_input(text):
    """Retain raw comments in storage, but exclude low-information subscription bots."""
    if len(text) < 6 or re.fullmatch(r"[\W\d哈啊哦嗯嘿嘻呵]+", text):
        return False
    if "@点点" in text or re.search(r"收到[啦了！!，, ]*.*帮你蹲|已经订阅过|第一时间来评论区喊你|我一直在帮你盯着", text):
        return False
    return True


def train_topics(store, docs):
    import jieba
    import numpy as np
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    from .analysis import STOP_WORDS
    unique = list(dict.fromkeys(d["text"] for d in docs if topic_input(d["text"])))
    if len(unique) < 20:
        return {}, [], {"state": "insufficient_samples", "sample_size": len(unique)}
    encoder_name = store.meta()["config"]["embedding_model"]
    store.meta(analysis_stage="embeddings")
    cached = Path.home() / ".cache/huggingface/hub" / ("models--" + encoder_name.replace("/", "--")) / "snapshots"
    snapshots = sorted(cached.glob("*")) if cached.exists() else []
    from .semantic import encoder as shared_encoder
    encoder = shared_encoder(encoder_name)
    old_texts = []
    index_path, vector_path = store.directory / "embedding-index.json", store.directory / "topic-embeddings.npy"
    if index_path.exists():
        old_index = json.loads(index_path.read_text(encoding="utf-8"))
        if old_index.get("model") == encoder_name:
            old_texts = old_index["texts"]
    elif (store.directory / "topic-assignments.json").exists():
        old_texts = list(json.loads((store.directory / "topic-assignments.json").read_text(encoding="utf-8")))
    old_vectors = np.load(vector_path) if vector_path.exists() else None
    cache = {text: i for i, text in enumerate(old_texts)} if old_vectors is not None and len(old_texts) == len(old_vectors) else {}
    vectors = np.empty((len(unique), encoder.get_sentence_embedding_dimension()), dtype=np.float32)
    missing = []
    for i, text in enumerate(unique):
        if text in cache:
            vectors[i] = old_vectors[cache[text]]
        else:
            missing.append(i)
    if missing:
        vectors[missing] = encoder.encode([unique[i] for i in missing], batch_size=32, normalize_embeddings=True, show_progress_bar=True)
    np.save(vector_path, vectors)
    atomic_json(index_path, {"model": encoder_name, "texts": unique})
    store.meta(analysis_stage="bertopic_fit")
    model = BERTopic(embedding_model=encoder,
        umap_model=UMAP(n_neighbors=min(15, len(unique) - 1), n_components=min(5, len(unique) - 2), min_dist=0.0, metric="cosine", random_state=42),
        hdbscan_model=HDBSCAN(min_cluster_size=max(5, min(35, len(unique) // 35)), min_samples=3, metric="euclidean", prediction_data=True),
        vectorizer_model=CountVectorizer(tokenizer=tokenize_chinese, token_pattern=None, stop_words=STOP_WORDS + ["一下", "什么", "现在", "感觉", "还有", "怎么", "真的", "这么", "就是", "但是", "这样", "时候", "看到", "目前", "觉得", "知道", "大家"] + [name.casefold() for name in [store.meta()["config"]["primary"], *store.meta()["config"]["competitors"]]]),
        calculate_probabilities=False, verbose=True)
    assigned, _ = model.fit_transform(unique, vectors)
    lookup = dict(zip(unique, map(int, assigned)))
    info = []
    for topic_id in sorted(set(assigned)):
        if topic_id == -1:
            continue
        words = model.get_topic(topic_id) or []
        info.append({"id": int(topic_id), "keywords": [word for word, _ in words[:8]], "training_count": int(sum(t == topic_id for t in assigned))})
    model.get_topic_info().to_csv(store.directory / "bertopic-topics.csv", index=False, encoding="utf-8-sig")
    atomic_json(store.directory / "topic-assignments.json", lookup)
    store.meta(analysis_stage="bertopic_save_reload")
    path = store.directory / "bertopic-model.joblib"
    # Preserve fitted UMAP/HDBSCAN/c-TF-IDF. The fixed encoder is reattached on load.
    pending_path = store.directory / "bertopic-model.next.joblib"
    model.save(str(pending_path), serialization="pickle", save_embedding_model=False)
    loaded = BERTopic.load(str(pending_path), embedding_model=encoder)
    sample = unique[:3]
    predicted, _ = loaded.transform(sample, embeddings=vectors[:3])
    if len(predicted) != len(sample):
        raise ValueError("Reloaded topic pipeline did not return predictions")
    pending_path.replace(path)
    metadata = {"state": "trained", "algorithm": "BERTopic: MiniLM + UMAP + HDBSCAN + c-TF-IDF", "embedding_model": encoder_name,
        "fit_sample_size": len(unique), "input_texts": len(docs), "filtered_or_duplicate_count": len(docs) - len(unique),
        "topic_count": len(info), "noise_count": int(sum(t == -1 for t in assigned)),
        "fit_scope": "all collected history; weekly counts filtered separately", "generated_at": now(),
        "artifact": path.name, "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "serialization": "full fitted pipeline; fixed MiniLM encoder loaded by model id",
        "reload_verified": True, "reload_sample_predictions": list(map(int, predicted)),
        "embedding_cache_hits": len(unique) - len(missing),
        "versions": {name: version(name) for name in ["bertopic", "sentence-transformers", "umap-learn", "hdbscan", "scikit-learn"]}}
    atomic_json(store.directory / "topic-model-metadata.json", metadata)
    return lookup, info, metadata
