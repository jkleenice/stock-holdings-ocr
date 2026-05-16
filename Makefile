.PHONY: setup test check fmt clean ui deploy

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

# Run tests, then commit (if changes) and push to main. Streamlit Cloud auto-redeploys.
# Usage: `make deploy` or `make deploy M="add 새 카테고리"`
deploy: check
	git add -A
	git diff --cached --quiet || git commit -m "$(if $(M),$(M),update)"
	git push origin main
