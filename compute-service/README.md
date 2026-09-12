# Compute Service

**This service exists because Supabase and Convex cannot process video natively.**

It provides ffmpeg frame extraction, audio extraction, Whisper transcription, CLIP embedding, text embedding, scene detection, and a local chat model as HTTP endpoints. Supabase Edge Functions and Convex Actions call it for every media step: Deno has no subprocess and therefore no ffmpeg, and a Convex Node action has nowhere to keep model weights.

Pixeltable does not need this service. Its seven operations are seven expressions in `pixeltable/app.py`.

Every model here runs locally, so the benchmark needs no API key on any platform.

## Run locally

```bash
pip install -e ".[dev]"
uvicorn app:app --host 0.0.0.0 --port 9000 --reload
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/extract-frames` | POST | Extract frames from video at given FPS |
| `/extract-audio` | POST | Extract audio track from video |
| `/transcribe` | POST | Transcribe audio with Whisper |
| `/embed-clip` | POST | Embed images/text with CLIP |
| `/embed-text` | POST | Embed text with sentence-transformers |
| `/chat` | POST | Answer a prompt with a local chat model |
| `/detect-scenes` | POST | Detect scene boundaries |
| `/health` | GET | Health check |
