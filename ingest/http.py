"""HTTP OpenAlex: ограничение темпа, повторы и атомарный кэш без секретов."""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class Client:
    def __init__(self, cache, base="https://api.openalex.org", offline=False):
        self.cache = Path(cache)
        self.base = base
        self.offline = offline
        self.last_request = 0.0

    def get(self, path: str, params: dict) -> dict:
        url = self.base + path + "?" + urllib.parse.urlencode(sorted(params.items()))
        key = hashlib.sha256(url.encode()).hexdigest()
        file = self.cache / f"{key}.json"
        if file.exists():
            return json.loads(file.read_text(encoding="utf-8"))
        if self.offline:
            raise FileNotFoundError(f"Нет ответа в кэше: {file.name}")
        headers = {"User-Agent": "TrendRadar/0.1 (research snapshot)",
                   "Accept": "application/json"}
        if os.environ.get("OPENALEX_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["OPENALEX_API_KEY"]
        for attempt in range(5):
            time.sleep(max(0, 0.25 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = json.load(response)
                self.cache.mkdir(parents=True, exist_ok=True)
                temp = file.with_suffix(".tmp")
                temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                temp.replace(file)
                return payload
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == 4:
                    raise
                retry_after = error.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 2 ** attempt
                time.sleep(min(delay, 60))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Исчерпаны попытки HTTP")
