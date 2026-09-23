import httpx

from classifier.features import ОПИСАНИЯ, Сборщик


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_у_каждого_признака_есть_фраза_для_аналитика():
    """Требование ТЗ: система обязана показывать, по каким признакам решила.
    Собираем и HN-признаки, но в набор модели они не входят - замер показал
    вред; их множество объявлено отдельно в HN_ПРИЗНАКИ."""
    from classifier.features import HN_ПРИЗНАКИ
    сб = Сборщик(кэш={}, client=_mock(lambda r: httpx.Response(200, json={})))
    признаки = set(сб.признаки("x"))
    assert признаки == set(ОПИСАНИЯ) | set(HN_ПРИЗНАКИ)
    assert not (set(ОПИСАНИЯ) & set(HN_ПРИЗНАКИ))


def test_кэш_не_даёт_ходить_в_сеть_дважды():
    вызовов = {"n": 0}

    def h(r):
        вызовов["n"] += 1
        return httpx.Response(200, json={"group_by": [{"key": "2025", "count": 7}]})
    сб = Сборщик(кэш={}, client=_mock(h))
    сб.openalex_годы("q")
    сб.openalex_годы("q")
    assert вызовов["n"] == 1


def test_ошибка_api_не_подменяется_нулём():
    """Ноль «нет публикаций» и ноль «ответа не было» - разные вещи. Первый прогон
    получил 441 отказ 429 и молча записал нули - модель училась на дырах."""
    import pytest

    from classifier.features import ОтказИсточника
    сб = Сборщик(кэш={}, client=_mock(lambda r: httpx.Response(429)))
    with pytest.raises(ОтказИсточника):
        сб.признаки("x")
    assert "oa:years:x" not in сб.кэш


def test_ошибочный_ответ_в_старом_кэше_перезапрашивается():
    вызовов = {"n": 0}

    def h(r):
        вызовов["n"] += 1
        return httpx.Response(200, json={"group_by": []})
    сб = Сборщик(кэш={"oa:years:q": {"_error": 429}},
                 client=_mock(h))
    сб.openalex_годы("q")
    assert вызовов["n"] == 1


def test_свежая_доля_репозиториев_считается_по_дате():
    def h(r):
        if "github" in str(r.url):
            return httpx.Response(200, json={"total_count": 3, "items": [
                {"stargazers_count": 900, "created_at": "2026-01-01T00:00:00Z"},
                {"stargazers_count": 10, "created_at": "2019-01-01T00:00:00Z"}]})
        return httpx.Response(200, json={})
    сб = Сборщик(кэш={}, client=_mock(h))
    g = сб.github("x")
    assert g["github_stars_max"] == 900 and g["github_new_share"] == 0.5


def test_запрос_без_кавычек_и_откат_на_алиасы():
    """Точная фраза в кавычках даёт ноль у 63 сигналов из 100: многословные
    названия технологий никто не пишет дословно. 'AI agent IAM' в кавычках - 0,
    без кавычек - 136. Ищем по И-связке слов, при нуле пробуем алиасы."""
    запросы = []

    def h(r):
        f = dict(r.url.params)["filter"]
        запросы.append(f)
        есть = "agent identity management" in f
        ряд = [{"key": "2025", "count": 42}] if есть else []
        return httpx.Response(200, json={"group_by": ряд})

    сб = Сборщик(кэш={}, client=_mock(h))
    годы = сб.openalex_годы("AI agent IAM", алиасы=["agent identity management"])
    assert годы == {2025: 42}
    assert all('"' not in f for f in запросы), запросы
    assert сб.использованный_запрос["AI agent IAM"] == "agent identity management"


def test_основной_запрос_не_перебивается_алиасом():
    сб = Сборщик(кэш={}, client=_mock(
        lambda r: httpx.Response(200, json={"group_by": [{"key": "2024", "count": 5}]})))
    assert сб.openalex_годы("vision transformer", алиасы=["ViT"]) == {2024: 5}
    assert сб.использованный_запрос["vision transformer"] == "vision transformer"


def test_новостные_признаки_считаются_по_датам():
    """Все ошибки модели на публикационных признаках - «сигнал → зрелая»:
    у нейроморфных чипов и event-based сенсоров наука старая, а индустрия
    новая. Новостной сигнал это ловит."""
    import time
    сейчас = int(time.time())
    год = 365 * 24 * 3600

    def h(r):
        return httpx.Response(200, json={"hits": [
            {"created_at_i": сейчас - 30 * 24 * 3600, "points": 120,
             "title": "Startup raises $30M Series A"},
            {"created_at_i": сейчас - 60 * 24 * 3600, "points": 45,
             "title": "Company exits stealth"},
            {"created_at_i": сейчас - 4 * год, "title": "Old research paper", "points": 5},
        ]})
    сб = Сборщик(кэш={}, client=_mock(h))
    f = сб.hackernews("x")
    assert f["hn_mentions_12m"] == 2
    assert f["hn_recent_share"] == 2 / 3
    assert f["hn_funding_mentions"] == 2
    assert f["hn_points_max"] == 120


def test_пустой_ответ_hn_не_ломает_признаки():
    сб = Сборщик(кэш={}, client=_mock(lambda r: httpx.Response(200, json={"hits": []})))
    f = сб.hackernews("x")
    assert f["hn_mentions_12m"] == 0 and f["hn_recent_share"] == 0.0
