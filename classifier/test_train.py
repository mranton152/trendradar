import random

from classifier.features import ОПИСАНИЯ
from classifier.train import абляция, важность, главное, матрица, модели, оценить


def _синтетика(n=120):
    """Сигналы: мало публикаций, но свежие и с растущим GitHub. Зрелые: много и старые."""
    rng = random.Random(1)
    rows = []
    for i in range(n):
        сигнал = i % 2 == 0
        rows.append({"label": f"t{i}", "domain": "x", "is_weak_signal": сигнал,
                     "pub_total_10y": rng.randint(5, 80) if сигнал else rng.randint(500, 5000),
                     "pub_last_3y_share": rng.uniform(0.6, 0.95) if сигнал else rng.uniform(0.2, 0.4),
                     "pub_growth": rng.uniform(0.3, 1.0) if сигнал else rng.uniform(-0.1, 0.1),
                     "pub_accel": rng.uniform(0.0, 0.5), "pub_burst": rng.uniform(0.8, 3.0),
                     "pub_age": rng.randint(0, 3) if сигнал else rng.randint(8, 25),
                     "pub_countries": rng.randint(2, 15) if сигнал else rng.randint(40, 120),
                     "pub_company_share": rng.uniform(0, 0.3),
                     "github_repos": rng.randint(0, 50) if сигнал else rng.randint(1000, 90000),
                     "github_stars_max": rng.randint(0, 500), "github_new_share": rng.uniform(0.5, 1.0) if сигнал else rng.uniform(0, 0.2),
                     "hf_models": rng.randint(0, 20) if сигнал else rng.randint(100, 5000),
                     "log_pub_total": 0.0})
    return rows


def test_матрица_в_порядке_описаний():
    X, y = матрица(_синтетика(10))
    assert X.shape == (10, len(ОПИСАНИЯ)) and set(y) == {0, 1}


def test_на_разделимой_синтетике_обе_модели_берут_порог():
    и = главное(_синтетика())
    assert и["модели"]["logreg"]["accuracy"] >= 0.9
    assert и["модели"]["gboost"]["accuracy"] >= 0.9
    assert и["выбор"] == "logreg"     # простейшая из проходящих


def test_важность_объяснена_фразами():
    X, y = матрица(_синтетика())
    m = модели()["logreg"].fit(X, y)
    в = важность(m, list(ОПИСАНИЯ))
    assert all(x["смысл"] for x in в) and len(в) == len(ОПИСАНИЯ)


def test_абляция_называет_самый_важный_признак_первым():
    X, y = матрица(_синтетика())
    база = оценить(модели()["logreg"], X, y)["accuracy"]
    а = абляция(X, y, list(ОПИСАНИЯ), база)
    assert а[0]["потеря"] >= а[-1]["потеря"]


def test_ошибки_перечислены_поимённо():
    и = главное(_синтетика())
    for e in и["модели"]["logreg"]["ошибки"]:
        assert {"label", "истина", "предсказано"} <= set(e)
