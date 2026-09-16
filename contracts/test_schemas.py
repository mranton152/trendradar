"""Контракты под требования ТЗ: новые поля не ломают старые файлы."""
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import REJECTED, SCHEMAS, TRENDS, WORKS


def test_works_знает_доверенность_тип_язык_и_резюме():
    имена = {f.name for f in WORKS}
    assert {"source_type", "trust_level", "summary_ru", "summary_model"} <= имена
    for поле in ("source_type", "trust_level", "summary_ru", "summary_model"):
        assert WORKS.field(поле).nullable, поле


def test_старый_golden_читается_новой_схемой():
    """Золотой снапшот собран до ТЗ. Новые поля обязаны быть необязательными,
    иначе всё, что уже работает, ломается в день расширения контракта."""
    старый = pq.read_table("data/index/golden/works.parquet")
    for поле in WORKS:
        if поле.name not in старый.column_names:
            assert поле.nullable, f"{поле.name} добавлено как обязательное"


def test_trends_умеет_бэктест():
    имена = {f.name for f in TRENDS}
    assert {"bt_at_cutoff", "bt_peak_after", "bt_growth_x"} <= имена
    assert all(TRENDS.field(п).nullable for п in ("bt_at_cutoff", "bt_peak_after", "bt_growth_x"))


def test_rejected_это_отдельный_контракт():
    assert "rejected" in SCHEMAS
    assert {f.name for f in REJECTED} == {"cand_id", "label", "reason", "n_docs", "as_of", "domain"}


def test_rejected_пишется_и_проходит_валидацию(tmp_path):
    строки = [{"cand_id": "c1", "label": "lynching tree", "domain": "golden",
               "reason": "нет географического распространения", "n_docs": 1314, "as_of": 2026}]
    p = tmp_path / "rejected.parquet"
    pq.write_table(pa.Table.from_pylist(строки, schema=REJECTED), p)
    assert pq.read_schema(p).equals(REJECTED)
