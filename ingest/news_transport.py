"""Общий транспорт новостных источников: ограниченное время и кэш ответов."""
import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx


class NewsClient:
    def __init__(self, http: httpx.AsyncClient, cache: Path, *, deadline=None,
                 attempts=3, ttl=3600, max_bytes=10_000_000, offline=False):
        self.http = http
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.deadline = deadline
        self.attempts = max(1, attempts)
        self.ttl = ttl
        self.max_bytes = max_bytes
        self.offline = offline

    async def get(self, url, params=None):
        """Возвращает байты; deadline — monotonic, общий для всех источников."""
        remaining = None if self.deadline is None else self.deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError('Исчерпан бюджет сбора')
        async with asyncio.timeout(remaining):
            return await self._get(url, params)

    async def _get(self, url, params):
        target = str(httpx.URL(url, params=sorted((params or {}).items())))
        path = self.cache / (hashlib.sha256(target.encode()).hexdigest() + '.bin')
        if path.exists() and (self.offline or time.time() - path.stat().st_mtime <= self.ttl):
            if path.stat().st_size <= self.max_bytes:
                return path.read_bytes()
        if self.offline:
            raise FileNotFoundError('Ответ отсутствует в локальном кэше')
        for attempt in range(self.attempts):
            delay = 2 ** attempt
            try:
                async with self.http.stream('GET', target, timeout=20,
                                            follow_redirects=True) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise ValueError('Ответ источника превышает ограничение размера')
                temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
                try:
                    temporary.write_bytes(body)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
                return bytes(body)
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in {429, 500, 502, 503, 504}:
                    raise
                if attempt + 1 == self.attempts:
                    raise
                retry_after = error.response.headers.get('Retry-After')
                if retry_after:
                    try:
                        delay = max(0, float(retry_after))
                    except ValueError:
                        try:
                            date = parsedate_to_datetime(retry_after)
                            delay = max(0, (date - datetime.now(UTC)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
            except httpx.TransportError:
                if attempt + 1 == self.attempts:
                    raise
            await asyncio.sleep(delay)
