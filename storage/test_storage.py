"""Схема без базы проверяется всегда; загрузка — только если Postgres доступен.

На CI Postgres поднимается сервисом, поэтому интеграционная часть там идёт
по-настоящему. Локально без `docker compose up -d postgres` она пропускается.
"""
import shutil

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from contracts.schemas import SCHEMAS
from storage import load
from storage.schema import KEYS, PATHS, TABLES, create_table, ddl, pg_type

GOLDEN = load.DATA / "index" / "golden"


def test_каждый_контракт_имеет_таблицу_ключ_и_путь():
    assert set(TABLES) == set(SCHEMAS) == set(KEYS) == set(PATHS)


def test_ключи_это_обязательные_поля_контракта():
    for table, key in KEYS.items():
        fields = {f.name: f for f in SCHEMAS[table]}
        for k in key:
            assert k in fields and not fields[k].nullable, (table, k)


def test_типы():
    assert pg_type(pa.list_(pa.int32())) == "integer[]"
    assert pg_type(pa.float32()) == "real"
    with pytest.raises(TypeError):
        pg_type(pa.timestamp("s"))


def test_ddl_покрывает_все_колонки():
    text = ddl()
    for table in TABLES:
        sql = create_table(table)
        for f in SCHEMAS[table]:
            assert f"    {f.name} " in sql
    assert "CREATE TABLE IF NOT EXISTS loads" in text


def test_имя_набора_проверяется(tmp_path):
    with pytest.raises(load.ОшибкаЗагрузки):
        load.файлы_набора("../etc", tmp_path)


def _conn():
    try:
        return psycopg.connect(load.dsn(), connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres недоступен")


@pytest.fixture
def conn():
    c = _conn()
    yield c
    with c.cursor() as cur:
        for table in (*TABLES, "loads"):
            cur.execute(f"DELETE FROM {table} WHERE dataset LIKE 'test-%'")
    c.commit()
    c.close()


def _набор(tmp_path, name="test-golden"):
    """Копия золотого снапшота под тестовым именем набора."""
    idx = tmp_path / "index" / name
    idx.mkdir(parents=True)
    for f in GOLDEN.glob("*.parquet"):
        shutil.copy(f, idx / f.name)
    return tmp_path


def test_загрузка_золотого_снапшота(conn, tmp_path):
    data = _набор(tmp_path)
    counts = load.загрузить_набор(conn, "test-golden", data)
    for table, n in counts.items():
        assert n == pq.read_metadata(GOLDEN / f"{table}.parquet").num_rows
    with conn.cursor() as cur:
        cur.execute("""SELECT label, years, counts FROM trends
                       WHERE dataset = 'test-golden' ORDER BY as_of DESC, rank LIMIT 1""")
        label, years, counts_ = cur.fetchone()
        assert label and len(years) == len(counts_)
        # списки доезжают массивами, а не строками
        assert isinstance(years[0], int)


def test_перезагрузка_заменяет_а_не_дублирует(conn, tmp_path):
    data = _набор(tmp_path)
    first = load.загрузить_набор(conn, "test-golden", data)
    second = load.загрузить_набор(conn, "test-golden", data)
    assert first == second
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trends WHERE dataset = 'test-golden'")
        assert cur.fetchone()[0] == first["trends"]


def test_файл_вне_контракта_не_грузится_и_не_портит_базу(conn, tmp_path):
    data = _набор(tmp_path)
    before = load.загрузить_набор(conn, "test-golden", data)
    bad = pq.read_table(data / "index" / "test-golden" / "trends.parquet")
    bad = bad.append_column("лишнее", pa.array([1] * bad.num_rows))
    pq.write_table(bad, data / "index" / "test-golden" / "trends.parquet")
    with pytest.raises(load.ОшибкаЗагрузки):
        load.загрузить_набор(conn, "test-golden", data)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM works WHERE dataset = 'test-golden'")
        assert cur.fetchone()[0] == before["works"]
