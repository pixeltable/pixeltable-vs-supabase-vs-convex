from fastapi import FastAPI, UploadFile, File, Form, Request
from pydantic import BaseModel
import uuid
import io

app = FastAPI(title="Vercel Cloud Comparison API")

class DocInput(BaseModel):
    title: str
    body: str

@app.api_route("/docs", methods=["POST"])
@app.api_route("/api/docs", methods=["POST"])
def insert_doc(doc: DocInput):
    doc_id = str(uuid.uuid4())
    title_upper = doc.title.upper()
    summary = doc.title[:12] + "..." if len(doc.title) > 12 else doc.title
    return {
        "id": doc_id,
        "title_upper": title_upper,
        "summary": summary
    }

@app.api_route("/clip", methods=["POST"])
@app.api_route("/api/clip", methods=["POST"])
async def insert_clip(clip: UploadFile = File(...), title: str = Form(...)):
    try:
        import av
        content = await clip.read()
        container = av.open(io.BytesIO(content))
        duration = float(container.duration / av.time_base) if container.duration else 0.0
        frame_image = None
        for frame in container.decode(video=0):
            frame_image = frame.to_image()
            break
        w, h = 320, 180
        thumb = frame_image.resize((w, h)) if frame_image else None
        return {"id": str(uuid.uuid4()), "title": title, "duration": round(duration, 2), "thumb": [w, h]}
    except Exception as e:
        return {"id": str(uuid.uuid4()), "title": title, "error": f"{type(e).__name__}: {str(e)}"}

@app.api_route("/{path_name:path}", methods=["GET", "POST"])
def catch_all(request: Request, path_name: str = ""):
    return {
        "status": "ok",
        "platform": "vercel",
        "received_path": path_name,
        "url_path": str(request.url.path)
    }
