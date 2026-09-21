import httpx

from classifier.features import ОПИСАНИЯ, Сборщик


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_у_каждого_признака_есть_фраза_для_аналитика():
    """Требование ТЗ: система обязана показывать, по каким признакам решила."""
    сб = Сборщик(кэш={}, client=_mock(lambda r: httpx.Response(200, json={})))
    признаки = сб.признаки("x")
    assert set(признаки) == set(ОПИСАНИЯ), set(признаки) ^ set(ОПИСАНИЯ)


def test_кэш_не_даёт_ходить_в_сеть_дважды():
    вызовов = {"n": 0}

    def h(r):
        вызовов["n"] += 1
        return httpx.Response(200, json={"group_by": [{"key": "2025", "count": 7}]})
    сб = Сборщик(кэш={}, client=_mock(h))
    сб.openalex_годы("q"); сб.openalex_годы("q")
    assert вызовов["n"] == 1


def test_ошибка_api_не_роняет_сбор():
    сб = Сборщик(кэш={}, client=_mock(lambda r: httpx.Response(429)))
    f = сб.признаки("x")
    assert f["pub_total_10y"] == 0 and f["github_repos"] == 0 and f["hf_models"] == 0


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
