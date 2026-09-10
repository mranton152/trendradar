"""Проверки докачки полного корпуса без сети."""
import json

import pyarrow.parquet as pq
import pytest


def record(number, year=2020, kind="article"):
    return {"id": f"https://openalex.org/W{number}", "title": "Test paper",
            "publication_year": year, "publication_date": f"{year}-01-01",
            "doi": f"https://doi.org/10.1/{number}", "type": kind}


class Pages:
    def __init__(self):
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, params))
        if path == "/concepts":
            return {"results": [{"display_name": "artificial intelligence",
                                  "id": "https://openalex.org/C1"}]}
        assert "sample" not in params
        assert "type:article|preprint|report" in params["filter"]
        if params["cursor"] == "*":
            return {"results": [record(1), record(2, kind="preprint"), {}],
                    "meta": {"next_cursor": "next"}}
        return {"results": [record(1), record(3, kind="report")],
                "meta": {"next_cursor": None}}


def test_resume_and_publish_only_complete(tmp_path):
    from ingest.full import harvest
    client = Pages()
    args = {"client": client, "output": tmp_path, "domain": "artificial-intelligence",
                "years": "2020-2020", "as_of": "2020-12-31"}
    state = harvest(**args, max_pages=1)
    assert state["status"] == "incomplete"
    assert state["rejected"] == 1
    assert not (tmp_path / "works.parquet").exists()
    client.calls.clear()
    state = harvest(**args, max_pages=1)
    assert state["status"] == "complete"
    assert client.calls[0][1]["cursor"] == "next"
    table = pq.read_table(tmp_path / "works.parquet")
    assert table.num_rows == 3
    assert set(table["doc_type"].to_pylist()) == {"article", "report", "preprint"}
    assert state["duplicates"] == 1
    assert json.loads((tmp_path / "manifest.json").read_text())["status"] == "complete"
    client.calls.clear()
    harvest(**args)
    assert client.calls == []


def test_identity_change_rejected_before_network(tmp_path):
    from ingest.full import harvest
    client = Pages()
    harvest(client, tmp_path, "artificial-intelligence", "2020-2020", "2020-12-31", 1)
    client.calls.clear()
    with pytest.raises(ValueError, match="конфигурац"):
        harvest(client, tmp_path, "artificial-intelligence", "2020-2020", "2020-11-30")
    assert client.calls == []


def test_failed_request_keeps_checkpoint(tmp_path):
    from ingest.full import harvest
    client = Pages()
    harvest(client, tmp_path, "artificial-intelligence", "2020-2020", "2020-12-31", 1)
    before = (tmp_path / "manifest.json").read_bytes()

    class Failed:
        def get(self, *args):
            raise OSError("offline")

    with pytest.raises(OSError):
        harvest(Failed(), tmp_path, "artificial-intelligence", "2020-2020", "2020-12-31")
    assert before == (tmp_path / "manifest.json").read_bytes()
    assert not (tmp_path / "works.parquet").exists()


def test_page_replayed_after_checkpoint_failure(tmp_path, monkeypatch):
    from ingest import full
    original = full.atomic_json

    def fail_checkpoint(path, value):
        if path.name == "manifest.json" and value["pages"] == 1:
            raise OSError("disk full")
        original(path, value)

    monkeypatch.setattr(full, "atomic_json", fail_checkpoint)
    with pytest.raises(OSError):
        full.harvest(Pages(), tmp_path, "artificial-intelligence", "2020-2020",
                     "2020-12-31", 1)
    assert (tmp_path / "pages/000000000.parquet").exists()
    monkeypatch.setattr(full, "atomic_json", original)
    result = full.harvest(Pages(), tmp_path, "artificial-intelligence", "2020-2020",
                          "2020-12-31")
    assert result["pages"] == 2
    assert result["n_works"] == 3
    assert result["rejected"] == 1


def test_year_cursors_reset_and_bad_dates_logged(tmp_path):
    from ingest.full import harvest

    class Years(Pages):
        def get(self, path, params):
            if path == "/concepts":
                return super().get(path, params)
            assert params["cursor"] == "*"
            year = 2020 if "publication_year:2020," in params["filter"] else 2021
            bad = record(99, year)
            bad["publication_date"] = "not-a-date"
            return {"results": [record(year, year), bad], "meta": {"next_cursor": None}}

    state = harvest(Years(), tmp_path, "artificial-intelligence", "2020-2021", "2021-12-31")
    assert state["counts_by_year"] == {"2020": 1, "2021": 1}
    assert state["rejected"] == 2


@pytest.mark.parametrize("domain,years,as_of,limit", [
    ("../escape", "2020-2020", "2020-12-31", 1),
    ("ai", "2021-2020", "2021-12-31", 1),
    ("ai", "2020-2022", "2021-12-31", 1),
    ("ai", "2020-2020", "2020-12-31", 0),
])
def test_invalid_config_never_requests(tmp_path, domain, years, as_of, limit):
    from ingest.full import harvest
    client = Pages()
    with pytest.raises(ValueError):
        harvest(client, tmp_path, domain, years, as_of, limit)
    assert client.calls == []


def test_explicit_concept_id_verified_and_persisted(tmp_path):
    from ingest.full import harvest

    class Explicit(Pages):
        def get(self, path, params):
            if path == "/concepts/C58053490":
                return {"id": "https://openalex.org/C58053490",
                        "display_name": "Quantum computer"}
            assert path != "/concepts"
            assert "concepts.id:C58053490" in params["filter"]
            return {"results": [], "meta": {"next_cursor": None}}

    state = harvest(Explicit(), tmp_path, "quantum-computing", "2020-2020",
                    "2020-12-31", concept_id="C58053490")
    assert state["concept_name"] == "Quantum computer"
    assert state["n_works"] == 0
    assert state["config"]["concept_id"] == "C58053490"
