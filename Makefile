.PHONY: install test eval serve charts lint
install:
	pip install -e ".[dev]"
test:
	pytest -q
eval:
	orion eval
charts:
	python scripts/make_charts.py
serve:
	orion serve
lint:
	ruff check orion tests
