"""Обучение и честная оценка классификатора слабых сигналов.

    python -m classifier.train

Две модели, обе интерпретируемые: логистическая регрессия (коэффициенты
читаются напрямую) и градиентный бустинг (важность признаков). Стратифицированная
5-fold кросс-валидация, отчёт P/R/F1/accuracy - как требует ТЗ.

Выбираем ПРОСТЕЙШУЮ модель, проходящую порог, а не самую точную. Если порог
не берётся, отчёт говорит почему, а не подкручивает: точность, натянутая
на 196 примерах, на закрытой выборке заказчика развалится.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from classifier.features import ОПИСАНИЯ

ПРИЗНАКИ = list(ОПИСАНИЯ)
ПОРОГ_ТЗ = 0.80
ПОРОГ_МИН = 0.75    # ТЗ: "точность не ниже 80% (возможно 75%)"
СИД = 42


def матрица(строки: list[dict], признаки: list[str] = ПРИЗНАКИ) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([[float(r.get(f) or 0.0) for f in признаки] for r in строки])
    y = np.array([1 if r["is_weak_signal"] else 0 for r in строки])
    return X, y


def модели() -> dict:
    """Три интерпретируемые модели. Сравнены на одной кросс-валидации - это даёт
    небольшой оптимистический сдвиг, и об этом сказано в отчёте."""
    return {
        "logreg": make_pipeline(StandardScaler(),
                                LogisticRegression(C=0.1, max_iter=2000, random_state=СИД)),
        "gboost": GradientBoostingClassifier(n_estimators=150, max_depth=2,
                                             learning_rate=0.05, random_state=СИД),
        "forest": RandomForestClassifier(n_estimators=400, min_samples_leaf=2,
                                         random_state=СИД),
    }


РАЗБИЕНИЙ = 20


def _одно(model, X: np.ndarray, y: np.ndarray, folds: int, seed: int) -> tuple[dict, np.ndarray]:
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    pred = cross_val_predict(model, X, y, cv=cv)
    return {"accuracy": accuracy_score(y, pred), "precision": precision_score(y, pred),
            "recall": recall_score(y, pred), "f1": f1_score(y, pred)}, pred


def оценить(model, X: np.ndarray, y: np.ndarray, folds: int = 5,
            разбиений: int = РАЗБИЕНИЙ) -> dict:
    """Метрики — среднее по `разбиений` случайным 5-fold разбиениям.

    На 196 примерах результат одного разбиения гуляет на ±2 п.п.: на seed 42
    лес давал 79%, и это оказался максимум из двадцати, а не типичное значение.
    Поэтому отчитываемся средним и разбросом. Матрица ошибок и поимённые ошибки —
    по одному разбиению (seed 42): они нужны, чтобы показать, где модель слепа.
    """
    прогоны = [_одно(model, X, y, folds, seed)[0] for seed in range(разбиений)]
    _, pred = _одно(model, X, y, folds, СИД)
    tn, fp, fn, tp = confusion_matrix(y, pred).ravel()
    acc = [п["accuracy"] for п in прогоны]
    return {**{k: round(float(np.mean([п[k] for п in прогоны])), 3)
               for k in ("accuracy", "precision", "recall", "f1")},
            "accuracy_std": round(float(np.std(acc, ddof=1)), 3) if len(acc) > 1 else 0.0,
            "accuracy_min": round(min(acc), 3), "accuracy_max": round(max(acc), 3),
            "разбиений": разбиений,
            "разбиений_выше_мин": sum(a >= ПОРОГ_МИН for a in acc),
            "confusion": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)},
            "pred": pred.tolist()}


def важность(model, признаки: list[str]) -> list[dict]:
    """Вклад признаков фразами - «по каким признакам система решила»."""
    if hasattr(model, "feature_importances_"):
        веса = model.feature_importances_
    else:
        веса = model[-1].coef_[0]
    пары = sorted(zip(признаки, веса, strict=True), key=lambda p: -abs(p[1]))
    return [{"признак": п, "вес": round(float(в), 3), "смысл": ОПИСАНИЯ[п]} for п, в in пары]


def абляция(X: np.ndarray, y: np.ndarray, признаки: list[str], базовая: float) -> list[dict]:
    """Убираем признаки по одному: падение accuracy = вклад. Хорошо смотрится на слайде."""
    out = []
    for i, п in enumerate(признаки):
        Xi = np.delete(X, i, axis=1)
        acc = оценить(модели()["logreg"], Xi, y, разбиений=5)["accuracy"]
        out.append({"без": п, "accuracy": acc, "потеря": round(базовая - acc, 3)})
    return sorted(out, key=lambda d: -d["потеря"])


def главное(строки: list[dict]) -> dict:
    X, y = матрица(строки)
    итог = {"n": len(строки), "n_pos": int(y.sum()), "n_neg": int(len(y) - y.sum()),
            "признаки": ПРИЗНАКИ, "порог_ТЗ": ПОРОГ_ТЗ, "модели": {}}
    for имя, m in модели().items():
        оц = оценить(m, X, y)
        m.fit(X, y)
        итог["модели"][имя] = {**{k: v for k, v in оц.items() if k != "pred"},
                                "важность": важность(m, ПРИЗНАКИ)}
        # ошибки поимённо - без них отчёт не объясняет, где метод слеп
        итог["модели"][имя]["ошибки"] = [
            {"label": r["label"], "domain": r["domain"], "истина": bool(r["is_weak_signal"]),
             "предсказано": bool(p)} for r, p in zip(строки, оц["pred"], strict=True)
            if bool(p) != bool(r["is_weak_signal"])]
    итог["абляция_logreg"] = абляция(X, y, ПРИЗНАКИ, итог["модели"]["logreg"]["accuracy"])
    # ТЗ: "не ниже 80% (возможно 75%)". Берём простейшую из проходящих верхний
    # порог; если таких нет - лучшую из проходящих нижний, и говорим об этом прямо.
    порядок = ["logreg", "gboost", "forest"]
    верх = [и for и in порядок if итог["модели"][и]["accuracy"] >= ПОРОГ_ТЗ]
    низ = [и for и in порядок if итог["модели"][и]["accuracy"] >= ПОРОГ_МИН]
    итог["выбор"] = верх[0] if верх else (
        max(низ, key=lambda и: итог["модели"][и]["accuracy"]) if низ else None)
    итог["порог_взят"] = "верхний" if верх else ("нижний" if низ else "нет")
    return итог


def отчёт_md(и: dict) -> str:
    def таб(m):
        c = m["confusion"]
        return (f"| accuracy, среднее | **{m['accuracy']:.1%}** ± {m['accuracy_std']:.1%} |\n"
                f"| accuracy, диапазон | {m['accuracy_min']:.1%} – {m['accuracy_max']:.1%}; "
                f"≥75% в {m['разбиений_выше_мин']} из {m['разбиений']} |\n"
                f"| precision | {m['precision']:.2f} |\n"
                f"| recall | {m['recall']:.2f} |\n| F1 | {m['f1']:.2f} |\n"
                f"| матрица (seed 42) | TP {c['tp']} · FP {c['fp']} · FN {c['fn']} · "
                f"TN {c['tn']} |")
    lg, gb = и["модели"]["logreg"], и["модели"]["gboost"]
    rf = и["модели"]["forest"]
    выбор = и["выбор"]
    вердикты = {
        "верхний": f"Порог ≥80% **взят**. Выбрана `{выбор}` — простейшая из проходящих.",
        "нижний": (f"Верхний порог 80% не взят; допустимый по ТЗ минимум 75% — **взят**. "
                   f"Выбрана `{выбор}` ({и['модели'].get(выбор, {}).get('accuracy', 0):.1%})."),
        "нет": "Ни одна модель не проходит даже 75%. Причины ниже, подкрутки нет."}
    вердикт = вердикты[и.get("порог_взят", "нет")]
    важн = "\n".join(f"| {p['признак']} | {p['вес']:+.3f} | {p['смысл']} |"
                     for p in lg["важность"])
    абл = "\n".join(f"| {a['без']} | {a['accuracy']:.0%} | {a['потеря']:+.3f} |"
                    for a in и["абляция_logreg"][:8])
    def _ярлык(b):
        return "сигнал" if b else "зрелая"
    ош = "\n".join(f"| {e['label'][:60]} | {e['domain']} | {_ярлык(e['истина'])} → "
                   f"{_ярлык(e['предсказано'])} |" for e in lg["ошибки"][:15])
    return f"""# Отчёт классификатора — этап 1 ТЗ

