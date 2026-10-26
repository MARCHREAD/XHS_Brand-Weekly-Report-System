from __future__ import annotations

from datetime import date
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from .manager import Manager, default_config
from .analysis import LABELS, build_report, corpus


class ReportRequest(BaseModel):
    primary: str = Field(default="libtv", min_length=1, max_length=80)
    competitors: list[str] = Field(default_factory=lambda: ["即梦", "updream"], min_length=1, max_length=5)
    search_pages: int = Field(default=100, ge=100, le=500)
    sort: Literal["general", "popularity_descending", "time_descending"] = "time_descending"
    week_start: date = date(2026, 10, 19)
    week_end: date = date(2026, 10, 25)

    @model_validator(mode="after")
    def valid(self):
        names = [self.primary, *self.competitors]
        if any(not v.strip() or len(v) > 80 for v in names) or len({v.casefold().strip() for v in names}) != len(names):
            raise ValueError("Brands must be nonempty and distinct")
        if (self.week_end - self.week_start).days != 6:
            raise ValueError("Choose one seven-day reporting window")
        return self


class LabelRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    label: Literal["positive", "neutral", "negative"]


def router(manager: Manager, get_service, require_local):
    r = APIRouter(prefix="/v1/xhs/weekly", tags=["Brand weekly reports"])

    def store(job_id):
        try:
            return manager.store(job_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Report not found") from exc

    @r.get("/config")
    def config():
        return default_config()

    @r.get("/jobs")
    def jobs():
        return manager.latest()

    @r.post("/jobs", status_code=202)
    async def create(body: ReportRequest, request: Request, service=Depends(get_service)):
        require_local(request)
        config = {**default_config(), **body.model_dump(mode="json")}
        try:
            return manager.create(config)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.get("/jobs/{job_id}")
    def status(job_id: str):
        return store(job_id).summary()

    @r.post("/jobs/{job_id}/pause")
    def pause(job_id: str, request: Request):
        require_local(request)
        s = store(job_id)
        if s.meta().get("status") == "running":
            s.meta(status="pause_requested")
        return s.summary()

    @r.post("/jobs/{job_id}/resume", status_code=202)
    async def resume(job_id: str, request: Request, service=Depends(get_service)):
        require_local(request)
        store(job_id)
        try:
            return manager.launch(job_id, "collect")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.get("/jobs/{job_id}/report")
    def report(job_id: str):
        s = store(job_id)
        path = s.directory / "report.json"
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            value["collection"] = s.summary()
            value["stale"] = s.meta().get("updated_at", "") > value["generated_at"]
            return value
        notes, docs = corpus(s)
        return build_report(s, notes, docs)

    @r.get("/jobs/{job_id}/evidence")
    def evidence(job_id: str, offset: int = 0):
        if offset < 0:
            raise HTTPException(422, "Offset must be nonnegative")
        s = store(job_id)
        _, docs = corpus(s)
        labels = s.get("labels", "sentiment", {})
        comments = [d for d in docs if d["kind"] == "comment"]
        return {"total": len(comments), "items": [{**d, "annotation": labels.get(d["id"])} for d in comments[offset:offset + 30]]}

    @r.post("/jobs/{job_id}/labels")
    def label(job_id: str, body: LabelRequest, request: Request):
        require_local(request)
        s = store(job_id)
        _, docs = corpus(s)
        if not any(d["id"] == body.document_id and d["kind"] == "comment" for d in docs):
            raise HTTPException(404, "Comment not found in this report")
        labels = s.get("labels", "sentiment", {})
        labels[body.document_id] = {"label": body.label, "source": "human_review"}
        s.put("labels", "sentiment", labels)
        return {"labeled": len(labels)}

    @r.post("/jobs/{job_id}/{action}", status_code=202)
    def analysis(job_id: str, action: Literal["analyze", "train"], request: Request):
        require_local(request)
        s = store(job_id)
        if s.meta().get("analysis_status") == "running":
            raise HTTPException(409, "Analysis is already running")
        return manager.launch(job_id, action)

    return r
