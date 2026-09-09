"""Интеграция ядра с настоящим золотым снапшотом.

Синтетика проверяет логику, но не форму реальных данных: там четверть записей
без стран, четверть без аннотаций, и год 2026 неполный. Этот тест ловит именно
такие вещи.

Кандидатов пока никто не считает (K-05…K-08 у Кости), поэтому связки
«кандидат — документ» собираются здесь по вхождению слова в заголовок.
Файлы пишутся во временную папку: чужие артефакты в репозитории не создаём.
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from contracts.schemas import CAND_DOCS
from core.series import country_spread, year_counts

СНАПШОТ = "data/index/golden/works.parquet"

pytestmark = pytest.mark.skipif(
    not __import__("pathlib").Path(СНАПШОТ).exists(),
    reason="золотого снапшота нет — стадия ingest ещё не отработала")


@pytest.fixture
def связки(tmp_path):
    """Два кандидата по вхождению слова в заголовок + один заведомо без стран."""
    import duckdb

    con = duckdb.connect()
    строки = []
    for слово, cand_id in (("learning", "c:learning"), ("network", "c:network")):
        for (doc_id,) in con.execute(
                "SELECT doc_id FROM read_parquet(?) WHERE lower(title) LIKE ?",
                [СНАПШОТ, f"%{слово}%"]).fetchall():
            строки.append({"cand_id": cand_id, "doc_id": doc_id, "weight": 1.0})

    без_стран = con.execute(
        "SELECT doc_id FROM read_parquet(?) "
        "WHERE countries IS NULL OR len(countries) = 0 LIMIT 50",
        [СНАПШОТ]).fetchall()
    строки += [{"cand_id": "c:безстран", "doc_id": d[0], "weight": 1.0}
               for d in без_стран]

    pq.write_table(pa.Table.from_pylist(строки, schema=CAND_DOCS),
                   tmp_path / "cand_docs.parquet")
    return tmp_path


def test_годовые_ряды_считаются_на_настоящих_данных(связки):
    ряды = year_counts(связки, СНАПШОТ)
    assert "c:learning" in ряды
    годы = ряды["c:learning"]
    assert min(годы) >= 2015 and max(годы) <= 2026
    assert sum(годы.values()) > 100


def test_записи_без_стран_не_ломают_подсчёт_географии(связки):
    """Четверть снапшота — без аффилиаций. unnest по пустому списку обязан
    давать ноль строк, а не падать и не считать NULL за страну."""
    страны = country_spread(связки, СНАПШОТ, 2015, 2026)
    assert страны.get("c:безстран", 0) == 0
    assert 1 < страны["c:learning"] <= 126


def test_кандидат_без_связок_просто_отсутствует(связки):
    ряды = year_counts(связки, СНАПШОТ)
    assert "c:такого-нет" not in ряды
