FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    RCA_RUNTIME_DIR=/app/runtime \
    RCA_MODE=all \
    RCA_API_HOST=0.0.0.0 \
    RCA_API_PORT=8000

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests

RUN pip install --no-cache-dir -e ".[test]" \
    && mkdir -p /app/runtime/output

EXPOSE 8000 8501

CMD ["python", "-m", "rca_engine.main"]
