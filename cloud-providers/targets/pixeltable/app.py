"""Pixeltable multimodal application.

Defines:
- Docs table + ingest service
- Images table + Videos table + media service
"""
import pixeltable as pxt
import pixeltable.functions as pxtf
from pixeltable.serving import FastAPIRouter

TableModel = pxt.model_base()


# a udf: a Python function the computed columns below can call
@pxt.udf
def excerpt(text: str, n: int = 12) -> str:
    return text if len(text) <= n else f'{text[:n]}...'


class Docs(TableModel, name='docs'):
    id = pxt.Column(value=pxtf.uuid.uuid7(), primary_key=True)  # generated on insert; update matches rows by it
    title: pxt.String
    body: pxt.String | None
    title_upper = pxtf.string.upper(title)  # a computed column: an assignment, not an annotation
    summary = excerpt(title)  # a computed column over a udf this file defines


class Images(TableModel, name='images'):
    id = pxt.Column(value=pxtf.uuid.uuid7(), primary_key=True)
    label: pxt.String
    photo: pxt.Image
    thumb = photo.resize((128, 128))
    gray = pxtf.image.convert(photo, 'L')
    w = photo.width
    h = photo.height


class Videos(TableModel, name='videos'):
    id = pxt.Column(value=pxtf.uuid.uuid7(), primary_key=True)
    title: pxt.String
    clip: pxt.Video
    duration = pxtf.video.get_duration(clip)
    frame = pxtf.video.extract_frame(clip, timestamp=0.5)
    thumb = frame.resize((256, 144))


# Service 1: Ingest
ingest = FastAPIRouter(name='ingest')
ingest.add_insert_route(
    Docs, path='/docs', inputs=[Docs.title, Docs.body], outputs=[Docs.id, Docs.title_upper, Docs.summary]
)
ingest.add_insert_route(
    Docs, path='/docs/async', inputs=[Docs.title, Docs.body], outputs=[Docs.id, Docs.title_upper, Docs.summary], background=True
)
ingest.add_update_route(Docs, path='/docs/update', inputs=[Docs.title], outputs=[Docs.id, Docs.title_upper])
ingest.add_compute_route(Docs, path='/titles', inputs=[Docs.title], outputs=[Docs.title_upper])
ingest.add_compute_route(
    Docs, path='/titles/async', inputs=[Docs.title], outputs=[Docs.title_upper], background=True
)


# a point read for the shootout's read path: one row by primary key
@pxt.query
def doc_by_id(doc_id: pxt.UUID) -> pxt.Query:
    return Docs.where(Docs.id == doc_id).select(Docs.id, Docs.title, Docs.body)


ingest.add_query_route(path='/docs/get', query=doc_by_id, one_row=True)

# Service 2: Multimodal Media Service
media = FastAPIRouter(name='media')
media.add_insert_route(
    Images,
    path='/photo',
    inputs=[Images.label],
    uploadfile_inputs=[Images.photo],
    outputs=[Images.id, Images.label, Images.w, Images.h, Images.thumb]
)
media.add_compute_route(
    Images,
    path='/photo/preview',
    inputs=[Images.label],
    uploadfile_inputs=[Images.photo],
    outputs=[Images.label, Images.w, Images.h, Images.thumb]
)
media.add_insert_route(
    Videos,
    path='/clip',
    inputs=[Videos.title],
    uploadfile_inputs=[Videos.clip],
    outputs=[Videos.id, Videos.title, Videos.duration, Videos.thumb]
)
media.add_insert_route(
    Videos,
    path='/clip/async',
    inputs=[Videos.title],
    uploadfile_inputs=[Videos.clip],
    outputs=[Videos.id, Videos.title, Videos.duration, Videos.thumb],
    background=True
)
