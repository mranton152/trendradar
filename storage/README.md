# storage/ — PostgreSQL как хранилище

ТЗ ставит PostgreSQL в стек «для сырых данных и результатов». Считаем мы
по-прежнему на parquet: так любая стадия воспроизводима и демо работает без
сети. Postgres получает копию каждого набора после расчёта — там собранные
документы и выдача лежат вместе, и аналитик достаёт их SQL-запросом.

```bash
make pg-up        # docker compose -f storage/compose.yml up -d --wait
make pg-load      # все наборы из data/ → Postgres
make pg-status    # что загружено, сколько строк, когда
```

Замер на MacBook: полный корпус `ai-full` (6,3 млн работ, 3,6 млн связей
кандидат–документ) грузится за **3 мин 15 с** и занимает в базе **12 ГБ**.
`make pg-load` грузит всё, что есть в `data/`, — при нехватке места берите
один набор.

Одиночный набор: `uv run python -m storage.load --dataset golden`.
Подключение: `TRENDRADAR_PG_DSN`, по умолчанию
`postgresql://trendradar:trendradar@localhost:55432/trendradar`.

## Как устроено

- **Схема выводится из `contracts/schemas.py`** (`storage/schema.py`). Таблица на
  каждый контракт, плюс колонка `dataset` — имя набора (`golden`, `ai-full`,
  живой запрос). Поле, добавленное в контракт, добавляется в таблицу при
  следующей загрузке.
- **Перед загрузкой файл проверяется контрактом** — тем же валидатором, что в CI.
- **Набор грузится одной транзакцией.** Сломанный файл откатывает весь набор:
  в базе остаётся предыдущая целая версия, а не половина новой.
- **Перезагрузка заменяет, а не дублирует.** Естественные ключи
  (`doc_id`, `trend_id`, …) — первичные, повтор строки в файле — ошибка.
- **`loads`** — журнал: какой файл, сколько строк, sha256, когда. По sha256
  видно, что в базе ровно тот файл, из которого строилась выдача.

## Запросы

ТОП-15 на срезе:

```sql
SELECT rank, label, round(emergence_score::numeric, 2) AS score, takeoff_year, stage
FROM trends WHERE dataset = 'golden' AND as_of = 2026 ORDER BY rank;
```

Первоисточники тренда:

```sql
SELECT w.year, w.title, w.url
FROM trends t
CROSS JOIN LATERAL unnest(t.top_doc_ids) AS d(doc_id)
JOIN works w ON w.dataset = t.dataset AND w.doc_id = d.doc_id
WHERE t.dataset = 'golden' AND t.trend_id = 't:golden:2026:01';
```

Бэктест — что выросло после среза:

```sql
SELECT label, bt_at_cutoff, bt_peak_after, bt_growth_x
FROM trends WHERE dataset = 'golden' AND as_of = 2021 ORDER BY bt_growth_x DESC NULLS LAST;
```

Почему кандидат отсеян:

```sql
SELECT label, n_docs, reason FROM rejected
WHERE dataset = 'golden' ORDER BY n_docs DESC LIMIT 20;
```

## Чего здесь нет

API читает parquet, а не базу: переводить его на Postgres за пять дней до
сдачи — риск без выигрыша для жюри. Живые запросы (`data/live/`) в базу
пока не пишутся — это следующий шаг, когда K-12 определит формат папки.
