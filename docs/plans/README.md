# Планы реализации

Три плана, по одному на человека. Каждый пишет **только в свои папки**, поэтому
планы не пересекаются и выполняются параллельно.

| План | Кто | Папки |
|---|---|---|
| [phase0-konstantin.md](2026-09-08-phase0-konstantin.md) | Константин | `ingest/`, `semantic/` |
| [phase0-mikhail.md](2026-09-08-phase0-mikhail.md) | Михаил | `cards/`, `api/`, `web/` |
| [phase0-anton.md](2026-09-08-phase0-anton.md) | Антон | `core/`, `validation/` |

## Как исполнять

Задачи идут по порядку и построены одинаково: сначала падающий тест, потом
минимальная реализация, потом коммит. Не пропускай шаг «убедись, что тест падает» —
тест, который проходит до реализации, ничего не проверяет.

Одна задача = одна ветка = один PR:

```bash
git checkout main && git pull
git checkout -b feat/<имя>/<номер-задачи>
# ... шаги задачи ...
make check
git push -u origin feat/<имя>/<номер-задачи>
```

## Global Constraints

Действуют во всех трёх планах, повторять в каждой задаче не буду.

- **Python 3.12**, зависимости через `uv`, объявляются в `pyproject.toml`.
- **Схемы данных — закон.** `contracts/schemas.py` менять нельзя. Любой parquet,
  который ты пишешь, обязан проходить `python contracts/validate.py <файл> --schema <имя>`.
- **Пиши только в свои папки.** CI роняет PR за выход за границы.
- **Никаких сетевых обращений в рантайме API.** Сеть — только в стадиях `ingest`
  и `cards` (генерация), и всё кэшируется на диск.
- **Воспроизводимость:** любой рандом фиксируется семенем (`random_state=42`,
  `seed=42`). Прогон на другой машине обязан давать тот же результат.
- **Никаких утверждений без источника.** Любой текст о тренде выводится из
  документов корпуса и несёт `doc_id`.
- Комментарии и docstring — по-русски, идентификаторы — по-английски.
- Тесты рядом с кодом: `ingest/test_http.py`, `core/test_components.py`.
- Коммиты по-русски, осмысленные. `git commit -m "wip"` не считается.

## Пути к данным

```
data/corpus/{domain}/works.parquet
data/index/{domain}/candidates.parquet
data/index/{domain}/cand_docs.parquet
data/index/{domain}/embeddings.npy
data/index/{domain}/trends.parquet
data/index/{domain}/cards.parquet
data/index/{domain}/meta.json
data/index/golden/            ← мини-срез в репозитории, на нём тесты и CI
```

`{domain}` — slug: `artificial-intelligence`.
