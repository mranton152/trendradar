# ingest — владелец: Константин

Сбор данных из открытых источников и приведение их к единой схеме. Коннекторы (OpenAlex, arXiv, Crossref, HuggingFace, GitHub, патенты), кэш ответов, нормализация, докачка.

**Полный бриф: [../team/PROMPT-konstantin.md](../team/PROMPT-konstantin.md).**
Общие правила: [../AGENTS.md](../AGENTS.md). Контракты: [../contracts/README.md](../contracts/README.md).

## Что эта папка отдаёт наружу

`data/corpus/{domain}/works.parquet` по схеме `WORKS`.

## Границы

Пишем только в эту папку (и в соседние папки того же владельца). Чужие папки не
трогаем никогда — даже ради опечатки. `contracts/schemas.py` не меняем.
