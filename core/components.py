"""Интерпретируемые компоненты Emergence Score.

Каждая компонента объяснима аналитику без ML-образования и показывается в UI:
пользователь видит не «0.803», а «в топ-10% по ускорению».

Опора — рамка Rotolo, Hicks & Martin (2015) «What is an emerging technology?»:
radical novelty (N), fast growth (G), coherence, prominent impact, uncertainty.
Ускорение (A), всплеск (B) и распространение (D) — наша операционализация.
"""
import math

from core.normalize import frequencies

ПОРОГ_ПЕРВОГО_УПОМИНАНИЯ = 5   # ниже — статистический шум и ошибки метаданных
ДОЛЯ_ПИКА_ДЛЯ_ВЗЛЁТА = 0.10


def _ols_slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den


def pct_rank(values: list[float]) -> list[float]:
    """Перцентильный ранг.

    Распределения тяжёлохвостые: z-score и min-max разъезжаются от одного выброса,
    перцентиль устойчив и интерпретируем.
    """
    порядок = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    n = max(1, len(values) - 1)
    for ранг, i in enumerate(порядок):
        out[i] = ранг / n
    return out


def components(counts: dict[int, int], norm: dict[int, float],
               as_of: int, window: int = 5) -> dict:
    years = list(range(as_of - window + 1, as_of + 1))
    freq = frequencies(counts, norm, years)
    logf = [math.log(f + 1.0) for f in freq]

    # N — новизна. Первый год упоминания в чистом виде не работает: у любого
    # термина найдутся единичные срабатывания 20-летней давности.
    история = {y: c for y, c in counts.items() if y <= as_of}
    пик = max(история.values()) if история else 0
    first_mention = takeoff = None
    for y in sorted(история):
        if first_mention is None and история[y] >= ПОРОГ_ПЕРВОГО_УПОМИНАНИЯ:
            first_mention = y
        if takeoff is None and история[y] >= max(ПОРОГ_ПЕРВОГО_УПОМИНАНИЯ * 2,
                                                 ДОЛЯ_ПИКА_ДЛЯ_ВЗЛЁТА * пик):
            takeoff = y
    опорный = takeoff or first_mention
    age = (as_of - опорный) if опорный else 99

    growth = _ols_slope(years, logf)

    # A — ускорение: разница наклонов второй и первой половины окна.
    # Именно оно отличает зарождающийся тренд от равномерно растущей области.
    половина = max(2, window // 2)
    accel = (_ols_slope(years[-половина:], logf[-половина:])
             - _ols_slope(years[:половина], logf[:половина]))

    # B — всплеск: упрощённый Kleinberg (2002)
    база = sum(freq[:-1]) / max(1, len(freq) - 1)
    burst = (freq[-1] + 0.1) / (база + 0.1)

    сумма = sum(freq)
    return {
        "first_mention": first_mention,
        "takeoff_year": takeoff,
        "age": age,
        "growth": growth,
        "accel": accel,
        "burst": burst,
        # зрелость: высокая доля в домене = мейнстрим, а не слабый сигнал
        "maturity": freq[-1],
        "freq_series": [round(f, 2) for f in freq],
        "counts_recent": int(sum(counts.get(y, 0) for y in years)),
        "active_years": sum(1 for f in freq if f > 0),
        "last_year_share": round(freq[-1] / сумма, 3) if сумма > 0 else 1.0,
        "years": years,
        "counts_series": [int(counts.get(y, 0)) for y in years],
    }
