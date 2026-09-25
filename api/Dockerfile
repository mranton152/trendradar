FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache .

COPY contracts/ ./contracts/
COPY core/ ./core/
COPY ingest/ ./ingest/
COPY semantic/ ./semantic/
COPY api/ ./api/

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
