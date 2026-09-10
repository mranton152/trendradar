"""Полнота генерации кандидатов: предлагает ли конвейер нужные термины вообще.

    python -m validation.candidate_recall --index data/index/ai-smoke

Это метрика, которой у нас не было, и она важнее Precision@15. Скоринг умеет
ранжировать только то, что ему подали. Если генератор не предложил
`vision transformer` в принципе, никакая формула его не вытащит — тренд
потерян до начала расчёта.

Precision@15 отвечает «насколько хорошо мы упорядочили найденное».
Полнота отвечает «а нашли ли вообще». Вторая цифра решает, куда вкладывать
оставшееся время: в формулу или в генерацию.

Совпадение засчитывается мягко и намеренно. У зарождающегося тренда часто нет
устоявшегося названия — это следует из определения, — поэтому кластер
`diffusion image generation` с ключевыми словами denoising/diffusion считается
попаданием для эталонного `diffusion model`. Строгое сравнение строк здесь
меряло бы совпадение словарей, а не работу метода.
"""
import argparse
import json
from pathlib import Path

# Слова, которые есть почти у каждого термина домена. Совпадение по ним ничего
# не значит: без этого списка `contrastive learning` засчитывался за
# `deep learning`, а `graph neural network` за `convolutional neural network`,
# и полнота выходила 21% вместо честного нуля. Метрика, ошибающаяся в нашу
# пользу, хуже отсутствия метрики.
ОБЩИЕ = {
    "learning", "network", "networks", "model", "models", "neural", "deep",
    "machine", "artificial", "intelligence", "based", "using", "data",
    "method", "methods", "approach", "system", "systems", "algorithm",
    "algorithms", "training", "analysis",
}


def _слова(текст: str) -> set[str]:
    return {w for w in текст.lower().replace("-", " ").split() if len(w) > 2}


def _отличительные(текст: str) -> set[str]:
    """Слова, по которым термин вообще можно узнать."""
    слова = _слова(текст)
    особые = слова - ОБЩИЕ
    return особые or слова


def найти_кандидата(эталон: str, кандидаты: list[dict]) -> dict | None:
    """Первый кандидат, который можно считать этим трендом.

    Порядок проверок — от строгой к мягкой, чтобы точное совпадение
    не перебивалось случайным пересечением ключевых слов.
    """
    цель = эталон.lower()
    for c in кандидаты:
        if c["label"].lower() == цель:
            return c
    for c in кандидаты:
        if any((a or "").lower() == цель for a in (c.get("aliases") or [])):
            return c

    особые = _отличительные(эталон)
    if not особые:
        return None
    for c in кандидаты:
        поле = {w.lower() for w in (c.get("top_terms") or [])} | _слова(c["label"])
        поле |= {w for a in (c.get("aliases") or []) for w in _слова(a or "")}
        # все отличительные слова эталона должны найтись: у кластера может
        # не быть устоявшегося названия, но ключевые слова темы обязаны совпасть
        if особые <= поле:
            return c
    return None


def полнота_кандидатов(эталон: list[str], кандидаты: list[dict]) -> dict:
    найдено, пропущены, попадания = 0, [], {}
    for термин in эталон:
        c = найти_кандидата(термин, кандидаты)
        if c:
            найдено += 1
            попадания[термин] = {"cand_id": c["cand_id"], "label": c["label"],
                                 "kind": c["kind"], "n_docs": c.get("n_docs")}
        else:
            пропущены.append(термин)
    return {
        "всего": len(эталон),
        "найдено": найдено,
        "полнота": round(найдено / len(эталон), 3) if эталон else 0.0,
        "пропущены": пропущены,
        "попадания": попадания,
        "размер_пула": len(кандидаты),
    }


def main() -> None:
    from validation.reference import ЭТАЛОН_ИИ_2021

    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="каталог с candidates.parquet")
    args = ap.parse_args()

    import duckdb

    путь = Path(args.index) / "candidates.parquet"
    if not путь.exists():
        raise SystemExit(f"нет {путь} — стадия semantic ещё не отработала")

    строки = duckdb.connect().execute(
        "SELECT cand_id, kind, label, aliases, top_terms, n_docs FROM read_parquet(?)",
        [str(путь)]).fetchall()
    # fetchall, а не .df(): pandas отдаёт списки как numpy-массивы, а у них
    # проверка на истинность неоднозначна и падает на пустых
    кандидаты = [{"cand_id": r[0], "kind": r[1], "label": r[2],
                  "aliases": list(r[3] or []), "top_terms": list(r[4] or []),
                  "n_docs": r[5]} for r in строки]

    итог = полнота_кандидатов(ЭТАЛОН_ИИ_2021, кандидаты)

    print(f"\nПул кандидатов: {итог['размер_пула']}")
    print(f"Полнота по эталону: {итог['найдено']}/{итог['всего']} "
          f"({итог['полнота']:.0%})\n")
    if итог["попадания"]:
        print("нашлись:")
        for т, c in sorted(итог["попадания"].items()):
            print(f"  {т:<38} -> [{c['kind']}] {c['label'][:40]} ({c['n_docs']} док.)")
    if итог["пропущены"]:
        print("\nне предложены генератором вообще:")
        for т in итог["пропущены"]:
            print(f"  {т}")
    print()
    print(json.dumps({k: v for k, v in итог.items() if k != "попадания"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
