from core.score import emergence_scores, стадия, уверенность


def _строка(age, growth, accel, burst, maturity, countries):
    return {"label": f"t{age}-{growth}", "countries": countries,
            "c": {"age": age, "growth": growth, "accel": accel,
                  "burst": burst, "maturity": maturity}}


def test_молодой_и_растущий_обгоняет_старый_и_ровный():
    rows = emergence_scores([
        _строка(2, 1.5, 0.9, 5.0, 10.0, 40),     # молодой, разгоняется
        _строка(8, 0.1, 0.0, 1.0, 900.0, 40),    # старый мейнстрим
    ])
    assert rows[0]["c"]["age"] == 2
    assert rows[0]["es"] > rows[1]["es"]


def test_штраф_за_зрелость_понижает_мейнстрим():
    rows = emergence_scores([
        _строка(3, 1.0, 0.5, 2.0, 1.0, 30),
        _строка(3, 1.0, 0.5, 2.0, 5000.0, 30),
    ])
    зрелый = next(r for r in rows if r["c"]["maturity"] == 5000.0)
    молодой = next(r for r in rows if r["c"]["maturity"] == 1.0)
    assert молодой["es"] > зрелый["es"]


def test_стадия_выводится_из_возраста_и_зрелости():
    assert стадия({"age": 2}, 0.3) == "emerging"
    assert стадия({"age": 5}, 0.3) == "early_growth"
    assert стадия({"age": 5}, 0.95) == "scaling"


def test_мало_данных_значит_низкая_уверенность():
    assert уверенность({"counts_recent": 30}, 6) == "low"
    assert уверенность({"counts_recent": 500}, 40) == "high"
