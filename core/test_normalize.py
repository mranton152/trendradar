from core.normalize import frequencies, peer_normalizer


def test_знаменатель_это_сумма_активности_пула():
    все = [{2020: 10, 2021: 20}, {2020: 30, 2021: 0}]
    assert peer_normalizer(все, [2020, 2021]) == {2020: 40.0, 2021: 20.0}


def test_пустой_год_не_делит_на_ноль():
    assert peer_normalizer([{2020: 0}], [2020, 2021]) == {2020: 1.0, 2021: 1.0}


def test_частота_на_миллион():
    norm = {2020: 100.0, 2021: 200.0}
    assert frequencies({2020: 1, 2021: 1}, norm, [2020, 2021]) == [10000.0, 5000.0]
