.PHONY: help check lint test contracts demo pull-corpus setup hooks pg-up pg-load pg-status requirements diagrams

DOMAIN ?= artificial-intelligence
AS_OF  ?= 2026

help:
	@echo "setup        — поставить зависимости (uv sync)"
	@echo "hooks        — включить git-хуки (запрет прямого пуша в main)"
	@echo "check        — линт + тесты + валидация контрактов. Гнать перед каждым PR"
	@echo "demo         — сквозной прогон: ingest → semantic → core → cards → api"
	@echo "pull-corpus  — скачать полный корпус из GitHub Releases"
	@echo "pg-up        — поднять Postgres (localhost:55432)"
	@echo "pg-load      — залить все наборы из data/ в Postgres"
	@echo "pg-status    — что сейчас лежит в Postgres"
	@echo "requirements — пересобрать requirements.txt из uv.lock"
	@echo "diagrams     — отрисовать схемы docs/diagrams/*.puml в SVG"

setup: hooks
	uv sync --all-extras

hooks:
	git config core.hooksPath .githooks
	@echo "✓ git-хуки включены: прямой пуш в main заблокирован"

lint:
	uv run ruff check .

test:
	uv run pytest -q

contracts:
	@for pair in \
	  "data/index/golden/works.parquet:works" \
	  "data/index/golden/candidates.parquet:candidates" \
	  "data/index/golden/cand_docs.parquet:cand_docs" \
	  "data/index/golden/trends.parquet:trends" \
	  "data/index/golden/cards.parquet:cards"; do \
	    f=$${pair%%:*}; s=$${pair##*:}; \
	    if [ -f "$$f" ]; then uv run python contracts/validate.py "$$f" --schema "$$s"; \
	    else echo "· $$f ещё нет — пропускаем"; fi; \
	done

check: lint test contracts

demo:
	uv run python -m ingest.harvest   --domain $(DOMAIN)
	uv run python -m semantic.build   --domain $(DOMAIN)
	uv run python -m core.build       --domain $(DOMAIN) --as-of $(AS_OF)
	uv run python -m cards.build      --domain $(DOMAIN) --as-of $(AS_OF)
	uv run uvicorn api.main:app --reload

pull-corpus:
	gh release download corpus-$(DOMAIN) -D data/corpus/$(DOMAIN)/ --clobber

pg-up:
	docker compose -f storage/compose.yml up -d --wait

pg-load:
	uv run python -m storage.load --all

pg-status:
	uv run python -m storage.load --status

# requirements.txt — для тех, кто ставит через pip. Источник правды — uv.lock,
# CI падает, если файл с ним разошёлся.
requirements:
	uv export --no-hashes --no-dev --no-emit-project --format requirements-txt -o requirements.txt -q

# Локальный plantuml (brew install plantuml), иначе — через Docker.
diagrams:
	@if command -v plantuml >/dev/null; then \
	  plantuml -tsvg -charset UTF-8 docs/diagrams/*.puml && \
	  plantuml -tpng -charset UTF-8 docs/diagrams/*.puml; \
	else \
	  docker run --rm -v "$(CURDIR)/docs/diagrams:/data" plantuml/plantuml -tsvg -charset UTF-8 /data/*.puml && \
	  docker run --rm -v "$(CURDIR)/docs/diagrams:/data" plantuml/plantuml -tpng -charset UTF-8 /data/*.puml; \
	fi
