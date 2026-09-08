from validation.metrics import lead_time, precision_at_k, рост_после_среза


def test_precision_считает_совпадения_по_вхождению():
    """'vision transformer' засчитывается эталонному 'transformer':
    это тот же тренд, названный подробнее."""
    найдено = ["vision transformer", "fraud detection", "diffusion models"]
    эталон = ["transformer", "diffusion model"]
    assert precision_at_k(найдено, эталон, k=3) == 2 / 3


def test_precision_учитывает_только_верхушку():
    найдено = ["шум", "шум", "transformer"]
    assert precision_at_k(найдено, ["transformer"], k=2) == 0.0


def test_рост_после_среза():
    """(300+1)/(100+1): сглаживание +1 нужно, чтобы не делить на ноль,
    и на заметных числах почти не искажает результат."""
    counts = {2021: 100, 2022: 200, 2023: 300}
    assert рост_после_среза(counts, as_of=2021, до_года=2023) == 2.98


def test_срез_с_нулём_не_ломает_деление():
    """Тренд, которого на срезе ещё не было, — самый интересный случай,
    и он не должен ронять расчёт."""
    assert рост_после_среза({2022: 50}, as_of=2021, до_года=2023) == 51.0


def test_затухший_тренд_даёт_рост_около_единицы():
    counts = {2021: 100, 2022: 90, 2023: 80}
    assert рост_после_среза(counts, as_of=2021, до_года=2023) < 1.0


def test_lead_time_это_расстояние_до_пика():
    assert lead_time(2019, {2019: 10, 2020: 50, 2023: 400, 2024: 100}) == 4


def test_без_года_взлёта_lead_time_не_считается():
    assert lead_time(None, {2020: 5}) is None
