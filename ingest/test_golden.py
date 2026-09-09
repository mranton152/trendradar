"""Проверки потерь данных и воспроизводимости золотого среза."""
import json
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from ingest.http import Client
from ingest.normalize import normalize
from ingest.sources.openalex import sample_year, select_valid


def work():
    return {
        "id": "https://openalex.org/W123", "title": " A study ",
        "type": "article", "publication_year": 2020,
        "doi": "https://doi.org/10.1234/example",
        "abstract_inverted_index": {"world": [1], "Hello": [0, 2]},
        "authorships": [{"countries": ["US", None, "US"],
                         "author": {"display_name": "Author"},
                         "institutions": [{"country_code": "GB", "display_name": "Lab"}]}],
    }


def test_normalize_preserves_abstract_and_unique_countries():
    row = normalize(work(), "artificial-intelligence", "2026-09-08T00:00:00Z")
    assert row["abstract"] == "Hello world Hello"
    assert row["countries"] == ["GB", "US"]
    assert row["doc_id"] == "openalex:W123"
    assert row["title"] == "A study"
    assert row["url"] == "https://doi.org/10.1234/example"


@pytest.mark.parametrize("field,value", [("title", " "), ("id", None),
                                        ("doi", None), ("publication_year", None)])
def test_invalid_required_data_is_rejected(field, value):
    record = work()
    record[field] = value
    with pytest.raises(ValueError):
        normalize(record, "ai", "2026-09-08T00:00:00Z")


def test_page_size_stays_fixed_on_last_page():
    class Pages:
        def get(self, path, params):
            assert params["per_page"] == 100
            page = params["page"]
            return {"results": [{"id": f"W{i}"}
                                for i in range((page - 1) * 100, min(page * 100, 217))]}

    result = sample_year(Pages(), "concepts.id:C154945302", 2020, 217, 42, "2026-09-08")
    assert len(result) == 217
    assert len({r["id"] for r in result}) == 217


def test_short_sample_fails():
    class Empty:
        def get(self, path, params):
            return {"results": []}

    with pytest.raises(ValueError):
        sample_year(Empty(), "concepts.id:C154945302", 2020, 217, 42, "2026-09-08")


def test_selection_excludes_missing_urls_and_takes_next_valid_work():
    invalid = work()
    invalid["doi"] = None
    valid = work()
    rows, rejected = select_valid([invalid, valid], 1, "ai", "2026-09-08")
    assert len(rows) == 1
    assert rows[0]["url"] == "https://doi.org/10.1234/example"
    assert len(rejected) == 1


def test_selection_excludes_a_document_with_confirmed_dead_url():
    first = work()
    second = work()
    second["id"] = "https://openalex.org/W456"
    rows, rejected = select_valid([first, second], 1, "ai", "2026-09-08",
                                  excluded={"openalex:W123"})
    assert rows[0]["doc_id"] == "openalex:W456"
    assert len(rejected) == 1


def test_cached_response_can_be_read_after_server_stops(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"results": [{"id": "W123"}]}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        first = Client(tmp_path, base=base).get("/works", {"sample": 1})
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert Client(tmp_path, base=base, offline=True).get("/works", {"sample": 1}) == first


def test_offline_missing_cache_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        Client(tmp_path, offline=True).get("/works", {})


def test_http_404_is_not_cached(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = Client(tmp_path, base=f"http://127.0.0.1:{server.server_port}")
        with pytest.raises(urllib.error.HTTPError):
            client.get("/works", {})
        assert not list(tmp_path.glob("*.json"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
