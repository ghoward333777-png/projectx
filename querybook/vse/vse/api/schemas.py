from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LipSyncRequest(BaseModel):
    text: str
    audio_url: Optional[str] = None            # a local path or file:// URL (remote fetching is left to the deployment)
    audio_b64: Optional[str] = None
    language: str = "en"
    mode: str = "high_fidelity"
    options: dict = Field(default_factory=dict)


class LipReadRequest(BaseModel):
    video_url: Optional[str] = None
    frames: Optional[list[Any]] = None          # QueryBook frames JSON
    language: str = "en"
    words: list[str] = Field(default_factory=list)
    script: str = ""
    options: dict = Field(default_factory=dict)


class JobResponse(BaseModel):
    job_id: str
    status: str
    estimated_time_seconds: Optional[float] = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
