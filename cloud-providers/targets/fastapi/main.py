import uuid
import time
import io
from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
import av
from PIL import Image

app = FastAPI(title="Cloud Comparison Benchmark Service")

class DocInput(BaseModel):
    title: str
    body: str

@app.get("/")
def health():
    return {"status": "ok", "service": "comparison-benchmark"}

@app.post("/docs")
def insert_doc(doc: DocInput):
    doc_id = str(uuid.uuid4())
    title_upper = doc.title.upper()
    summary = doc.title[:12] + "..." if len(doc.title) > 12 else doc.title
    return {
        "id": doc_id,
        "title_upper": title_upper,
        "summary": summary
    }

@app.post("/clip")
async def insert_clip(clip: UploadFile = File(...), title: str = Form(...)):
    clip_id = str(uuid.uuid4())
    content = await clip.read()
    
    # Process video using PyAV
    container = av.open(io.BytesIO(content))
    duration = float(container.duration / av.time_base) if container.duration else 0.0
    
    # Extract frame at ~0.5s or first frame
    frame_image = None
    stream = container.streams.video[0]
    container.seek(500000, stream=stream)  # Seek 0.5s in microseconds
    for frame in container.decode(video=0):
        frame_image = frame.to_image()
        break
    
    if frame_image is None:
        container.seek(0)
        for frame in container.decode(video=0):
            frame_image = frame.to_image()
            break
            
    # Generate thumbnail
    w, h = 320, 180
    if frame_image:
        thumb = frame_image.resize((w, h))
    
    return {
        "id": clip_id,
        "title": title,
        "duration": round(duration, 2),
        "thumb": [w, h]
    }


# /clip/persist does what Pixeltable's media route does, so the two can be compared: decode a frame, make a
# thumbnail, upload the video and the thumbnail to object storage, and insert one row into Postgres.
# Configured by DATABASE_URL, STORAGE_URL (Supabase Storage /storage/v1) and STORAGE_KEY.
import os

import httpx
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None
_storage: httpx.AsyncClient | None = None
BUCKET = os.environ.get("STORAGE_BUCKET", "shootout-media")


@app.on_event("startup")
async def _open_persistence() -> None:
    global _pool, _storage
    if not os.environ.get("DATABASE_URL"):
        return
    _pool = AsyncConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=10, open=False)
    await _pool.open()
    async with _pool.connection() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS videos (id text PRIMARY KEY, title text, duration double precision,"
            " video_key text, thumb_key text, created_at timestamptz DEFAULT now())"
        )
    _storage = httpx.AsyncClient(
        base_url=os.environ["STORAGE_URL"],
        headers={"Authorization": f"Bearer {os.environ['STORAGE_KEY']}", "apikey": os.environ["STORAGE_KEY"]},
        timeout=60,
    )


@app.post("/clip/persist")
async def persist_clip(clip: UploadFile = File(...), title: str = Form(...)):
    if _pool is None or _storage is None:
        return {"error": "persistence not configured"}
    clip_id = str(uuid.uuid4())
    content = await clip.read()
    container = av.open(io.BytesIO(content))
    duration = float(container.duration / av.time_base) if container.duration else 0.0
    stream = container.streams.video[0]
    container.seek(500000, stream=stream)
    frame_image = next((frame.to_image() for frame in container.decode(video=0)), None)
    if frame_image is None:  # the clip is shorter than the seek; take the first frame, as /clip does
        container.seek(0)
        frame_image = next((frame.to_image() for frame in container.decode(video=0)), None)
    thumb = io.BytesIO()
    frame_image.resize((256, 144)).save(thumb, format="JPEG")
    video_key, thumb_key = f"videos/{clip_id}.mpg", f"thumbs/{clip_id}.jpg"
    for key, body, ctype in ((video_key, content, "video/mpeg"), (thumb_key, thumb.getvalue(), "image/jpeg")):
        r = await _storage.post(f"/object/{BUCKET}/{key}", content=body, headers={"Content-Type": ctype})
        r.raise_for_status()
    async with _pool.connection() as conn:
        await conn.execute(
            "INSERT INTO videos (id, title, duration, video_key, thumb_key) VALUES (%s, %s, %s, %s, %s)",
            (clip_id, title, round(duration, 2), video_key, thumb_key),
        )
    return {"id": clip_id, "title": title, "duration": round(duration, 2), "thumb": [256, 144]}
