.PHONY: install install-dev test test-unit cov lint fmt clean simulate

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

generate-data:
	python -m persistence.generators.run

batch-load:
	python -m persistence.batch_loader

ingest-docs:
	python -m rag.ingest

simulate:
	python -m streaming.simulate_cli --scenario $(SCENARIO)

mcp-rag-retriever:
	python -m mcp_servers.rag_retriever

event-agent:
	python -m streaming.event_agent

publish-live-prices:
	python -m streaming.live_feed_cli --tickers "$(TICKERS)"

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
