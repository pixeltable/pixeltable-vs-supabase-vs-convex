"""Shared compute service for media processing.

Supabase Edge Functions and Convex actions do not run ffmpeg, Whisper, CLIP or a local
chat model here (see each app's README for why), so both call these seven endpoints, and
both implementations are charged for every line of this file. Pixeltable runs the same
work inside its own process, in computed columns.

That this service has to exist at all is the comparison point.
"""

from __future__ import annotations

import base64
import hmac
import io
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from PIL import Image
from pydantic import BaseModel, Field

# Unset on a laptop, where only the two local consumers can reach the service. Set on any
# deployment with a public address (cloud/deploy_compute.sh keeps it in Secrets Manager):
# every endpoint then requires it, and both consumers send it from their own secrets.
TOKEN = os.environ.get('COMPUTE_SERVICE_TOKEN', '')


def require_token(request: Request) -> None:
    if TOKEN and not hmac.compare_digest(request.headers.get('authorization', ''), f'Bearer {TOKEN}'):
        raise HTTPException(status_code=401, detail='missing or wrong bearer token')


app = FastAPI(
    title='Video Compute Service',
    description='External media processing that Supabase/Convex need but Pixeltable does not.',
    dependencies=[Depends(require_token)],
)

# ---------------------------------------------------------------------------
# Lazy model singletons
# ---------------------------------------------------------------------------

# One process, four models, and a lock. Supabase and Convex fan out one webhook or
# action per row, so without this they contend on a single CLIP and a single Whisper.
#
# The endpoints are plain `def`, not `async def`: every one of them blocks on ffmpeg or a
# model, and FastAPI runs a `def` endpoint in its threadpool but an `async def` one on the
# event loop, where a blocking call stalls every other request. Concurrent requests then
# overlap on ffmpeg and on the torch models, whose forward passes are safe to share.
# Whisper and llama.cpp are not: Whisper installs kv-cache hooks on the shared model for
# the length of a decode, and a llama.cpp context holds one sequence at a time. Each gets
# its own lock around inference.
_lock = threading.Lock()
_whisper_lock = threading.Lock()
_chat_lock = threading.Lock()
_clip_model = None
_clip_processor = None
_whisper_model = None
_text_model = None
_chat_model = None


def _get_clip():
    global _clip_model, _clip_processor
    with _lock:
        if _clip_model is None:
            from transformers import CLIPModel, CLIPProcessor

            model_id = 'openai/clip-vit-base-patch32'
            _clip_processor = CLIPProcessor.from_pretrained(model_id)
            _clip_model = CLIPModel.from_pretrained(model_id)
    return _clip_model, _clip_processor


def _get_whisper():
    global _whisper_model
    with _lock:
        if _whisper_model is None:
            import whisper  # type: ignore[import-untyped]

            _whisper_model = whisper.load_model('base.en')
    return _whisper_model


CHAT_REPO_ID = 'Qwen/Qwen2.5-1.5B-Instruct-GGUF'
CHAT_FILENAME = '*q4_k_m.gguf'


def _get_chat_model():
    global _chat_model
    with _lock:
        if _chat_model is None:
            from llama_cpp import Llama, llama_supports_gpu_offload

            # Pixeltable's llama_cpp UDF offloads every layer when this build supports it and
            # none otherwise; the same rule here, so both run the agent on the same device.
            # llama-cpp-python's own default is 0 layers, CPU even on a Mac with Metal.
            _chat_model = Llama.from_pretrained(
                repo_id=CHAT_REPO_ID,
                filename=CHAT_FILENAME,
                n_ctx=4096,
                n_gpu_layers=-1 if llama_supports_gpu_offload() else 0,
                verbose=False,
            )
    return _chat_model


def _get_text_model():
    global _text_model
    with _lock:
        if _text_model is None:
            from sentence_transformers import SentenceTransformer

            _text_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return _text_model


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ExtractFramesRequest(BaseModel):
    video_url: str = Field(..., description='URL or local path to video')
    fps: float = Field(1.0, description='Frames per second to extract')


class ExtractFramesResponse(BaseModel):
    frames: list[str] = Field(..., description='Base64-encoded JPEG frames')


