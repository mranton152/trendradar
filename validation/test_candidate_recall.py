from validation.candidate_recall import найти_кандидата, полнота_кандидатов

КАНДИДАТЫ = [
    {"cand_id": "c1", "kind": "term", "label": "vision transformer",
     "aliases": [], "top_terms": ["vision", "transformer"], "n_docs": 120},
    {"cand_id": "c2", "kind": "cluster", "label": "diffusion image generation",
     "aliases": ["denoising diffusion"], "top_terms": ["diffusion", "denoising",
                                                       "image", "generation"], "n_docs": 340},
    {"cand_id": "c3", "kind": "term", "label": "federated learning",
     "aliases": [], "top_terms": ["federated", "learning"], "n_docs": 900},
]


def test_точное_совпадение_находится():
    r = найти_кандидата("vision transformer", КАНДИДАТЫ)
    assert r is not None and r["cand_id"] == "c1"


def test_термин_находится_через_алиас():
    r = найти_кандидата("denoising diffusion", КАНДИДАТЫ)
    assert r is not None and r["cand_id"] == "c2"


def test_кластер_находится_по_ключевым_словам():
    """У кластера нет устоявшегося названия — по определению зарождающегося
    тренда. Поэтому засчитываем совпадение по его ключевым словам."""
    r = найти_кандидата("diffusion model", КАНДИДАТЫ)
    assert r is not None and r["cand_id"] == "c2"


def test_отсутствующий_термин_не_придумывается():
    assert найти_кандидата("neural radiance field", КАНДИДАТЫ) is None


def test_полнота_считается_и_называет_пропущенных():
    итог = полнота_кандидатов(["vision transformer", "diffusion model",
                               "neural radiance field", "state space model"],
                              КАНДИДАТЫ)
    assert итог["найдено"] == 2
    assert итог["всего"] == 4
    assert итог["полнота"] == 0.5
    assert set(итог["пропущены"]) == {"neural radiance field", "state space model"}


def test_пустой_пул_даёт_нулевую_полноту():
    итог = полнота_кандидатов(["vision transformer"], [])
    assert итог["полнота"] == 0.0
    assert итог["пропущены"] == ["vision transformer"]
