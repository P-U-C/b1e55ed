.PHONY: install test test-cov lint format typecheck run dev dashboard setup clean

install:
	uv sync --extra dev

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ --cov=engine --cov-report=term-missing

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy engine/

run:
	uv run uvicorn api.main:app --host 127.0.0.1 --port 5050

dev:
	uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 5050

dashboard:
	uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 5051

setup:
	bash scripts/setup.sh

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
