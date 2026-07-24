.PHONY: install install-dev test test-unit cov lint fmt clean

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

test:
	pytest

test-unit:
	pytest tests/unit

cov:
	pytest --cov=src --cov-report=xml --cov-report=term

lint:
	ruff check .
	black --check .
	mypy src

fmt:
	ruff check --fix .
	black .

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
