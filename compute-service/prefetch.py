"""Download every model compute-service loads, through the same names it uses.

Run at image build (see Dockerfile). Going through app.py's own getters and constants
means the cached weights are exactly the ones the service asks for, not a second list to
keep in step with it.
"""

import fnmatch

from app import CHAT_FILENAME, CHAT_REPO_ID, _get_clip, _get_text_model, _get_whisper
from huggingface_hub import HfApi, hf_hub_download

for load in (_get_clip, _get_whisper, _get_text_model):
    load()
    print(f'fetched {load.__name__.removeprefix("_get_")}', flush=True)

# The chat model is downloaded, not loaded. llama.cpp's CPU kernels use x86 vector
# instructions that an emulated build host may lack (it dies with SIGILL), and the file in
# the cache, where Llama.from_pretrained looks for it, is all a cold start needs.
(name,) = fnmatch.filter(HfApi().list_repo_files(CHAT_REPO_ID), CHAT_FILENAME)
hf_hub_download(CHAT_REPO_ID, name)
print(f'fetched chat_model {name}', flush=True)
