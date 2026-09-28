# TrendRadar — детектор зарождающихся технологических трендов

Решение кейса Газпромбанк.Тех на ЛЦТ-2026: сервис находит **слабые сигналы** —
технологии, которые ещё не стали мейнстримом, — и для каждого показывает
мотивацию, кейс, первоисточник и доказательство того, что тренд именно
зарождается: год взлёта, динамику публикаций, распространение.

Числа считает статистика по открытым источникам, LLM только формулирует текст
по найденным документам и не утверждает ничего без ссылки на источник.

| Что проверяли | Результат |
|---|---|
| Классификатор на датасете заказчика (5-fold CV, 20 разбиений) | **78%** accuracy (76,5–80%, порог ТЗ 75% взят на всех 20), F1 0,80 — [отчёт](classifier/REPORT.md) |
| Бэктест: считаем по данным до 2021, смотрим, что стало к 2026 | **93%** трендов выросли, фора до пика **6 лет** — [отчёт](validation/REPORT.md) |
| Первый в ТОПе среза 2021 — `vision transformer` | вырос к 2026 в **65 раз** |

## Быстрый старт (Docker)

Нужно: Docker Desktop или Docker Engine с Compose **2.20+** (`docker compose version`),
~5 ГБ на диске, свободные порты **3000**, **8000**, **55432**.

Для **живого запроса** по произвольному направлению нужна локальная модель
[Ollama](https://ollama.com) на той же машине (не в Docker — так она использует GPU
Mac). Она переводит запрос и находит названия технологий в заголовках новостей:

```bash
ollama pull qwen2.5:7b    # один раз, 4,7 ГБ
ollama serve              # если Ollama не запущена как приложение
```

**Без Ollama живой запрос практически пуст:** запрос не переводится на английский,
и сбор идёт только по русской формулировке (замер: 93 документа, 0 кандидатов
против 525 документов и 26 кандидатов с моделью). Выдача по индексу от Ollama
не зависит.

Ключ OpenAlex **необязателен**. С ключом (`OPENALEX_API_KEY=...` в файле `.env`
в корне) живой сбор добавляет историю научных публикаций; без ключа фильтр
зрелости всё равно работает через анонимный доступ.

```bash
git clone https://github.com/mranton152/trendradar.git
cd trendradar
docker compose up --build -d
```

Первая сборка — около 10 минут (скачиваются образы), дальше — секунды.

| Адрес | Что там |
|---|---|
| http://localhost:3000 | веб-интерфейс: введите направление — живой запрос идёт около минуты |
| http://localhost:8000/docs | API, интерактивная документация (Swagger) |
| `localhost:55432` | PostgreSQL: `trendradar` / `trendradar`, база `trendradar` |

Проверить, что всё поднялось:

```bash
docker compose ps
curl http://localhost:8000/api/v1/health
```

Что запускается:

| Сервис | Что делает |
|---|---|
| `api` | FastAPI, отдаёт тренды, карточки, методологию |
| `web` | Next.js 15, интерфейс аналитика |
| `postgres` | PostgreSQL 16 — хранилище сырых данных и выдачи |
| `pg-load` | разово заливает в базу золотой снапшот и завершается |

Остановить: `docker compose down`. Удалить и данные базы: `docker compose down -v`.

**Если порт занят** — например, 3000 уже слушает другой проект, — поменяйте
левую часть `"3000:3000"` в `docker-compose.yml` на свободный порт. Порт
Postgres задаётся переменной: `TRENDRADAR_PG_PORT=55433 docker compose up -d`.

## Запросы к базе

После `docker compose up` в Postgres уже лежит золотой снапшот. Например, ТОП-15:

```bash
docker compose exec postgres psql -U trendradar -c \
  "SELECT rank, label, round(emergence_score::numeric, 2) AS score, takeoff_year, stage
   FROM trends WHERE dataset = 'golden' AND as_of = 2026 ORDER BY rank;"
```

Первоисточники тренда, бэктест, причины отсева — [storage/README.md](storage/README.md).

## Без Docker

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/) (или pip), Node.js 20+.

```bash
uv sync                          # или: pip install -r requirements.txt
uv run uvicorn api.main:app      # API на :8000

cd web && npm ci && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # веб на :3000
```

