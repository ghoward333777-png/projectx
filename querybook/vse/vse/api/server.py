"""REST API (FastAPI). Endpoints follow the specification (/vse/lip_sync, /vse/lip_read, /vse/job/{id}); the same
request bodies QueryBook's Language Builder sends are accepted under /api/vse/… so either engine can serve the page.

    uvicorn vse.api.server:app --port 8200        (set VSE_STAGE1_APPS to QueryBook's apps/ directory)"""
from __future__ import annotations

import base64
import os

from fastapi import FastAPI, HTTPException

from vse.pipeline.job_manager import JobManager
from vse.pipeline.lip_read_pipeline import LipReadConfig, LipReadPipeline
from vse.pipeline.lip_sync_pipeline import LipSyncConfig, LipSyncPipeline

from .schemas import JobResponse, JobStatusResponse, LipReadRequest, LipSyncRequest


def create_app(stage1=None, stage2_reader=None, motion_model=None):
    if stage1 is None and os.environ.get("VSE_STAGE1_APPS"):
        from vse.bridge.querybook import load_stage1
        stage1 = load_stage1(os.environ["VSE_STAGE1_APPS"])
    app = FastAPI(title="Visual Speech Engine", version="0.1.0")
    jobs = JobManager()
    sync = LipSyncPipeline(LipSyncConfig(), stage1, motion_model)
    read = LipReadPipeline(LipReadConfig(), stage1, stage2_reader)

    def _audio(req: LipSyncRequest):
        if req.audio_b64:
            return base64.b64decode(req.audio_b64)
        if req.audio_url:
            path = req.audio_url[7:] if req.audio_url.startswith("file://") else req.audio_url
            if not os.path.isfile(path):
                raise HTTPException(400, "audio_url must be a readable local file")
            return path
        raise HTTPException(400, "give audio_b64 or audio_url")

    @app.post("/vse/lip_sync", response_model=JobResponse)
    def lip_sync(req: LipSyncRequest):
        audio = _audio(req)
        return jobs.submit("lip_sync", sync.run, audio, req.text, req.options.get("word_times"))

    @app.post("/vse/lip_read", response_model=JobResponse)
    def lip_read(req: LipReadRequest):
        if req.frames is None and not req.video_url:
            raise HTTPException(400, "give frames or video_url")
        return jobs.submit("lip_read", read.run, req.frames, req.video_url, req.words, req.script)

    @app.get("/vse/job/{job_id}", response_model=JobStatusResponse)
    def job(job_id: str):
        j = jobs.status(job_id)
        if not j:
            raise HTTPException(404, "no such job")
        return JobStatusResponse(job_id=job_id, status=j["status"], result=j["result"], error=j["error"])

    # QueryBook-compatible routes
    @app.post("/api/vse/lip_read", response_model=JobResponse)
    def qb_lip_read(body: dict):
        words = body.get("words") or []
        if isinstance(words, str):
            words = [w for w in words.replace(",", " ").split() if w]
        return jobs.submit("lip_read", read.run, body.get("frames") or [], None, words, body.get("script") or "")

    @app.get("/api/vse/job")
    def qb_job(id: str):
        j = jobs.status(id)
        if not j:
            raise HTTPException(404, "no such job")
        return {k: j[k] for k in ("job_id", "kind", "status", "result", "error")}

    return app


app = create_app() if os.environ.get("VSE_STAGE1_APPS") else None
