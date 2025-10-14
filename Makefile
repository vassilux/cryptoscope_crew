.PHONY: run run-offline fmt lint

run:
	uv run python -m cryptoscope_crew.main

run-offline:
	uv run python -m cryptoscope_crew.main --inputs offline=true

fmt:
	uv run python -m pip install ruff==0.6.9
	uv run ruff check --select I --fix .
	uv run ruff format .

lint:
	uv run ruff check .