class ExtractAudioRequest(BaseModel):
    video_url: str = Field(..., description='URL or local path to video')
    format: str = Field('mp3', description='Output audio format')


class ExtractAudioResponse(BaseModel):
    audio_b64: str = Field(..., description='Base64-encoded audio')
    duration_sec: float


class TranscribeRequest(BaseModel):
    audio_b64: str = Field(..., description='Base64-encoded audio (MP3/WAV)')
    language: str = Field('en', description='Language code')
    start_sec: float | None = Field(None, description='Transcribe only from this offset')
    end_sec: float | None = Field(None, description='Transcribe only up to this offset')


class TranscribeResponse(BaseModel):
    text: str


class EmbedClipRequest(BaseModel):
    images_b64: list[str] | None = Field(None, description='Base64-encoded images')
    texts: list[str] | None = Field(None, description='Text strings to embed')


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


class EmbedTextRequest(BaseModel):
    texts: list[str] = Field(..., description='Text strings to embed semantically')


class ChatRequest(BaseModel):
    messages: list[dict] = Field(..., description='OpenAI-shaped chat messages')
    max_tokens: int = Field(256)
    temperature: float = Field(0.2)


class ChatResponse(BaseModel):
    content: str


class DetectScenesRequest(BaseModel):
    video_url: str = Field(..., description='URL or local path to video')
    threshold: float = Field(8.0, description='Content-change threshold, percent')


class SceneBoundary(BaseModel):
    start_sec: float
    end_sec: float


class DetectScenesResponse(BaseModel):
    scenes: list[SceneBoundary]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post('/extract-frames', response_model=ExtractFramesResponse)
def extract_frames(req: ExtractFramesRequest):
    """Extract frames at given FPS using ffmpeg."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = str(Path(tmpdir) / 'frame_%04d.jpg')
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            req.video_url,
            '-vf',
            f'fps={req.fps}',
            '-q:v',
            '2',
            pattern,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f'ffmpeg failed: {result.stderr[-300:]}')

        frames_b64 = []
        for frame_path in sorted(Path(tmpdir).glob('frame_*.jpg')):
            frames_b64.append(base64.b64encode(frame_path.read_bytes()).decode())

    return ExtractFramesResponse(frames=frames_b64)


@app.post('/extract-audio', response_model=ExtractAudioResponse)
def extract_audio(req: ExtractAudioRequest):
    """Extract audio track from video using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=f'.{req.format}', delete=False) as f:
        out_path = f.name

    try:
        # Encoded once, at the encoder's defaults, and never again: /transcribe cuts this
        # track without a second lossy encode. Pixeltable does the same (one extract_audio
        # encode, then audio_splitter remuxes packets), so Whisper hears equivalent audio.
        # Forcing 16 kHz here and re-encoding every chunk once squeezed speech through two
        # lossy passes at 24 kbps, and on a CI runner Whisper heard 'quicksword' where
        # Pixeltable heard 'quicksort'.
        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            req.video_url,
            '-vn',
            '-acodec',
            'libmp3lame' if req.format == 'mp3' else 'pcm_s16le',
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f'ffmpeg failed: {result.stderr[-300:]}')

        audio_bytes = Path(out_path).read_bytes()
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', out_path],
            capture_output=True,
            text=True,
        )
        duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0.0
    finally:
        Path(out_path).unlink(missing_ok=True)

    return ExtractAudioResponse(audio_b64=base64.b64encode(audio_bytes).decode(), duration_sec=duration)


@app.post('/transcribe', response_model=TranscribeResponse)
def transcribe(req: TranscribeRequest):
    """Transcribe audio using Whisper."""
    model = _get_whisper()
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
        f.write(base64.b64decode(req.audio_b64))
        f.flush()
        tmp_path = f.name

    clip_path = None
    try:
        if req.start_sec is not None or req.end_sec is not None:
            # Without this the caller transcribes the whole track once per chunk and writes
            # the same text to every row. Chunking has to be done somewhere; here it is ffmpeg,
            # decoding the track and cutting PCM at the exact time, so the one lossy step stays
            # the encode in /extract-audio. A stream copy on MP3 packets starts each chunk on a
            # frame whose bit reservoir is gone, and Whisper heard 'Alisha' for the 'deletion'
            # at a boundary where Pixeltable's chunk says 'deletion'.
            clip_path = f'{tmp_path}.clip.wav'
            cmd = ['ffmpeg', '-y', '-i', tmp_path, '-ss', str(req.start_sec or 0.0)]
            if req.end_sec is not None:
                cmd += ['-to', str(req.end_sec)]
            cmd += ['-c:a', 'pcm_s16le', clip_path]
            clipped = subprocess.run(cmd, capture_output=True, text=True)
            if clipped.returncode != 0:
                raise HTTPException(status_code=500, detail=f'ffmpeg failed: {clipped.stderr[-300:]}')
        with _whisper_lock:
            result = model.transcribe(clip_path or tmp_path, language=req.language)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if clip_path is not None:
            Path(clip_path).unlink(missing_ok=True)

    return TranscribeResponse(text=result['text'])


