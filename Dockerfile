FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN python -m pip install --no-cache-dir . \
    && groupadd --system taj \
    && useradd --system --gid taj --home-dir /nonexistent taj \
    && mkdir -p /data/workspace \
    && chown taj:taj /data/workspace

USER taj

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn jarvis.main:app --app-dir src --host 0.0.0.0 --port \"${PORT:-8000}\""]
