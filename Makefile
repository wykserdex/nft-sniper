.PHONY: install format lint typecheck test test-unit test-contract \
        test-integration compose-up compose-down migrate revision run check

install:
	pip install -e ".[dev]"

format:
	ruff format src tests scripts
	ruff check --fix src tests scripts

lint:
	ruff format --check src tests scripts
	ruff check src tests scripts
	mypy
	python scripts/no_float.py

typecheck:
	mypy

test:
	pytest

test-unit:
	pytest tests/unit -v

test-contract:
	pytest tests/contract -v

test-integration:
	pytest tests/integration -v

compose-up:
	docker compose up -d postgres redis

compose-down:
	docker compose down

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

run:
	nftsniper serve

check:
	nftsniper check
