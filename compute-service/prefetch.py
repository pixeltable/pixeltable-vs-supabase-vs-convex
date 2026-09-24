"""Download every model compute-service loads, through the same loaders it uses.

Run at image build (see Dockerfile). Going through app.py's own getters means the
cached weights are exactly the ones the service asks for, not a second list to keep in
step with it.
"""

from app import _get_chat_model, _get_clip, _get_text_model, _get_whisper

for load in (_get_clip, _get_whisper, _get_text_model, _get_chat_model):
    load()
    print(f'fetched {load.__name__.removeprefix("_get_")}', flush=True)
