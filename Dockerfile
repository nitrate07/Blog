FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY evidence/requirements.txt evidence/requirements.txt
RUN pip install --no-cache-dir -r evidence/requirements.txt

COPY evidence/ evidence/
COPY articles/ articles/
COPY tr/ tr/

RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

ENV EVIDENCE_DATABASE_PATH=/app/data/evidence.db \
    EVIDENCE_RAG_PERSIST_DIRECTORY=/app/data/chroma
VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "evidence.v2.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
