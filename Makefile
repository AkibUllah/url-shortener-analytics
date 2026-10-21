.PHONY: install dev test lint fmt run openapi docker-up docker-down clean

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

dev: install

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

run:
	$(PY) -m uvicorn shortener.main:app --reload --port 8000

openapi:
	$(PY) scripts/export_openapi.py

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down -v

clean:
	rm -rf .pytest_cache .ruff_cache shortener.db
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