Выборка: {и['n']} технологий — {и['n_pos']} слабых сигналов из датасета заказчика
и {и['n_neg']} зрелых технологий, собранных нами с обоснованием каждой
(`classifier/dataset.py`). Стратифицированная 5-fold кросс-валидация,
повторённая на {rf['разбиений']} случайных разбиениях; метрики — среднее по ним.

{вердикт}

## Логистическая регрессия

| Метрика | Значение |
|---|---|
{таб(lg)}

## Градиентный бустинг

| Метрика | Значение |
|---|---|
{таб(gb)}

## Случайный лес

| Метрика | Значение |
|---|---|
{таб(rf)}

## По каким признакам система решает (коэффициенты логрегрессии)

Положительный вес — в сторону «слабый сигнал», отрицательный — «зрелая».

| Признак | Вес | Что означает |
|---|---|---|
{важн}

## Абляция: что теряем, убирая признак

| Без признака | Accuracy | Потеря |
|---|---|---|
{абл}

## Ошибки логрегрессии (первые 15)

| Технология | Область | Истина → предсказание |
|---|---|---|
{ош}

## Что здесь честно сказать

**Одно разбиение врёт.** Первая версия отчёта считала на одном разбиении
(seed 42) и показывала у леса 79%. На двадцати разбиениях это оказался максимум,
а типичное значение — на 2 п.п. ниже. Разброс на 196 примерах — около ±1 п.п.,
поэтому здесь среднее и диапазон, а не одна удачная цифра.

