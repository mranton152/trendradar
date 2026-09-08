.PHONY: help check lint test contracts demo pull-corpus setup

DOMAIN ?= artificial-intelligence
AS_OF  ?= 2026

help:
	@echo "setup        — поставить зависимости (uv sync)"
	@echo "check        — линт + тесты + валидация контрактов. Гнать перед каждым PR"
	@echo "demo         — сквозной прогон: ingest → semantic → core → cards → api"
	@echo "pull-corpus  — скачать полный корпус из GitHub Releases"

setup:
	uv sync --all-extras

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