Зависимости: [pyproject.toml](pyproject.toml) и [uv.lock](uv.lock) — точные
версии; [requirements.txt](requirements.txt) — то же для pip, CI проверяет,
что файлы не разошлись. Фронтенд — [web/package.json](web/package.json).

## Воспроизвести результаты

Все команды работают на чистом клоне без сети.

```bash
uv run python -m classifier.train --offline     # классификатор: 78% ± 1, пишет classifier/REPORT.md
uv run python -m validation.report --source pool # бэктест на срезе 2021: 93%, фора 6 лет
uv run pytest -q                                # 247 тестов
```

`--offline` обучает по закоммиченному снимку признаков `classifier/features_v1.json`.
Без флага признаки собираются заново из OpenAlex, GitHub и Hugging Face — для
этого нужен датасет заказчика (путь — `--xlsx`) и около часа из-за лимитов API.

Полный конвейер на своём домене. Золотой снапшот содержит только результаты,
поэтому пересчёт начинается со сбора:

```bash
uv run python -m ingest.harvest  --domain <домен> --as-of 2026-09-01   # сбор, нужна сеть
uv run python -m semantic.build  --domain <домен> ...                  # кандидаты, см. --help
uv run python -m core.build      --domain <домен> --as-of 2026         # ряды, скоринг, фильтры
uv run python -m cards.build     --domain <домен> --as-of 2026         # карточки, нужна Ollama
uv run python -m storage.load    --dataset <домен>                     # копия в Postgres
```

## Как устроено

```
ingest/    сбор из открытых источников     → data/corpus/{d}/works.parquet
semantic/  кандидаты: термины и кластеры   → data/index/{d}/candidates.parquet
core/      ряды, скоринг, фильтры          → data/index/{d}/trends.parquet, rejected.parquet
cards/     карточки со ссылками            → data/index/{d}/cards.parquet
storage/   хранилище                       → PostgreSQL
api/ web/  выдача                          ← читают data/index/, ничего не считают
```

Парсинг, аналитика и интерфейс разделены: каждая стадия — отдельная команда,
слои связаны файлами, формат которых описан в [contracts/schemas.py](contracts/schemas.py)
и проверяется в CI.

| Документ | О чём |
|---|---|
| [docs/presentation/TrendRadar.pdf](docs/presentation/TrendRadar.pdf) | **презентация**, 15 слайдов |
| [docs/16-technical.md](docs/16-technical.md) | **техническая документация**: пайплайн, отбор признаков, фильтрация шума, отказоустойчивость |
| [docs/diagrams/](docs/diagrams/) | схемы архитектуры, конвейера и живого запроса (PlantUML) |
| [docs/01-methodology.md](docs/01-methodology.md) | методология детекции: формулы, обоснования, литература |
| [classifier/REPORT.md](classifier/REPORT.md) | отчёт классификатора: метрики, веса признаков, абляция, ошибки |
| [validation/REPORT.md](validation/REPORT.md) | бэктест на срезе 2021 |
| [validation/FULL_CORPUS_FINDINGS.md](validation/FULL_CORPUS_FINDINGS.md) | что не сработало на 6,3 млн работ и почему |

## Стек

Python 3.12 · DuckDB + Parquet · scikit-learn · sentence-transformers
(`multilingual-e5-large`) + UMAP + HDBSCAN · FastAPI · Next.js 15 + TypeScript +
Recharts · PostgreSQL 16 · Ollama (локальная LLM) · Docker Compose · uv · ruff + pytest.

## Команда

| Кто | Роль | Папки |
|---|---|---|
| Антон Загитов | капитан, методология, ядро, классификатор, хранилище | `core/`, `classifier/`, `storage/`, `validation/`, `contracts/` |
| Константин | сбор данных, семантика | `ingest/`, `semantic/` |
| Михаил Алексеев | API, веб-интерфейс, карточки, Docker | `api/`, `web/`, `cards/` |

Как мы работали втроём без конфликтов — [team/WORKFLOW.md](team/WORKFLOW.md).
Для разработчиков: `make help`, `make check` перед каждым пулл-реквестом.
