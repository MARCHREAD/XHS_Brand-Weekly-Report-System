"""Offline verification of saved models using the original fixed evaluation set.

Run from the Xiaohongshu platform directory. No collection or retraining occurs.
Only aggregate metrics are printed; original comments and identifiers stay local.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.weekly.store import Store, now


def verify(directory: Path):
    import joblib
    import numpy as np
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
    from bertopic import BERTopic
    from collector.weekly.analysis import corpus
    from collector.weekly.sentiment import merge_labels, LABELS
    from collector.weekly.semantic import encoder

    store = Store(directory)
    metrics = json.loads((directory / 'sentiment-metrics.json').read_text(encoding='utf-8'))
    topic = json.loads((directory / 'topic-model-metadata.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((directory / 'sentiment-svm.joblib').read_bytes()).hexdigest() == metrics['artifact_sha256']
    assert hashlib.sha256((directory / 'bertopic-model.joblib').read_bytes()).hexdigest() == topic['artifact_sha256']
    _, docs = corpus(store)
    by_id = {d['id']: d for d in docs}
    labels = merge_labels(store)
    test_ids = metrics['test_ids']
    texts = [by_id[key]['text'] for key in test_ids]
    y = [labels[key]['label'] for key in test_ids]
    evaluation = joblib.load(directory / 'training-history' / metrics['evaluation_model'])
    predictions = evaluation.predict(texts)
    accuracy = float(accuracy_score(y, predictions))
    macro_f1 = float(f1_score(y, predictions, labels=LABELS, average='macro', zero_division=0))
    recalls = recall_score(y, predictions, labels=LABELS, average=None, zero_division=0)
    matrix = confusion_matrix(y, predictions, labels=LABELS).tolist()
    assert np.isclose(accuracy, metrics['classification_report']['accuracy'])
    assert np.isclose(macro_f1, metrics['classification_report']['macro avg']['f1-score'])
    assert matrix == metrics['confusion_matrix']
    production = joblib.load(directory / 'sentiment-svm.joblib')
    assert len(production.predict(texts[:3])) == 3
    fixed_encoder = encoder(topic['embedding_model'])
    restored = BERTopic.load(str(directory / 'bertopic-model.joblib'), embedding_model=fixed_encoder)
    index = json.loads((directory / 'embedding-index.json').read_text(encoding='utf-8'))
    vectors = np.load(directory / 'topic-embeddings.npy')
    topic_ids, _ = restored.transform(index['texts'][:3], embeddings=vectors[:3])
    assert list(map(int, topic_ids)) == topic['reload_sample_predictions']
    counts = Counter(json.loads((directory / 'topic-assignments.json').read_text(encoding='utf-8')).values())
    assert counts[-1] == topic['noise_count']
    summary = store.summary()
    result = {
        'verified_at': now(),
        'collection': {key: summary[key] for key in ['status', 'notes', 'comments', 'notes_complete', 'notes_incomplete']},
        'collection_scope': 'first two main comment pages and inline replies; earlier data retained',
        'sentiment': {key: metrics[key] for key in ['generated_at', 'features', 'train_count', 'test_count',
            'labeled_total', 'reserved_unscored_count', 'label_sources', 'test_label_sources', 'best_params',
            'cv_macro_f1', 'class_weight', 'encoder_finetuned', 'independent_human_ground_truth']},
        'topic': {key: topic[key] for key in ['generated_at', 'algorithm', 'embedding_model', 'input_texts',
            'fit_sample_size', 'topic_count', 'noise_count', 'versions']},
        'topic_sizes': {str(k): v for k, v in sorted(counts.items())},
        'evaluation': {'accuracy': accuracy, 'macro_f1': macro_f1,
            'per_class_recall': dict(zip(LABELS, map(float, recalls))),
            'confusion_matrix': matrix, 'label_order': LABELS, 'reproduced': True,
            'svm_production_reload': True, 'bertopic_reload': True},
    }
    print('\n=== REAL SAVED MODEL VERIFICATION ===', flush=True)
    print(f"BERTopic: {topic['input_texts']} input -> {topic['fit_sample_size']} valid texts", flush=True)
    print(f"Topics={topic['topic_count']}  Noise={topic['noise_count']}  Reload=PASS", flush=True)
    print(f"SVM: train={metrics['train_count']}  fixed_test={len(test_ids)}  labels={metrics['labeled_total']}", flush=True)
    print(f"Accuracy={accuracy:.4%}  Macro-F1={macro_f1:.4f}  Negative recall={recalls[0]:.4f}", flush=True)
    print('Confusion matrix (true rows / predicted columns: neg, neu, pos):', flush=True)
    for row in matrix:
        print('  ' + '  '.join(f'{value:3d}' for value in row), flush=True)
    print('Fixed holdout reproduced: PASS | Model reload: PASS', flush=True)
    print('Test labels are AI-assisted; independent human evaluation is pending.', flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if len(args.job) != 32 or any(c not in '0123456789abcdef' for c in args.job):
        parser.error('Expected an existing 32-character report id')
    evidence = verify(Path(__file__).resolve().parents[1] / 'output/weekly' / args.job)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
