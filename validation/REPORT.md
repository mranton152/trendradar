# Отчёт валидации

Срез `as_of = 2021`, проверка по данным до 2026.
Методология версии 1.0, собрано 2026-09-10.

| Метрика | Значение | Смысл |
|---|---|---|
| Precision@15 по эталону | 47% | доля топа, попавшая в список заведомо выстреливших технологий |
| Доля мейнстрима в топе | 7% | **чем меньше, тем лучше**: это уже известные темы, а не слабые сигналы |
| Выросли после среза | 93% | доля трендов, чья активность выросла более чем в 1.2 раза |
| Медианный lead time | 6 лет | за сколько лет до пика тренд был обнаружен |

Эталонный список собран до прогонов и не менялся по их результатам —
иначе цифра Precision ничего не значит.

## ТОП-15 на срезе 2021

| # | Тренд | Год взлёта | Рост после среза |
|---|---|---|---|
| 1 | vision transformer | 2021 | x65.02 |
| 2 | differentiable rendering | 2021 | x2.67 |
| 3 | contrastive learning | 2020 | x20.37 |
| 4 | self-supervised learning | 2019 | x5.65 |
| 5 | physics-informed neural network | 2020 | x11.23 |
| 6 | neural architecture search | 2019 | x1.88 |
| 7 | meta learning | 2018 | x3.5 |
| 8 | continual learning | 2018 | x6.6 |
| 9 | covid-19 pandemic | 2020 | x0.99 |
| 10 | knowledge distillation | 2019 | x6.7 |
| 11 | graph neural network | 2020 | x6.67 |
| 12 | bayesian optimization | 2017 | x3.99 |
| 13 | time series forecasting | 2020 | x3.41 |
| 14 | model compression | 2018 | x4.03 |
| 15 | transformer | 2021 | x11.12 |

## Параметры

Веса компонент: `{'novelty': 0.2, 'growth': 0.32, 'accel': 0.23, 'burst': 0.15, 'diffusion': 0.1}`

Пороги фильтров: `{'MAX_AGE': 8, 'MIN_EVIDENCE': 20, 'MIN_COUNTRIES': 5, 'MIN_ACTIVE_YEARS': 3, 'MAX_LAST_YEAR_SHARE': 0.8, 'MIN_COUNTRIES_ДЛЯ_ВСПЛЕСКА': 10, 'MAX_MATURITY_PCT': 0.9}`
