import io
import uuid
import modal
from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

app = modal.App("pxt-benchmark")
web_app = FastAPI(title="Modal Benchmark Endpoint")


class DocInput(BaseModel):
    title: str
    body: str


def frame_at(container, seconds: float = 0.5):
    """The frame Pixeltable's extract_frame(timestamp=seconds) returns, found the same way: the first at or after
    `seconds` from the stream's start, or here the first frame of a shorter clip. Given a stream, seek() counts in
    that stream's time base, not in microseconds."""
    stream = container.streams.video[0]
    start = stream.start_time or 0
    container.seek(int(seconds / stream.time_base) + start, backward=True, stream=stream)
    for frame in container.decode(stream):
        if frame.pts is not None and (frame.pts - start) * stream.time_base >= seconds:
            return frame.to_image()
    container.seek(0)
    return next((frame.to_image() for frame in container.decode(stream)), None)


@web_app.get("/")
def health():
    return {"status": "ok", "platform": "modal"}


@web_app.get("/read")
def read_docs():
    return {
        "status": "ok",
        "platform": "modal",
        "count": 10,
        "docs": [{"id": f"modal-doc-{i}", "title": f"title-{i}"} for i in range(10)],
    }


@web_app.post("/docs")
def insert_doc(doc: DocInput):
    doc_id = str(uuid.uuid4())
    title_upper = doc.title.upper()
    summary = doc.title[:12] + "..." if len(doc.title) > 12 else doc.title
    return {
        "id": doc_id,
        "title_upper": title_upper,
        "summary": summary,
        "platform": "modal",
    }


# Same handler as the Railway and Render apps (cloud-comparison/app/main.py): decode in memory, store nothing.
@web_app.post("/clip")
async def insert_clip(clip: UploadFile = File(...), title: str = Form(...)):
    import av

    clip_id = str(uuid.uuid4())
    content = await clip.read()
    container = av.open(io.BytesIO(content))
    duration = float(container.duration / av.time_base) if container.duration else 0.0
    frame_image = frame_at(container)
    w, h = 320, 180
    if frame_image:
        frame_image.resize((w, h))
    return {"id": clip_id, "title": title, "duration": round(duration, 2), "thumb": [w, h]}


image = modal.Image.debian_slim().pip_install("fastapi[standard]", "av==13.1.0", "Pillow==10.4.0", "python-multipart==0.0.12")


@app.function(image=image)
def background_task(title: str, body: str) -> dict:
    return {"status": "done", "title_upper": title.upper()}


@web_app.post("/docs/async")
def insert_doc_async(doc: DocInput):
    call = background_task.spawn(doc.title, doc.body)
    return {
        "id": call.object_id,
        "status": "queued",
        "platform": "modal",
    }


@app.function(image=image)
@modal.asgi_app()
def fastapi_app():
    return web_app