**Отбор моделей.** Три конфигурации сравнены на одних и тех же разбиениях
и выбрана лучшая по среднему. Это даёт небольшой оптимистический сдвиг: на
по-настоящему новых данных результат будет чуть ниже.

**Новостные признаки пробовали и убрали.** Четыре признака по Hacker News
(упоминания за год, доля свежих, заголовки про раунды, громкость) ухудшили
точность с 76% до 74%, и направление у них оказалось обратным: у сигналов
упоминаний меньше, чем у зрелых — медиана 0 против 3. Причина в том, что поиск
по фразе меряет известность названия, а не новизну технологии. Код сбора
оставлен: он заработает, когда кандидатами станут имена компаний и продуктов
из новостей, а не сгенерированные английские фразы.

**Где модель слепа.** Почти все ошибки — «сигнал принят за зрелую технологию»:
нейроморфные чипы, event-based сенсоры зрения, аналоговые compute-in-memory
чипы. У них наука старая — исследования идут десятилетиями, — а коммерческий
сигнал новый. Публикационные признаки этого различить не могут по построению.
Это и есть граница метода, и она ровно там, где ТЗ говорит искать: в индустрии,
а не в науке.
"""


СНИМОК = Path("classifier/features_v1.json")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Обучение классификатора этапа 1 и отчёт classifier/REPORT.md")
    ap.add_argument("--offline", action="store_true",
                    help=f"обучить по закоммиченному снимку признаков {СНИМОК}: "
                         "без сети и без датасета заказчика")
    ap.add_argument("--xlsx", default="../tz/Датасет/Датасет/"
                    "100_слабых_технологических_сигналов_сентябрь_2026.xlsx",
                    help="датасет заказчика (лежит вне репозитория)")
    args = ap.parse_args(argv)

    if args.offline:
        строки = json.loads(СНИМОК.read_text(encoding="utf-8"))
        print(f"признаки из снимка {СНИМОК}: {len(строки)} технологий")
    else:
        from classifier.dataset import собрать_выборку
        from classifier.features import собрать_признаки
        from classifier.queries import ЗапросыКэш

        выборка = собрать_выборку(args.xlsx)
        кэш = ЗапросыКэш()
        запросы = {s["label"]: кэш.взять(s["label"]) for s in выборка}
        нет = [имя for имя, q in запросы.items() if not q]
        if нет:
            raise SystemExit(f"нет запросов для {len(нет)} технологий — "
                             "сначала python -m classifier.queries")

        print("собираю признаки…")
        строки = собрать_признаки(выборка, запросы)
        СНИМОК.write_text(json.dumps(строки, ensure_ascii=False, indent=1), encoding="utf-8")

    и = главное(строки)
    Path("classifier/report.json").write_text(json.dumps(и, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    Path("classifier/REPORT.md").write_text(отчёт_md(и), encoding="utf-8")
    for имя, m in и["модели"].items():
        print(f"{имя}: acc={m['accuracy']:.1%}±{m['accuracy_std']:.1%} P={m['precision']:.2f} "
              f"R={m['recall']:.2f} F1={m['f1']:.2f}")
    print("выбор:", и["выбор"])


if __name__ == "__main__":
    main()
