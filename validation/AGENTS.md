# validation — владелец: Антон

Честная проверка метода: Precision@15, lead time, recall по эталонному списку, сравнение с baseline, абляция компонент. Эталонный список собирается ДО прогонов.

**Полный бриф: [../team/PROMPT-anton.md](../team/PROMPT-anton.md).**
Общие правила: [../AGENTS.md](../AGENTS.md). Контракты: [../contracts/README.md](../contracts/README.md).

## Что эта папка отдаёт наружу

`validation/REPORT.md` и JSON для эндпойнта `/api/v1/methodology`.

## Границы

Пишем только в эту папку (и в соседние папки того же владельца). Чужие папки не
трогаем никогда — даже ради опечатки. `contracts/schemas.py` не меняем.
