# Перенос на MacBook и первый запуск

Целевая папка: `/Users/antonzagitov/Work/khakaton2026`

## Вариант 1. Клонировать с сервера напрямую

```bash
git clone ssh://root@SERVER_IP/home/lct-trendradar /Users/antonzagitov/Work/khakaton2026
```

## Вариант 2. Из bundle-файла

Если файл `khakaton2026.bundle` уже скачан в `~/Downloads`:

```bash
git clone ~/Downloads/khakaton2026.bundle /Users/antonzagitov/Work/khakaton2026
```

Bundle — это весь репозиторий с историей в одном файле, ничего не теряется.

## Проверка, что всё на месте

```bash
cd /Users/antonzagitov/Work/khakaton2026 && git log --oneline && ls docs/
```

Прототип детектора запускается без установки зависимостей:

```bash
python3 spikes/openalex_probe.py --domain "artificial intelligence" --top 15
```

Первый прогон занимает 10–15 минут (сеть), повторные — мгновенные из кэша
`data/cache/`. Кэш в репозиторий не входит, он локальный.

## Что настроить на маке до старта разработки

1. **Docker Desktop**: поднять лимит памяти до 8–12 ГБ (Settings → Resources).
   По умолчанию мало, Postgres с векторными индексами упрётся.
2. **Ollama нативно на хосте**, не в контейнере — иначе не будет Metal:
   ```bash
   brew install ollama && ollama serve
   ollama pull qwen2.5:7b
   ```
3. **Python 3.12 + uv** для управления зависимостями:
   ```bash
   brew install uv
   ```
4. Проверить, что образы тянутся под arm64 без эмуляции:
   ```bash
   docker pull pgvector/pgvector:pg16 && docker image inspect pgvector/pgvector:pg16 --format '{{.Architecture}}'
   ```
   Должно вывести `arm64`.

## Синхронизация мак ↔ сервер

Через общий удалённый репозиторий (GitHub или bare-репозиторий на сервере),
не через копирование папок. На сервере остаётся кэш ответов API — он тяжёлый
(уже 15 МБ) и в git не едет.
