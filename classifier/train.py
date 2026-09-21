"""Обучение и честная оценка классификатора слабых сигналов.

    python -m classifier.train

Две модели, обе интерпретируемые: логистическая регрессия (коэффициенты
читаются напрямую) и градиентный бустинг (важность признаков). Стратифицированная
5-fold кросс-валидация, отчёт P/R/F1/accuracy - как требует ТЗ.

Выбираем ПРОСТЕЙШУЮ модель, проходящую порог, а не самую точную. Если порог
не берётся, отчёт говорит почему, а не подкручивает: точность, натянутая
на 196 примерах, на закрытой выборке заказчика развалится.
"""
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
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
СИД = 42


def матрица(строки: list[dict], признаки: list[str] = ПРИЗНАКИ) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([[float(r.get(f) or 0.0) for f in признаки] for r in строки])
    y = np.array([1 if r["is_weak_signal"] else 0 for r in строки])
    return X, y


def модели() -> dict:
    return {
        "logreg": make_pipeline(StandardScaler(),
                                LogisticRegression(C=1.0, max_iter=2000, random_state=СИД)),
        "gboost": GradientBoostingClassifier(n_estimators=150, max_depth=2,
                                             learning_rate=0.05, random_state=СИД),
    }


def оценить(model, X: np.ndarray, y: np.ndarray, folds: int = 5) -> dict:
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=СИД)
    pred = cross_val_predict(model, X, y, cv=cv)
    tn, fp, fn, tp = confusion_matrix(y, pred).ravel()
    return {"accuracy": round(accuracy_score(y, pred), 3),
            "precision": round(precision_score(y, pred), 3),
            "recall": round(recall_score(y, pred), 3),
            "f1": round(f1_score(y, pred), 3),
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
        acc = оценить(модели()["logreg"], Xi, y)["accuracy"]
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
    проходят = [и for и, m in итог["модели"].items() if m["accuracy"] >= ПОРОГ_ТЗ]
    итог["выбор"] = ("logreg" if "logreg" in проходят else проходят[0]) if проходят else None
    return итог


def отчёт_md(и: dict) -> str:
    def таб(m):
        c = m["confusion"]
        return (f"| accuracy | **{m['accuracy']:.0%}** |\n| precision | {m['precision']:.2f} |\n"
                f"| recall | {m['recall']:.2f} |\n| F1 | {m['f1']:.2f} |\n"
                f"| матрица | TP {c['tp']} · FP {c['fp']} · FN {c['fn']} · TN {c['tn']} |")
    lg, gb = и["модели"]["logreg"], и["модели"]["gboost"]
    выбор = и["выбор"]
    вердикт = (f"Порог ТЗ ≥{и['порог_ТЗ']:.0%}: **{'взят' if выбор else 'НЕ взят'}**. "
               + (f"Выбрана `{выбор}` — простейшая из проходящих." if выбор else
                  "Ни одна модель не проходит; причины ниже, подкрутки нет."))
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
(`classifier/dataset.py`). Стратифицированная 5-fold кросс-валидация, seed 42.

{вердикт}

## Логистическая регрессия

| Метрика | Значение |
|---|---|
{таб(lg)}

## Градиентный бустинг

| Метрика | Значение |
|---|---|
{таб(gb)}

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

Признаки версии 1 — только публикации, GitHub и Hugging Face. Новостных
признаков (упоминания по месяцам, раунды, сайты) пока нет — они добавятся
отдельными колонками, и этот отчёт покажет прирост от них. Датасет заказчика
описывает сигналы через новости, поэтому ожидаемо, что публикационные признаки
недобирают именно там, где сигнал живёт только в индустрии.
"""


def main() -> None:
    from classifier.dataset import собрать_выборку
    from classifier.features import собрать_признаки
    from classifier.queries import ЗапросыКэш

    xlsx = "../tz/Датасет/Датасет/100_слабых_технологических_сигналов_сентябрь_2026.xlsx"
    выборка = собрать_выборку(xlsx)
    кэш = ЗапросыКэш()
    запросы = {s["label"]: кэш.взять(s["label"]) for s in выборка}
    нет = [имя for имя, q in запросы.items() if not q]
    if нет:
        raise SystemExit(f"нет запросов для {len(нет)} технологий — "
                         "сначала python -m classifier.queries")

    print("собираю признаки…")
    строки = собрать_признаки(выборка, запросы)
    Path("classifier/features_v1.json").write_text(
        json.dumps(строки, ensure_ascii=False, indent=1), encoding="utf-8")

    и = главное(строки)
    Path("classifier/report.json").write_text(json.dumps(и, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    Path("classifier/REPORT.md").write_text(отчёт_md(и), encoding="utf-8")
    for имя, m in и["модели"].items():
        print(f"{имя}: acc={m['accuracy']:.0%} P={m['precision']:.2f} "
              f"R={m['recall']:.2f} F1={m['f1']:.2f}")
    print("выбор:", и["выбор"])


if __name__ == "__main__":
    main()
