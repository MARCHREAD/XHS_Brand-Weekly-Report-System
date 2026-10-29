"""Fixed pretrained features, serializable without storing encoder runtime locks."""
from functools import lru_cache
from pathlib import Path

from sklearn.base import BaseEstimator, TransformerMixin

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=2)
def encoder(model_name):
    from sentence_transformers import SentenceTransformer
    root = Path.home() / ".cache/huggingface/hub" / ("models--" + model_name.replace("/", "--")) / "snapshots"
    local = sorted(root.glob("*")) if root.exists() else []
    return SentenceTransformer(str(local[-1]) if local else model_name, device="cpu")


_vectors = {}


class FixedMiniLM(BaseEstimator, TransformerMixin):
    def __init__(self, model_name=MODEL):
        self.model_name = model_name

    def fit(self, texts, y=None):
        return self

    def transform(self, texts):
        import numpy as np
        texts = list(texts)
        missing = list(dict.fromkeys(str(t) for t in texts if (self.model_name, str(t)) not in _vectors))
        if missing:
            values = encoder(self.model_name).encode(missing, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
            _vectors.update({(self.model_name, t): v for t, v in zip(missing, values)})
        return np.array([_vectors[(self.model_name, str(t))] for t in texts], dtype=np.float32)
