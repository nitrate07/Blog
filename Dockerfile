FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG INSTALL_CHROMA_RAG=false

COPY evidence/requirements.txt evidence/requirements.txt
COPY evidence/requirements-rag-chroma.txt evidence/requirements-rag-chroma.txt
RUN pip install --no-cache-dir -r evidence/requirements.txt \
    && if [ "$INSTALL_CHROMA_RAG" = "true" ]; then \
         pip install --no-cache-dir -r evidence/requirements-rag-chroma.txt; \
       fi

COPY evidence/ evidence/
COPY articles/ articles/
COPY tr/ tr/

RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

ENV EVIDENCE_DATABASE_PATH=/app/data/evidence.db \
    EVIDENCE_RAG_PERSIST_DIRECTORY=/app/data/chroma \
    EVIDENCE_RAG_CHROMA_PERSIST_DIRECTORY=/app/data/chroma_embeddings
VOLUME ["/app/data"]

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health')"

CMD ["sh", "-c", "uvicorn evidence.v2.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
