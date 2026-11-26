FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

COPY pipeline/requirements.txt /app/pipeline/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/pipeline/requirements.txt

COPY config/settings.toml config/cuisine_map.csv /app/config/
COPY sql/002_create_gold_views.sql /app/sql/002_create_gold_views.sql
COPY pipeline /app/pipeline

RUN mkdir -p /app/data/bronze /app/data/quarantine /app/data/reports /app/logs \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

ENTRYPOINT ["python", "-m", "pipeline.runner"]
