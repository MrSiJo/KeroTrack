FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/London

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash app

WORKDIR /app
COPY pyproject.toml ./
COPY kerotrack ./kerotrack

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/data /app/logs && chown -R app:app /app

USER app
EXPOSE 9176

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9176/api/health || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "--factory", "kerotrack.main:create_app", "--host", "0.0.0.0", "--port", "9176"]
