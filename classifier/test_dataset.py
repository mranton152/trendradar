import collections

import pytest

from classifier.dataset import ОБЛАСТИ, ОТРИЦАТЕЛЬНЫЕ, загрузить_положительные, собрать_выборку

XLSX = "../tz/Датасет/Датасет/100_слабых_технологических_сигналов_сентябрь_2026.xlsx"


def test_положительных_ровно_сто():
    п = загрузить_положительные(XLSX)
    assert len(п) == 100
    assert all(x["is_weak_signal"] for x in п)
    assert all(x["label"] and x["domain"] in ОБЛАСТИ for x in п)
    assert all(3 <= x["dataset_score"] <= 7 for x in п)


def test_отрицательные_покрывают_те_же_области_поровну():
    """Иначе классификатор выучит область, а не признаки зрелости."""
    по_областям = collections.Counter(x["domain"] for x in ОТРИЦАТЕЛЬНЫЕ)
    assert set(по_областям) == set(ОБЛАСТИ)
    assert max(по_областям.values()) - min(по_областям.values()) <= 2
    assert len(ОТРИЦАТЕЛЬНЫЕ) >= 90


def test_у_каждого_отрицательного_есть_обоснование_зрелости():
    """Отрицательный без обоснования - это мнение, а не разметка. Обоснование
    пойдёт на слайд «как мы отделяем зрелое»."""
    for x in ОТРИЦАТЕЛЬНЫЕ:
        assert len(x["why_mature"]) > 25, x["label"]
        assert x["is_weak_signal"] is False


def test_названия_не_пересекаются_с_положительными():
    п = {x["label"].lower() for x in загрузить_положительные(XLSX)}
    о = {x["label"].lower() for x in ОТРИЦАТЕЛЬНЫЕ}
    assert not (п & о)


def test_выборка_сбалансирована_и_помечена():
    в = собрать_выборку(XLSX)
    метки = collections.Counter(x["is_weak_signal"] for x in в)
    assert metки_ok(метки)
    assert all("cand_id" in x for x in в)


def metки_ok(c):
    return c[True] == 100 and c[False] >= 90


@pytest.mark.parametrize("поле", ["label", "domain", "is_weak_signal", "cand_id", "why"])
def test_общие_поля_есть_у_всех(поле):
    for x in собрать_выборку(XLSX):
        assert поле in x, x.get("label")
