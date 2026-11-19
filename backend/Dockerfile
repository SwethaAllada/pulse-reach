# Build from repository root: docker build -f backend/Dockerfile .
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY data-pipeline/rules ./data-pipeline/rules
COPY data/ ./data/

ENV PULSE_REACH_REPO_ROOT=/app \
    RULES_DIR=/app/data-pipeline/rules \
    DATA_DIR=/app/data

WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