@app.post('/embed-clip', response_model=EmbedResponse)
def embed_clip(req: EmbedClipRequest):
    """Embed images and/or text using CLIP."""
    import torch

    model, processor = _get_clip()
    embeddings: list[list[float]] = []

    if req.images_b64:
        images = [Image.open(io.BytesIO(base64.b64decode(b))) for b in req.images_b64]
        inputs = processor(images=images, return_tensors='pt', padding=True)
        with torch.no_grad():
            feats = model.get_image_features(**inputs)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        embeddings.extend(feats.cpu().numpy().tolist())

    if req.texts:
        inputs = processor(text=req.texts, return_tensors='pt', padding=True, truncation=True)
        with torch.no_grad():
            feats = model.get_text_features(**inputs)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        embeddings.extend(feats.cpu().numpy().tolist())

    return EmbedResponse(embeddings=embeddings)


@app.post('/embed-text', response_model=EmbedResponse)
def embed_text(req: EmbedTextRequest):
    """Embed text semantically, the counterpart to the CLIP index on frames."""
    model = _get_text_model()
    vectors = model.encode(req.texts, normalize_embeddings=True).tolist()
    return EmbedResponse(embeddings=vectors)


@app.post('/chat', response_model=ChatResponse)
def chat(req: ChatRequest):
    """Answer a chat prompt with a local model, which neither consumer hosts in its own runtime."""
    model = _get_chat_model()
    with _chat_lock:
        result = model.create_chat_completion(
            messages=req.messages, max_tokens=req.max_tokens, temperature=req.temperature
        )
    return ChatResponse(content=result['choices'][0]['message']['content'] or '')


@app.post('/detect-scenes', response_model=DetectScenesResponse)
def detect_scenes(req: DetectScenesRequest):
    """Detect scene boundaries using ffmpeg scene-change filter."""
    cmd = [
        'ffprobe',
        '-v',
        'quiet',
        '-show_entries',
        'frame=pts_time',
        '-of',
        'csv=p=0',
        '-f',
        'lavfi',
        f"movie='{req.video_url.replace(chr(58), chr(92) + chr(58))}',select='gt(scene,{req.threshold / 100})'",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    probe_dur = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', req.video_url],
        capture_output=True,
        text=True,
    )
    total_dur = float(probe_dur.stdout.strip()) if probe_dur.stdout.strip() else 0.0

    boundaries = [0.0]
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            try:
                boundaries.append(float(line.strip()))
            except ValueError:
                continue

    scenes = []
    for i, start in enumerate(boundaries):
        end_time = boundaries[i + 1] if i + 1 < len(boundaries) else total_dur
        scenes.append(SceneBoundary(start_sec=start, end_sec=end_time))

    return DetectScenesResponse(scenes=scenes)


# Every launch, here and in the READMEs, CI and harness/remeasure.sh, sets keep-alive above
# uvicorn's 5s default. A pooling client keeps idle connections longer than that (hyper,
# under Deno's fetch, defaults to 90s), so at 5s the server can close an idle one just as
# the client sends on it. Under load an agent query's calls land about that far apart,
# and Supabase's failed with "connection closed before message completed". The server
# has to outlive the client's idle timeout, not the reverse.
KEEP_ALIVE_SEC = 120

if __name__ == '__main__':
    import uvicorn

    uvicorn.run('app:app', host='0.0.0.0', port=9000, reload=True, timeout_keep_alive=KEEP_ALIVE_SEC)
