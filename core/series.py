"""Годовая динамика кандидатов.

Считается SQL-джойном по parquet: DuckDB делает это на порядок быстрее, чем
питон в цикле, и не требует поднимать сервер БД.

Документы взвешиваются по лагу источника (см. core/lead.py): препринт весит
больше журнальной статьи, потому что опережает её примерно на год. Без этого
зарождающийся сигнал становится виден только тогда, когда он уже не слабый.

Все значения передаются параметрами, а не подстановкой в строку запроса.
DuckDB умеет читать произвольные файлы через read_parquet, поэтому склейка
запроса из внешних данных - это чтение любого файла на диске, а не только
порча выборки.
"""
from collections import defaultdict
from pathlib import Path

import duckdb

from core.lead import sql_вес


def _подключение() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def year_counts(index_dir: str | Path, corpus_path: str | Path) -> dict[str, dict[int, int]]:
    """{cand_id: {год: взвешенное число документов}}"""
    links = str(Path(index_dir) / "cand_docs.parquet")
    # sql_вес() собран из константы модуля, а не из данных — подстановка здесь
    # безопасна, в отличие от значений, которые идут параметрами.
    строки = _подключение().execute(f"""
        SELECT cd.cand_id, w.year, sum({sql_вес()}) AS n
        FROM read_parquet(?) cd JOIN read_parquet(?) w USING (doc_id)
        GROUP BY 1, 2
    """, [links, str(corpus_path)]).fetchall()
    out: dict[str, dict[int, int]] = defaultdict(dict)
    for cand_id, year, n in строки:
        out[cand_id][int(year)] = int(round(float(n)))
    return dict(out)


def country_spread(index_dir: str | Path, corpus_path: str | Path,
                   y_from: int, y_to: int) -> dict[str, int]:
    """Сколько разных стран публикует по кандидату в окне.

    Прокси распространения: тема, которой занимается одна лаборатория,
    ещё не тренд, каким бы быстрым ни был её рост.
    """
    links = str(Path(index_dir) / "cand_docs.parquet")
    строки = _подключение().execute("""
        SELECT cd.cand_id, count(DISTINCT c) AS n
        FROM read_parquet(?) cd
        JOIN read_parquet(?) w USING (doc_id),
             unnest(w.countries) AS t(c)
        WHERE w.year BETWEEN ? AND ?
        GROUP BY 1
    """, [links, str(corpus_path), int(y_from), int(y_to)]).fetchall()
    return {cand_id: int(n) for cand_id, n in строки}


def top_docs(index_dir: str | Path, corpus_path: str | Path,
             cand_id: str, limit: int = 20, since: int | None = None) -> list[str]:
    """Документы кандидата для RAG и ссылок: свежие и цитируемые вперёд.

    `since` — год взлёта нынешней волны. У термина бывает прошлая жизнь:
    state space model до Mamba — это теория управления, и по строке к тренду
    приходили статьи про угольную электростанцию 2018 года. Скоринг при этом
    описывал взлёт 2025-го. Карточка и оценка говорили о разном.
    Документы обязаны браться из той же волны, по которой посчитана оценка.
    """
    links = str(Path(index_dir) / "cand_docs.parquet")
    строки = _подключение().execute("""
        SELECT w.doc_id
        FROM read_parquet(?) cd JOIN read_parquet(?) w USING (doc_id)
        WHERE cd.cand_id = ? AND w.year >= ?
        ORDER BY w.year DESC, w.cited_by DESC NULLS LAST
        LIMIT ?
    """, [links, str(corpus_path), cand_id,
          int(since) if since is not None else 0, int(limit)]).fetchall()
    return [r[0] for r in строки]
