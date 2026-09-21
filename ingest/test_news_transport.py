"""Транспорт: кэш, повторы и ограничение времени без внешней сети."""
import asyncio
import time

import httpx
import pytest

from ingest.news_transport import NewsClient


def test_retry_and_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '0'})
        return httpx.Response(200, json={'hits': []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = NewsClient(http, tmp_path)
            first = await client.get('https://example.org', {'q': 'robotics'})
            second = await client.get('https://example.org', {'q': 'robotics'})
            assert first == second
    asyncio.run(run())
    assert len(calls) == 2


def test_unauthorized_is_not_retried_or_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(httpx.HTTPStatusError):
                await NewsClient(http, tmp_path).get('https://example.org')
    asyncio.run(run())
    assert len(calls) == 1
    assert not list(tmp_path.glob('*.bin'))


def test_retry_after_cannot_overrun_deadline(tmp_path):
    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(429, headers={'Retry-After': '3600'}))
        async with httpx.AsyncClient(transport=transport) as http:
            client = NewsClient(http, tmp_path, deadline=time.monotonic() + 0.05)
            with pytest.raises(TimeoutError):
                await client.get('https://example.org')
    started = time.monotonic()
    asyncio.run(run())
    assert time.monotonic() - started < 1


def test_cancellation_is_propagated(tmp_path):
    async def handler(request):
        raise asyncio.CancelledError

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(asyncio.CancelledError):
                await NewsClient(http, tmp_path).get('https://example.org')
    asyncio.run(run())


def test_offline_miss_never_requests_network(tmp_path):
    def handler(request):
        raise AssertionError('Сеть в offline запрещена')

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(FileNotFoundError):
                await NewsClient(http, tmp_path, offline=True).get('https://example.org')
    asyncio.run(run())
