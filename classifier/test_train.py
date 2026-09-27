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
                     "pub_total_10y": (rng.randint(5, 80) if сигнал
                                       else rng.randint(500, 5000)),
                     "pub_last_3y_share": (rng.uniform(0.6, 0.95) if сигнал
                                           else rng.uniform(0.2, 0.4)),
                     "pub_growth": rng.uniform(0.3, 1.0) if сигнал else rng.uniform(-0.1, 0.1),
                     "pub_accel": rng.uniform(0.0, 0.5), "pub_burst": rng.uniform(0.8, 3.0),
                     "pub_age": rng.randint(0, 3) if сигнал else rng.randint(8, 25),
                     "pub_countries": rng.randint(2, 15) if сигнал else rng.randint(40, 120),
                     "pub_company_share": rng.uniform(0, 0.3),
                     "github_repos": rng.randint(0, 50) if сигнал else rng.randint(1000, 90000),
                     "github_stars_max": rng.randint(0, 500),
                     "github_new_share": (rng.uniform(0.5, 1.0) if сигнал
                                          else rng.uniform(0, 0.2)),
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


def test_лес_и_эмбеддинги_голосует_и_объясняется_лесом():
    import numpy as np

    from classifier.train import ЛесИЭмбеддинги
    X, y = матрица(_синтетика())
    шум = np.random.default_rng(0).normal(size=(len(y), 8))
    m = ЛесИЭмбеддинги().fit(np.hstack([X, шум]), y)
    p = m.predict_proba(np.hstack([X, шум]))
    assert p.shape == (len(y), 2) and np.allclose(p.sum(axis=1), 1)
    assert len(m.feature_importances_) == len(ОПИСАНИЯ)


def test_главное_с_эмбеддингами_добавляет_модель():
    import numpy as np
    строки = _синтетика()
    и = главное(строки, np.random.default_rng(0).normal(size=(len(строки), 8)), разбиений=1)
    assert "forest_e5" in и["модели"]
    assert и["модели"]["forest_e5"]["разбиений"] == 1


def test_стиль_запроса_не_выдаёт_класс():
    """Охрана от утечки: кодируем query_en, потому что по его длине и символам
    класс не угадывается. Если снимок поменяется и это перестанет быть так,
    эмбеддинги начнут учить стиль разметки - тест должен упасть."""
    import json
    from pathlib import Path

    import numpy as np
    import pytest
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    снимок = Path("classifier/features_v1.json")
    if not снимок.exists():
        pytest.skip("нет снимка признаков")
    строки = json.loads(снимок.read_text(encoding="utf-8"))

    def стиль(t):
        return [len(t), len(t.split()), t.count("("),
                sum(c.isascii() and c.isalpha() for c in t) / max(len(t), 1)]

    y = np.array([int(bool(r["is_weak_signal"])) for r in строки])
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    def acc(поле):
        X = np.array([стиль(r[поле] or "") for r in строки])
        return cross_val_score(LogisticRegression(max_iter=2000), X, y, cv=cv).mean()
    assert acc("query_en") < 0.65     # около монетки - кодировать можно
    assert acc("label") > 0.9         # стиль разметки - кодировать нельзя
