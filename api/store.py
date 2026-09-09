"""Неизменяемый снимок индекса в памяти: Parquet читается только при создании."""
import logging
import re
from copy import deepcopy
from pathlib import Path

import duckdb

DEFAULT_INDEX_ROOT = Path(__file__).resolve().parents[1] / "data" / "index"
DOMAIN_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
log = logging.getLogger("trendradar")


class Store:
    """Домены определяются папками с trends.parquet; обновление требует перезапуска.

    DuckDB используется только при загрузке. Обработчики читают Python-объекты,
    поэтому между потоками HTTP нет общего SQL-соединения. Возвращаем копии,
    чтобы вызывающий код не мог изменить сохранённые данные.
    """

    def __init__(self, index_root: str | Path = DEFAULT_INDEX_ROOT):
        self.root = Path(index_root).resolve()
        self._trends: dict[str, list[dict]] = {}
        self._by_id: dict[str, dict] = {}
        self._trend_domains: dict[str, str] = {}
        self._works: dict[str, dict[str, dict]] = {}
        if not self.root.exists():
            return
        with duckdb.connect(database=":memory:") as con:
            for directory in sorted(self.root.iterdir()):
                if not DOMAIN_NAME.fullmatch(directory.name) or not directory.is_dir():
                    continue
                path = directory / "trends.parquet"
                if not self._safe_file(path, self.root):
                    continue
                try:
                    rows = self._read(con, path)
                    rows.sort(key=lambda row: (row["as_of"], row["rank"]))
                    ids = [row["trend_id"] for row in rows]
                    if len(set(ids)) != len(ids) or any(i in self._by_id for i in ids):
                        raise ValueError("повторяющийся trend_id")
                    corpus_root = self.root.parent / "corpus"
                    corpus = corpus_root / directory.name / "works.parquet"
                    if not self._safe_file(corpus, corpus_root):
                        corpus = directory / "works.parquet"
                    works = (self._read(con, corpus)
                             if self._safe_file(corpus, self.root)
                             or self._safe_file(corpus, corpus_root) else [])
                    documents = {row["doc_id"]: row for row in works}
                except (duckdb.Error, KeyError, TypeError, ValueError) as exc:
                    log.warning("Домен %s пропущен: не удалось загрузить индекс: %s",
                                directory.name, exc)
                    continue
                self._trends[directory.name] = rows
                self._works[directory.name] = documents
                self._by_id.update(zip(ids, rows, strict=True))
                self._trend_domains.update(dict.fromkeys(ids, directory.name))

    @staticmethod
    def _safe_file(path: Path, root: Path) -> bool:
        """Не разрешаем ссылкам в индексе вести за пределы каталога данных."""
        return path.is_file() and path.resolve().is_relative_to(root.resolve())

    @staticmethod
    def _read(con: duckdb.DuckDBPyConnection, path: Path) -> list[dict]:
        result = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
        columns = [column[0] for column in result.description]
        return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]

    def domains(self) -> list[str]:
        return sorted(self._trends)

    def trends(self, domain: str, as_of: int, top: int = 15) -> list[dict]:
        if top <= 0:
            return []
        return deepcopy([row for row in self._trends.get(domain, [])
                         if row["as_of"] == as_of][:top])

    def trend(self, trend_id: str) -> dict | None:
        return deepcopy(self._by_id.get(trend_id))

    def trend_domain(self, trend_id: str) -> str | None:
        """Папка индекса для тренда, даже если её имя отличается от row["domain"]."""
        return self._trend_domains.get(trend_id)

    def n_works(self, domain: str) -> int:
        return len(self._works.get(domain, {}))

    def as_of_years(self, domain: str) -> list[int]:
        """Срезы, для которых в загруженном домене есть хотя бы один тренд."""
        return sorted({int(row["as_of"]) for row in self._trends.get(domain, [])})

    def works(self, domain: str, doc_ids: list[str]) -> list[dict]:
        """Источники в порядке запроса, без повторов и неизвестных идентификаторов."""
        documents = self._works.get(domain, {})
        return deepcopy([documents[i] for i in dict.fromkeys(doc_ids) if i in documents])
