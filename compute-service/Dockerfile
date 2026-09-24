# compute-service as a container, for a host that is not this laptop.
#
# Runs as an unprivileged user on PORT (8080 by default). Every model is downloaded at
# build time, so a cold start loads weights from disk instead of fetching them: a task
# that starts pays the load, not the download, and the benchmark can tell the two apart.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/cache \
    XDG_CACHE_HOME=/home/user/cache \
    PORT=8080
WORKDIR /home/user/app

# CPU wheels. The host has no GPU, and the default torch and llama-cpp-python builds
# pull CUDA or compile from source. app.py offloads to a GPU only when the build supports
# one, so on these wheels the chat model runs on CPU, as it would on any CPU host.
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --user llama-cpp-python \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

COPY --chown=user pyproject.toml app.py ./
RUN pip install --no-cache-dir --user .

COPY --chown=user prefetch.py ./
RUN python prefetch.py

EXPOSE 8080
# Keep-alive as in every launch: KEEP_ALIVE_SEC in app.py says why.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 120"]
