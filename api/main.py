"""FastAPI над локальным индексом. Запуск: uv run uvicorn api.main:app."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.store import DEFAULT_INDEX_ROOT, Store

log = logging.getLogger("trendradar")


def get_store(request: Request) -> Store:
    """Зависимость для обработчиков: один снимок на время жизни приложения."""
    return request.app.state.store


def create_app(index_root: str | Path = DEFAULT_INDEX_ROOT) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = Store(index_root)
        app.state.live_jobs = {}
        domains = app.state.store.domains()
        if domains:
            log.info("Загружены домены индекса: %s", ", ".join(domains))
        else:
            log.warning("Индекс пуст: нет доступных trends.parquet в %s", index_root)
        yield
        del app.state.store
        del app.state.live_jobs

    app = FastAPI(title="TrendRadar API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    @app.get("/api/v1/health")
    def health(request: Request) -> dict:
        return {"status": "ok", "indexed_domains": get_store(request).domains(),
                "offline_mode": True}

    from api.routes.live import router as live_router
    from api.routes.methodology import router as methodology_router
    from api.routes.trends import router as trends_router

    app.include_router(methodology_router)
    app.include_router(live_router)
    app.include_router(trends_router)
    return app


app = create_app()
