import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import FEATURES, SCHEMAS


def test_features_в_реестре_схем():
    assert SCHEMAS["features"] is FEATURES


def test_все_признаки_после_label_необязательные():
    """Источники разные и могут отсутствовать: у технологии из датасета может
    не быть репозиториев, у новостного кандидата - публикаций."""
    for f in FEATURES:
        if f.name not in ("cand_id", "label", "domain", "as_of"):
            assert f.nullable, f.name


def test_строка_с_пропусками_пишется(tmp_path):
    строка = {"cand_id": "c1", "label": "agent iam", "domain": "d", "as_of": "2026-09",
              "news_mentions_24m": 47, "news_mentions_by_month": [0] * 23 + [47],
              "trusted_share": 0.8, "is_weak_signal": True, "dataset_score": 7}
    p = tmp_path / "f.parquet"
    pq.write_table(pa.Table.from_pylist([строка], schema=FEATURES), p)
    assert pq.read_table(p).num_rows == 1
