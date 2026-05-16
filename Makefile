.PHONY: setup test check fmt clean ui

setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev,ui]"

ui:
	.venv/bin/streamlit run streamlit_app.py

test:
	.venv/bin/pytest

check:
	.venv/bin/ruff check src tests
	.venv/bin/pytest

fmt:
	.venv/bin/ruff format src tests

clean:
	rm -rf .venv .pytest_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
