# semantic — владелец: Константин

Превращение корпуса в кандидатов в тренды: эмбеддинги, кластеризация UMAP+HDBSCAN, названия кластеров через c-TF-IDF, кандидаты-термины, технологический фильтр. Все тяжёлые прогоны идут на RTX 3070.

**Полный бриф: [../team/PROMPT-konstantin.md](../team/PROMPT-konstantin.md).**
Общие правила: [../AGENTS.md](../AGENTS.md). Контракты: [../contracts/README.md](../contracts/README.md).

## Что эта папка отдаёт наружу

`candidates.parquet`, `cand_docs.parquet`, `embeddings.npy`, `meta.json` в `data/index/{domain}/`.

## Границы

Пишем только в эту папку (и в соседние папки того же владельца). Чужие папки не
трогаем никогда — даже ради опечатки. `contracts/schemas.py` не меняем.
