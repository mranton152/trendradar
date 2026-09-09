"""Замер качества скоринга на фиксированном пуле терминов.

    python -m validation.scoring_probe --as-of 2026
    python -m validation.scoring_probe --as-of 2021    # бэктест

Отвечает ровно на один вопрос: если кандидаты заданы вручную и правильные,
ставит ли скоринг зарождающееся выше мейнстрима. Генерацию кандидатов это
не проверяет — она в зоне стадии semantic и меряется отдельно.

Ряды кэшируются в validation/probe_cache.json, поэтому повторный прогон
идёт офлайн и воспроизводим. Кэш версионируется: это доказательная база.
"""
import argparse
import json
from pathlib import Path

import httpx

from core.components import components
from core.filters import ПОРОГИ, причина_отказа
from core.normalize import peer_normalizer
from core.score import emergence_scores
from validation.pool import ФОН
from validation.reference import АНТИЭТАЛОН_ИИ_2021, ЭТАЛОН_ИИ_2021

КОНЦЕПТ_ИИ = "concepts.id:C154945302"
КЭШ = Path("validation/probe_cache.json")
ПОЧТА = "flesha98@gmail.com"


def загрузить_кэш() -> dict:
    return json.loads(КЭШ.read_text()) if КЭШ.exists() else {}


def страны(термин: str, as_of: int, кэш: dict) -> int:
    """Сколько стран публикует по термину за три года до среза.

    Тянем по-настоящему, а не подставляем константу: именно география отличает
    взрывной международный рост от пакетной заливки метаданных, и подсовывать
    сюда заглушку значит мерить не то.
    """
    ключ = f"страны:{термин}:{as_of}"
    if ключ in кэш:
        return int(кэш[ключ])
    r = httpx.get("https://api.openalex.org/works", timeout=60, params={
        "filter": f'{КОНЦЕПТ_ИИ},title_and_abstract.search:"{термин}",type:article,'
                  f"publication_year:{as_of - 2}-{as_of}",
        "group_by": "authorships.institutions.country_code",
        "per-page": 200, "mailto": ПОЧТА})
    r.raise_for_status()
    n = len([g for g in (r.json().get("group_by") or []) if g.get("count", 0) >= 2])
    кэш[ключ] = n
    return n


def ряд(термин: str, кэш: dict) -> dict[int, int]:
    """Годовая гистограмма термина внутри домена ИИ — одним запросом."""
    if термин in кэш:
        return {int(y): n for y, n in кэш[термин].items()}
    r = httpx.get("https://api.openalex.org/works", timeout=60, params={
        "filter": f'{КОНЦЕПТ_ИИ},title_and_abstract.search:"{термин}",type:article',
        "group_by": "publication_year", "mailto": ПОЧТА})
    r.raise_for_status()
    out = {}
    for g in r.json().get("group_by") or []:
        if str(g["key"]).isdigit() and 1990 <= int(g["key"]) <= 2026:
            out[int(g["key"])] = g["count"]
    кэш[термин] = out
    return out


def прогнать(as_of: int) -> dict:
    кэш = загрузить_кэш()
    группы = {"эталон": ЭТАЛОН_ИИ_2021, "мейнстрим": АНТИЭТАЛОН_ИИ_2021, "фон": ФОН}
    к_группе = {т: г for г, тт in группы.items() for т in тт}

    ряды = {т: ряд(т, кэш) for тт in группы.values() for т in тт}
    ряды = {т: {y: n for y, n in с.items() if y <= as_of} for т, с in ряды.items() if с}
    КЭШ.write_text(json.dumps(кэш, ensure_ascii=False, indent=1, sort_keys=True))

    окно = list(range(as_of - 6, as_of + 1))
    norm = peer_normalizer(list(ряды.values()), окно)

    строки, отсеяны = [], {}
    for термин, counts in ряды.items():
        comp = components(counts, norm, as_of)
        n_стран = страны(термин, as_of, кэш)
        причина = причина_отказа(comp, n_стран)
        if причина:
            отсеяны[термин] = f"{причина} (стран: {n_стран})"
            continue
        строки.append({"label": термин, "c": comp, "countries": n_стран,
                       "группа": к_группе[термин]})
    КЭШ.write_text(json.dumps(кэш, ensure_ascii=False, indent=1, sort_keys=True))

    строки = emergence_scores(строки)
    строки = [r for r in строки if r["maturity_pct"] < ПОРОГИ["MAX_MATURITY_PCT"]]

    топ15 = строки[:15]
    состав = {г: sum(1 for r in топ15 if r["группа"] == г) for г in группы}
    потеряно = {т: п for т, п in отсеяны.items() if к_группе[т] == "эталон"}

    return {"as_of": as_of, "строки": строки, "топ15": топ15,
            "состав_топ15": состав, "отсеяны": отсеяны,
            "эталон_потерян": потеряно}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", type=int, default=2026)
    args = ap.parse_args()
    итог = прогнать(args.as_of)

    ЗНАЧКИ = {"эталон": "✓", "мейнстрим": "✗", "фон": "·"}
    print(f"\nПул из {len(итог['строки']) + len(итог['отсеяны'])} терминов, "
          f"срез {итог['as_of']}\n")
    print(f"{'#':>3} {'':2}{'термин':<42}{'ES':>7}{'взлёт':>7}{'публ':>8}{'стран':>7}")
    print("-" * 78)
    for i, r in enumerate(итог["топ15"], 1):
        print(f"{i:>3} {ЗНАЧКИ[r['группа']]:2}{r['label'][:42]:<42}"
              f"{r['es']:>7.3f}{str(r['c']['takeoff_year']):>7}"
              f"{r['c']['counts_recent']:>8}{r['countries']:>7}")

    с = итог["состав_топ15"]
    print(f"\nсостав ТОП-15: эталон {с['эталон']}, мейнстрим {с['мейнстрим']}, "
          f"фон {с['фон']}")
    if итог["эталон_потерян"]:
        print("\nэталонные термины, отсеянные фильтрами:")
        for т, п in sorted(итог["эталон_потерян"].items()):
            print(f"  {т:<44} {п}")


if __name__ == "__main__":
    main()
