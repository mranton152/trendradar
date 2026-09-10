"""Recovery from truncated OpenAlex responses must not cache partial data."""
import io
from http.client import IncompleteRead
from unittest.mock import patch

import pytest

from ingest.http import Client


def test_truncated_response_is_retried_and_only_complete_json_cached(tmp_path):
    with patch("ingest.http.urllib.request.urlopen", side_effect=[
        IncompleteRead(b'{"results":', 100), io.BytesIO(b'{"results": []}')
    ]) as request, patch("ingest.http.time.sleep"):
        client = Client(tmp_path)
        assert client.get("/works", {}) == {"results": []}
        assert request.call_count == 2
        assert client.get("/works", {}) == {"results": []}
        assert request.call_count == 2
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_truncated_response_retries_are_bounded_without_cache(tmp_path):
    with patch("ingest.http.urllib.request.urlopen", side_effect=IncompleteRead(b'', 1)) as request:
        with patch("ingest.http.time.sleep"), pytest.raises(IncompleteRead):
            Client(tmp_path).get("/works", {})
        assert request.call_count == 5
    assert not list(tmp_path.iterdir())
