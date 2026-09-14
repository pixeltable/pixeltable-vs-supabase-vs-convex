"""Video intelligence, end to end: schema, pipeline, agent, and HTTP in one file.

Insert a video. Pixeltable extracts frames, extracts audio, splits it into chunks,
transcribes speech, embeds frames visually and transcripts semantically, and detects
scene boundaries. Nothing below schedules that work, polls for it, or records its
status. The columns declare what each row contains, and Pixeltable computes it.

    pxt init
    pxt schema update app.py media
    pxt service update app.py media

Every model runs locally, so this needs no API key. Each model line carries the
hosted alternative beside it: swapping providers changes one expression, not a
pipeline.
"""

import uuid

import pixeltable as pxt
import pixeltable.functions as pxtf
from fastapi import Body
from pixeltable.functions.audio import audio_splitter
from pixeltable.functions.huggingface import clip, sentence_transformer
from pixeltable.functions.llama_cpp import create_chat_completion
from pixeltable.functions.video import extract_audio, frame_iterator
from pixeltable.functions.whisper import transcribe
from pixeltable.serving import FastAPIRouter

TableModel = pxt.model_base()

CATALOG = 'media'  # the catalog directory passed to `pxt schema update` / `pxt service update`

VISUAL = clip.using(model_id='openai/clip-vit-base-patch32')
SEMANTIC = sentence_transformer.using(model_id='sentence-transformers/all-MiniLM-L6-v2')
# hosted: openai.embeddings.using(model='text-embedding-3-small')

FRAME_FPS = 1.0
CHUNK_SECONDS = 10.0


# ---------------------------------------------------------------- the pipeline


@pxt.udf
def count_items(items: list) -> int:
    return len(items)


class Videos(TableModel, name='videos'):
    video: pxt.Video
    title: pxt.String
    audio = extract_audio(video, format='mp3')
    duration_sec = pxtf.video.get_duration(video)
    scenes = video.scene_detect_content(threshold=8.0)
    scene_count = count_items(scenes)


class Frames(TableModel, name='frames', base=Videos, iterator=frame_iterator(Videos.video, fps=FRAME_FPS)):
    # `frame` is computed on demand and never written to disk, which is what keeps a
    # 1 FPS view of an hour of video cheap. `still` is the stored copy the API serves.
    still = pxtf.image.resize(frame, (320, 180))  # type: ignore[name-defined]
    __indexes__ = [pxt.EmbeddingIndex(frame, embedding=VISUAL)]  # type: ignore[name-defined]


class Chunks(TableModel, name='chunks', base=Videos, iterator=audio_splitter(Videos.audio, duration=CHUNK_SECONDS)):
    transcript = transcribe(audio_segment, model='base.en').text.astype(pxt.String)  # type: ignore[name-defined]
    __indexes__ = [pxt.EmbeddingIndex(transcript, embedding=SEMANTIC)]


# ------------------------------------------------------------------- retrieval


@pxt.query
def search_frames(query: str, limit: int = 10):
    """Text to frame. The CLIP index answers a string query against stored images."""
    sim = Frames.frame.similarity(string=query)
    return (
        Frames.order_by(sim, asc=False)
        .limit(limit)
        .select(frame_url=Frames.still, frame_idx=Frames.pos, video_title=Frames.title, similarity=sim)
    )


@pxt.query
def search_transcripts(query: str, limit: int = 10):
    """Text to speech. A different index on a different column, queried the same way."""
    sim = Chunks.transcript.similarity(string=query)
    return (
        Chunks.order_by(sim, asc=False)
        .limit(limit)
        .select(
            transcript=Chunks.transcript,
            video_title=Chunks.title,
            start_sec=Chunks.segment_start,
            similarity=sim,
        )
    )


@pxt.query
def frames_seen(query: str, limit: int = 4):
    """What the agent needs from a frame: which video, where, how close. No image."""
    sim = Frames.frame.similarity(string=query)
    return (
        Frames.order_by(sim, asc=False)
        .limit(limit)
        .select(video_title=Frames.title, frame_idx=Frames.pos, similarity=sim)
    )


@pxt.query
def list_videos():
    return Videos.select(
        video_title=Videos.title,
        duration_sec=Videos.duration_sec,
        scene_count=Videos.scene_count,
    ).order_by(Videos.title)


# --------------------------------------------------------------------- the agent


@pxt.udf
def build_prompt(question: str, visual: list[dict], spoken: list[dict]) -> str:
    seen = '\n'.join(f'- {r["video_title"]}, frame {r["frame_idx"]}' for r in visual) or '(nothing)'
    heard = (
        '\n'.join(f'- [{r["video_title"]} @ {r["start_sec"]:.0f}s] {r["transcript"]}' for r in spoken) or '(nothing)'
    )
    return (
        'Answer the question using only the retrieved context. Be brief.\n\n'
        f'## Seen in the videos\n{seen}\n\n## Said in the videos\n{heard}\n\n## Question\n{question}'
    )


class Conversations(TableModel, name='conversations'):
    """The agent is a table. Insert a question and the answer computes itself.

    Retrieval is a column, so each answer keeps the evidence it was built from rather
    than discarding it once the prompt is assembled.
    """

    request_id: pxt.String
    question: pxt.String
    visual = frames_seen(question, limit=4)
    spoken = search_transcripts(question, limit=4)
    answer = (
        create_chat_completion(
            messages=[{'role': 'user', 'content': build_prompt(question, visual, spoken)}],
            repo_id='Qwen/Qwen2.5-1.5B-Instruct-GGUF',
            repo_filename='*q4_k_m.gguf',
            model_kwargs={'max_tokens': 256, 'temperature': 0.2},
        )
        .choices[0]
        .message.content
    )
    # hosted, with real tool calling:
    # answer = openai.chat_completions(messages=..., model='gpt-4o-mini',
    #                                  tools=pxt.tools(search_frames, search_transcripts))


# ----------------------------------------------------------------------- the API

api = FastAPIRouter(name='api')
# `uploadfile_inputs=[Videos.video]` would make this a multipart upload instead.
api.add_insert_route(Videos, path='/videos', inputs=[Videos.video, Videos.title], background=True)
api.add_query_route(path='/videos', query=list_videos, method='get')
api.add_query_route(path='/search/frames', query=search_frames, method='post')
api.add_query_route(path='/search/transcripts', query=search_transcripts, method='post')


# The fifth endpoint is the one route this file has to write by hand. `add_insert_route`
# resolves its target model eagerly, which fails on a model whose columns call a query
# (pixeltable 0.7.7: "A query over model `Frames` cannot be serialized"). The table still
# does the work; only the plumbing is manual.
@api.post('/agent/query')
def ask(question: str = Body(..., embed=True)) -> dict:
    conversations = pxt.get_table(f'{CATALOG}.conversations')
    # `request_id` exists only so this handler can find the row it just wrote. A
    # declared insert route would return the computed outputs directly.
    request_id = str(uuid.uuid4())
    conversations.insert([{'request_id': request_id, 'question': question}])
    row = (
        conversations.where(conversations.request_id == request_id)
        .select(answer=conversations.answer, visual=conversations.visual, spoken=conversations.spoken)
        .collect()[0]
    )
    return {'rows': [row]}
