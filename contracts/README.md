# Контракты между слоями

Это стык, по которому три человека работают параллельно, не мешая друг другу.
Пока форматы соблюдаются, каждый может переписывать свою половину как угодно.

**Менять `schemas.py` имеет право только Антон.** Нужно новое поле — заведи issue
с меткой `contract`, обсудим и внесём одним PR. Самовольное добавление колонки
уронит CI у всех остальных.

## Поток данных

```
   ingest/          semantic/              core/             cards/        api/ + web/
 Константин        Константин             Антон            Михаил          Михаил
     │                  │                   │                 │                │
 works.parquet ──► candidates.parquet ──► trends.parquet ──► cards.parquet ──► HTTP
                   cand_docs.parquet         │                 ▲
                   embeddings.npy            └─── top_doc_ids ─┘
```

## Файлы и кто их делает

| Файл | Путь | Пишет | Читают |
|---|---|---|---|
| `works.parquet` | `data/corpus/{domain}/` | Константин | все |
| `candidates.parquet` | `data/index/{domain}/` | Константин | Антон |
| `cand_docs.parquet` | `data/index/{domain}/` | Константин | Антон, Михаил |
| `embeddings.npy` | `data/index/{domain}/` | Константин | Антон (MMR, дедуп) |
| `trends.parquet` | `data/index/{domain}/` | Антон | Михаил |
| `cards.parquet` | `data/index/{domain}/` | Михаил | Михаил (api) |
| `rejected.parquet` | `data/index/{domain}/` | Антон | Михаил — «причины исключения» по ТЗ |
| `meta.json` | `data/index/{domain}/` | кто последний считал стадию | все |

`{domain}` — slug домена: `artificial-intelligence`, `quantum-computing`.

## embeddings.npy

Обычный numpy-массив `float32` формы `(N, 1024)`, L2-нормированный.
Строка `i` соответствует кандидату с `emb_row == i` в `candidates.parquet`.
Модель фиксирована: `intfloat/multilingual-e5-large`. Меняем модель — меняем
`meta.json["embedding_model"]`, чтобы никто не сравнивал несравнимое.

## meta.json

```json
{
  "domain": "artificial-intelligence",
  "domain_query": "технологии в ИИ",
  "as_of": 2026,
  "built_at": "2026-09-10T14:00:00Z",
  "stages": {"ingest": "...", "semantic": "...", "core": "...", "cards": "..."},
  "n_works": 412000,
  "n_candidates": 8400,
  "embedding_model": "intfloat/multilingual-e5-large",
  "methodology_version": "1.0"
}
```

## Изменения 16.09 под ТЗ

Все новые поля nullable — старые файлы читаются без пересборки, валидатор
пропускает отсутствующие необязательные колонки.

- `WORKS` += `source_type`, `trust_level` (trusted|indicator|unknown), `summary_ru`,
  `summary_model` — карточка источника по ТЗ; резюме с обязательной пометкой модели.
- `TRENDS` += `bt_at_cutoff`, `bt_peak_after`, `bt_growth_x` — что было после среза,
  заполняются только при `as_of` в прошлом.
- `REJECTED` — новая таблица отсеянных с причинами.
- `meta.json` += `n_sources_polled`, `n_candidates`, `n_rejected` — счётчики в шапку.

## Признаки для классификатора (K-14 → A-12)

`FEATURES` — одна строка на кандидата: новостные признаки за 24 месяца, код и
модели, публикации за 10 лет, и разметка для обучающей выборки. Всё после
`label` nullable: источники могут отсутствовать. Списки фиксированной длины —
24 месяца и 10 лет, старые первыми, — чтобы классификатор мог брать их как есть.

Пути: `data/features/{domain}/features.parquet` для живых прогонов,
`data/dataset/features.parquet` для 100 технологий заказчика плюс наши отрицательные.

Правило для признака: он обязан быть объясним одной фразой аналитику банка.
`funding_mentions` — «сколько заголовков про раунды, stealth и пилоты». Признак,
который нельзя так описать, в отчёт не попадёт, а значит и в модель.

## Проверка перед PR

```bash
python contracts/validate.py data/corpus/artificial-intelligence/works.parquet --schema works
```

CI гоняет то же самое на «золотом» мини-снапшоте. Красный CI — PR не мержится.

## Золотой снапшот

`data/index/golden/` — маленький настоящий срез (один домен, ~5 тыс. документов,
~50 МБ), который лежит прямо в репозитории. Он существует ровно для одного:
чтобы Михаил делал фронт, а Антон — скоринг, не дожидаясь, пока Константин
соберёт полный корпус. Все тесты и весь CI работают на нём.

Полные корпуса в git не кладём — они десятки гигабайт. Их публикуем в
**GitHub Releases** и качаем скриптом `make pull-corpus`.

## Контракт HTTP

Черновик — `contracts/api.openapi.yaml`. Фиксируем в первый день после ТЗ,
чтобы фронт и бэк шли параллельно. До этого фронт работает на моках, собранных
из золотого снапшота.
