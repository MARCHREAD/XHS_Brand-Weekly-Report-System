from pathlib import Path

import pytest

from collector.config import Settings
from collector.enrichment import OpenAIEnricher
from collector.errors import EnrichmentError


def test_gpt_enrichment_requires_explicit_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    enricher = OpenAIEnricher(Settings(cookie_file=tmp_path / "none"))
    with pytest.raises(EnrichmentError, match="OPENAI_API_KEY"):
        enricher.enrich({"title": "fixture", "desc": "text", "tags": []})

