import numpy as np

from core.dedup import dedup, mmr, лемма


def test_множественное_число_схлопывается_в_единственное():
    assert лемма("networks") == "network"
    assert лемма("studies") == "study"
    assert лемма("analysis") == "analysis"     # не 'analysi'
    assert лемма("bus") == "bus"


def test_дубли_по_числу_схлопываются():
    """В бэктесте это стоило четырёх слотов из пятнадцати.

    'generative adversarial network(s)' и 'convolutional neural network(s)'
    занимали по два места каждый: жаккар по токенам даёт 0.5 при пороге 0.6.
    """
    rows = [{"label": "generative adversarial networks", "es": 0.56},
            {"label": "generative adversarial network", "es": 0.51},
            {"label": "federated learning", "es": 0.40}]
    итог = dedup(rows)
    assert len(итог) == 2
    assert итог[0]["label"] == "generative adversarial networks"
    assert "generative adversarial network" in итог[0]["aliases"]


def test_вложенные_варианты_схлопываются():
    rows = [{"label": "explainable machine learning", "es": 0.80},
            {"label": "explainable machine", "es": 0.47}]
    assert len(dedup(rows)) == 1


def test_mmr_не_берёт_две_близкие_темы_подряд():
    emb = {0: np.array([1.0, 0.0]), 1: np.array([0.99, 0.14]),
           2: np.array([0.0, 1.0])}
    rows = [{"label": "a", "es": 0.9, "emb_row": 0},
            {"label": "b", "es": 0.85, "emb_row": 1},
            {"label": "c", "es": 0.5, "emb_row": 2}]
    assert [r["label"] for r in mmr(rows, emb, k=2)] == ["a", "c"]
