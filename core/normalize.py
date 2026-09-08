"""Peer-нормировка частот.

Нормировка на полный корпус домена даёт ложное падение последнего года:
метаданные индексируются быстрее абстрактов, поэтому поиск по тексту отстаёт
от общего счётчика работ. Peer-нормировка использует один и тот же способ
подсчёта в числителе и в знаменателе, и годовой перекос сокращается.
"""


def peer_normalizer(all_counts: list[dict[int, int]], years: list[int]) -> dict[int, float]:
    """Знаменатель = суммарная активность пула кандидатов за год."""
    return {y: max(1.0, float(sum(c.get(y, 0) for c in all_counts))) for y in years}


def frequencies(counts: dict[int, int], norm: dict[int, float],
                years: list[int]) -> list[float]:
    """Доля кандидата в активности пула, на миллион. Убирает общий рост науки."""
    return [float(counts.get(y, 0)) / norm.get(y, 1.0) * 1e6 for y in years]
