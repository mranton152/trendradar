# Разовая загрузка наборов из data/ в Postgres. Контекст сборки — корень репозитория.
FROM python:3.12-slim

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY contracts/ ./contracts/
COPY storage/ ./storage/

ENTRYPOINT ["python", "-m", "storage.load"]
CMD ["--dataset", "golden"]
