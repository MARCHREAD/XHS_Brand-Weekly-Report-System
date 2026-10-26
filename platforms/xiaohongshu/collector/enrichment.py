from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from .config import Settings
from .errors import EnrichmentError


class NoteEnrichment(BaseModel):
    summary: str = Field(description="A concise Chinese summary of the note")
    topics: list[str] = Field(description="Normalized topics discussed by the note")
    keywords: list[str] = Field(description="Useful Chinese search keywords")
    content_type: str = Field(description="One concise content category")
    sentiment: str = Field(description="One of positive, neutral, mixed, or negative")


class OpenAIEnricher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enrich(self, note: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.openai_configured:
            raise EnrichmentError("OPENAI_API_KEY is required when use_gpt=true")
        from openai import OpenAI

        source_tags = [tag.get("name", "") for tag in note.get("tags", []) if isinstance(tag, dict)]
        input_text = {
            "title": note.get("title", ""),
            "description": note.get("desc", ""),
            "platform_tags": source_tags,
        }
        try:
            response = OpenAI(api_key=os.environ["OPENAI_API_KEY"]).responses.parse(
                model=self.settings.openai_model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Normalize public Xiaohongshu note metadata. Use only the supplied text. "
                            "Return concise Chinese fields; use neutral when sentiment is unclear."
                        ),
                    },
                    {"role": "user", "content": str(input_text)},
                ],
                text_format=NoteEnrichment,
            )
        except Exception as exc:
            raise EnrichmentError(f"OpenAI enrichment failed: {exc}") from exc
        parsed = response.output_parsed
        if parsed is None:
            raise EnrichmentError("OpenAI returned no structured enrichment")
        return parsed.model_dump()

