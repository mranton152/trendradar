"""Живой скоринг: корпус за месяцы, без эмбеддингов, за секунды."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from contracts.schemas import CAND_DOCS, CANDIDATES, WORKS
from core.live import (
    components_monthly,
    domain_spread,
    month_counts,
    построить_live,
    причина_отказа_live,
)

ДОМЕНЫ = ["techcrunch.com", "siliconangle.com", "arxiv.org", "github.com",
          "venturebeat.com", "theregister.com"]


def _док(doc_id, month, домен, trust="trusted", source_type="news"):
    return {"doc_id": doc_id, "source": "rss", "doc_type": "article", "title": doc_id,
            "abstract": None, "year": int(month[:4]), "date": f"{month}-15",
            "lang": "en", "doi": None, "url": f"https://{домен}/{doc_id}",
            "cited_by": None, "countries": None, "institutions": None,
            "authors": None, "concepts": None, "domain": "live-test",
            "harvested_at": "2026-09-17", "source_type": source_type,
            "trust_level": trust, "summary_ru": None, "summary_model": None}


@pytest.fixture
def живой(tmp_path):
    """Три кандидата: разгоняющийся, ровный старый, один домен-пресс-релизы."""
    ряды = {
        "c:agent-iam":  {"2025-01": 1, "2025-04": 2, "2025-08": 3, "2025-11": 5,
                         "2026-02": 9, "2026-05": 14, "2026-08": 22},
        "c:cloud":      {m: 6 for m in ("2024-10", "2025-01", "2025-04", "2025-07",
                                        "2025-10", "2026-01", "2026-04", "2026-07")},
        "c:hype-corp":  {"2026-06": 12, "2026-07": 15, "2026-08": 20},
        # фон, чтобы перцентили не вырождались: в живом пуле их будет десятки
        "c:bg-a": {"2025-03": 3, "2025-09": 4, "2026-02": 4, "2026-07": 5},
        "c:bg-b": {"2025-06": 5, "2025-12": 4, "2026-04": 6, "2026-08": 5},
        "c:bg-c": {"2025-01": 4, "2025-07": 5, "2026-01": 3, "2026-06": 4},
    }
    works, links, n = [], [], 0
    for cid, ряд in ряды.items():
        for m, k in ряд.items():
            for _ in range(k):
                домен = "prnewswire.com" if cid == "c:hype-corp" else ДОМЕНЫ[n % len(ДОМЕНЫ)]
                trust = "indicator" if cid == "c:hype-corp" else "trusted"
                d = _док(f"d{n}", m, домен, trust,
                         "press_release" if cid == "c:hype-corp" else "news")
                works.append(d)
                links.append({"cand_id": cid, "doc_id": d["doc_id"], "weight": 1.0})
                n += 1
    кандидаты = [{"cand_id": c, "kind": "term", "label": c[2:], "aliases": [], "top_terms": [],
                  "emb_row": None, "n_docs": sum(r.values()), "domain": "live-test"}
                 for c, r in ряды.items()]
    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), tmp_path / "works.parquet")
    pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS), tmp_path / "cand_docs.parquet")
    pq.write_table(pa.Table.from_pylist(кандидаты, schema=CANDIDATES),
                   tmp_path / "candidates.parquet")
    return tmp_path


def test_месячные_ряды_считаются_по_дате(живой):
    ряды = month_counts(живой, живой / "works.parquet")
    assert ряды["c:agent-iam"]["2026-08"] == 22
    assert ряды["c:agent-iam"]["2025-01"] == 1


def test_распространение_это_разные_домены(живой):
    """У новостей нет стран. Тема, о которой пишет один сайт, - не тренд."""
    д = domain_spread(живой, живой / "works.parquet")
    assert д["c:agent-iam"] == 6
    assert д["c:hype-corp"] == 1


def test_компоненты_на_месяцах_различают_разгон_и_плато():
    норма = {m: 1000.0 for m in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08")}
    # хоккейная клюшка, а не чистая экспонента: у экспоненты на лог-шкале
    # ускорение по построению ноль - это уже ловил тест индексного режима
    разгон = {"2026-03": 2, "2026-04": 2, "2026-05": 3, "2026-06": 3, "2026-07": 9, "2026-08": 22}
    плато = {m: 10 for m in норма}
    a = components_monthly(разгон, норма, as_of="2026-08", window=6)
    b = components_monthly(плато, норма, as_of="2026-08", window=6)
    assert a["growth"] > b["growth"]
    assert a["accel"] > b["accel"]
    assert a["takeoff_year"] == 2026


def test_плато_это_старое_и_плоское_а_не_самое_частое():
    """В живом пуле из пяти тем «самый частый» - это и есть зарождающийся.
    Мейнстрим в новостях - то, о чём пишут давно и ровно."""
    from core.live import это_плато
    assert это_плато({"age_months": 22, "growth": -0.01})
    assert not это_плато({"age_months": 12, "growth": 0.20})
    assert not это_плато({"age_months": 22, "growth": 0.15})   # старое, но растёт - не плато


def test_пресс_релизы_с_одного_домена_отсекаются():
    comp = {"counts_recent": 47, "age_months": 2, "active_months": 3, "last_share": 0.43}
    assert причина_отказа_live(comp, n_domains=1, trusted_share=0.0) is not None
    assert причина_отказа_live(comp, n_domains=6, trusted_share=1.0) is None


def test_живой_прогон_ранжирует_и_укладывается_в_бюджет(живой):
    import time
    t = time.time()
    тренды, отсеянные = построить_live(живой, живой / "works.parquet", "live-test",
                                       as_of="2026-08")
    assert time.time() - t < 10
    метки = [r["label"] for r in тренды]
    assert метки[0] == "agent-iam"
    assert "hype-corp" not in метки
    assert any(r["label"] == "hype-corp" for r in отсеянные)
    assert тренды[0]["series_granularity"] == "month"
    assert len(тренды[0]["years"]) == len(тренды[0]["counts"])

