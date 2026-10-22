FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data MODEL_CACHE_DIR=/app/data/models HF_HOME=/app/data/huggingface
WORKDIR /app
COPY requirements-lock.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements-lock.txt \
    && groupadd --gid 10001 bible \
    && useradd --uid 10001 --gid bible --no-create-home bible \
    && mkdir -p /app/data && chown bible:bible /app/data
COPY backend ./backend
COPY resources/cuv.jsonl resources/manifest.json ./resources/
COPY scripts/warm_model.py scripts/reindex_all.py scripts/server_entrypoint.py ./scripts/
COPY frontend/dist ./frontend/dist
USER bible
EXPOSE 8000
CMD ["python", "scripts/server_entrypoint.py"]
