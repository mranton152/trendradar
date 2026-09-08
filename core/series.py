"""Годовая динамика кандидатов.

Считается SQL-джойном по parquet: DuckDB делает это на порядок быстрее, чем
питон в цикле, и не требует поднимать сервер БД.
"""
from collections import defaultdict
from pathlib import Path

import duckdb


def year_counts(index_dir: str | Path, corpus_path: str | Path) -> dict[str, dict[int, int]]:
    """{cand_id: {год: сколько документов}}"""
    links = Path(index_dir) / "cand_docs.parquet"
    строки = duckdb.sql(f"""
        SELECT cd.cand_id, w.year, count(*) AS n
        FROM '{links}' cd JOIN '{corpus_path}' w USING (doc_id)
        GROUP BY 1, 2
    """).fetchall()
    out: dict[str, dict[int, int]] = defaultdict(dict)
    for cand_id, year, n in строки:
        out[cand_id][int(year)] = int(n)
    return dict(out)


def country_spread(index_dir: str | Path, corpus_path: str | Path,
                   y_from: int, y_to: int) -> dict[str, int]:
    """Сколько разных стран публикует по кандидату в окне.

    Прокси распространения: тема, которой занимается одна лаборатория,
    ещё не тренд, каким бы быстрым ни был её рост.
    """
    links = Path(index_dir) / "cand_docs.parquet"
    строки = duckdb.sql(f"""
        SELECT cd.cand_id, count(DISTINCT c) AS n
        FROM '{links}' cd
        JOIN '{corpus_path}' w USING (doc_id),
             unnest(w.countries) AS t(c)
        WHERE w.year BETWEEN {y_from} AND {y_to}
        GROUP BY 1
    """).fetchall()
    return {cand_id: int(n) for cand_id, n in строки}


def top_docs(index_dir: str | Path, corpus_path: str | Path,
             cand_id: str, limit: int = 20) -> list[str]:
    """Документы кандидата для RAG и ссылок: свежие и цитируемые вперёд."""
    links = Path(index_dir) / "cand_docs.parquet"
    строки = duckdb.sql(f"""
        SELECT w.doc_id
        FROM '{links}' cd JOIN '{corpus_path}' w USING (doc_id)
        WHERE cd.cand_id = '{cand_id}'
        ORDER BY w.year DESC, w.cited_by DESC NULLS LAST
        LIMIT {limit}
    """).fetchall()
    return [r[0] for r in строки]
