"""Recovery from truncated OpenAlex responses must not cache partial data."""
import io
import ssl
from http.client import IncompleteRead, RemoteDisconnected
from unittest.mock import patch

import pytest

from ingest.http import Client


@pytest.mark.parametrize("failure", [IncompleteRead(b'{"results":', 100),
                                     RemoteDisconnected("connection closed")])
def test_truncated_response_is_retried_and_only_complete_json_cached(tmp_path, failure):
    with patch("ingest.http.urllib.request.urlopen", side_effect=[
        failure, io.BytesIO(b'{"results": []}')
    ]) as request, patch("ingest.http.time.sleep"):
        client = Client(tmp_path)
        assert client.get("/works", {}) == {"results": []}
        assert request.call_count == 2
        assert client.get("/works", {}) == {"results": []}
        assert request.call_count == 2
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("failure", [IncompleteRead(b'', 1), RemoteDisconnected("closed")])
def test_truncated_response_retries_are_bounded_without_cache(tmp_path, failure):
    with patch("ingest.http.urllib.request.urlopen", side_effect=failure) as request:
        with patch("ingest.http.time.sleep"), pytest.raises(type(failure)):
            Client(tmp_path).get("/works", {})
        assert request.call_count == 5
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("recover", [True, False])
def test_ssl_failure_while_reading_response(tmp_path, recover):
    class BrokenResponse(io.BytesIO):
        def read(self, *args):
            raise ssl.SSLError(1, "[SSL] record layer failure")

    responses = ([BrokenResponse(), io.BytesIO(b'{"results": []}')]
                 if recover else [BrokenResponse() for _ in range(5)])
    with patch("ingest.http.urllib.request.urlopen", side_effect=responses) as request:
        with patch("ingest.http.time.sleep"):
            if recover:
                assert Client(tmp_path).get("/works", {}) == {"results": []}
                assert request.call_count == 2
                assert len(list(tmp_path.glob("*.json"))) == 1
            else:
                with pytest.raises(ssl.SSLError):
                    Client(tmp_path).get("/works", {})
                assert request.call_count == 5
                assert not list(tmp_path.iterdir())


def test_certificate_failure_is_not_retried(tmp_path):
    failure = ssl.SSLCertVerificationError(1, "certificate verify failed")
    with patch("ingest.http.urllib.request.urlopen", side_effect=failure) as request:
        with patch("ingest.http.time.sleep"), pytest.raises(ssl.SSLCertVerificationError):
            Client(tmp_path).get("/works", {})
        assert request.call_count == 1
    assert not list(tmp_path.iterdir())
