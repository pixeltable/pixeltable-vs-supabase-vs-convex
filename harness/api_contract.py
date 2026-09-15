"""The contract every implementation serves.

Five operations over one video pipeline. The response envelope is `{"rows": [...]}`
because that is what a generic router emits when it returns rows of a query; see
docs/METHODOLOGY.md, which states plainly that this choice suits Pixeltable's
serving layer and costs the other two nothing, since they build their JSON by hand
either way.

Paths differ per platform (Supabase serves Edge Functions under /functions/v1),
so the harness holds a per-implementation path map rather than pretending the URLs
are identical.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VideoIngestRequest(BaseModel):
    video: str = Field(..., description='URL or local path to a video file')
    title: str = Field(..., description='Human-readable title')


class IngestAck(BaseModel):
    """What POST /videos returns. Deliberately not a VideoRow.

    Ingest is asynchronous on Pixeltable, which returns a job to poll and frees the
    worker immediately, and synchronous on Supabase and Convex, which block for the
    length of the pipeline and then report `ready`. Neither can honestly return
    `scene_count` in the same breath as accepting the video, so the contract asks only
    that the response identifies the work. What matters is the effect, and the suite
    asserts that instead: after ingest, the video is listed and searchable.
    """

    id: str
    job_url: str | None = Field(None, description='Pixeltable: poll until status is done')
    video_title: str | None = None
    status: Literal['processing', 'ready', 'error'] | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., description='Natural-language query')
    limit: int = Field(10, ge=1, le=100)


class AgentRequest(BaseModel):
    question: str = Field(..., description='Question to answer from the videos')


class VideoRow(BaseModel):
    video_title: str
    duration_sec: float
    scene_count: int
    status: Literal['processing', 'ready', 'error'] | None = None


class FrameRow(BaseModel):
    frame_url: str = Field(..., description='Servable URL for the extracted frame')
    frame_idx: int
    video_title: str
    similarity: float = Field(..., ge=0, le=1)


class TranscriptRow(BaseModel):
    transcript: str
    video_title: str
    start_sec: float = Field(..., description='Offset of this chunk within the video')
    similarity: float = Field(..., ge=0, le=1)


class EvidenceRow(BaseModel):
    """What the agent kept from a frame. No image: the prompt never needed one."""

    video_title: str
    frame_idx: int
    similarity: float = Field(..., ge=0, le=1)


class AgentRow(BaseModel):
    answer: str = Field(..., min_length=1)
    visual: list[EvidenceRow] = Field(default_factory=list)
    spoken: list[TranscriptRow] = Field(default_factory=list)


class Rows(BaseModel):
    """Every endpoint returns this envelope."""

    rows: list[dict]


# POST /videos            VideoIngestRequest -> Rows[VideoRow]
# GET  /videos                              -> Rows[VideoRow]
# POST /search/frames     SearchRequest      -> Rows[FrameRow]
# POST /search/transcripts SearchRequest     -> Rows[TranscriptRow]
# POST /agent/query       AgentRequest       -> Rows[AgentRow]
