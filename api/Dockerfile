FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache .

COPY contracts/ ./contracts/
COPY core/ ./core/
COPY api/ ./api/
# Живой режим запускает сбор, кандидатов и ядро подпроцессами (api/routes/live.py).
# Без этих папок живой запрос в контейнере падал на первом шаге: No module named 'ingest'.
COPY ingest/ ./ingest/
COPY semantic/ ./semantic/
COPY cards/ ./cards/
# Отчёты для страницы методологии: без них в Docker на ней нет ни классификатора,
# ни проверки на прошлом.
COPY classifier/report.json ./classifier/report.json
COPY validation/report.json ./validation/report.json

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
