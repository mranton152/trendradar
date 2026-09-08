# core — владелец: Антон

Ядро методологии: годовые ряды, peer-нормировка, компоненты Emergence Score (новизна, рост, ускорение, всплеск, распространение), структурные фильтры, дедуп, MMR, режим `as_of`. Логика-прототип — в `spikes/openalex_probe.py`.

**Полный бриф: [../team/PROMPT-anton.md](../team/PROMPT-anton.md).**
Общие правила: [../AGENTS.md](../AGENTS.md). Контракты: [../contracts/README.md](../contracts/README.md).

## Что эта папка отдаёт наружу

`data/index/{domain}/trends.parquet` по схеме `TRENDS`.

## Границы

Пишем только в эту папку (и в соседние папки того же владельца). Чужие папки не
трогаем никогда — даже ради опечатки. `contracts/schemas.py` не меняем.
