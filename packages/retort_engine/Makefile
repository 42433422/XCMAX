.PHONY: lint test self-evolve

lint:
	python -m ruff check .

test:
	PYTHONPATH=. python -m pytest tests -q

self-evolve:
	PYTHONPATH=. python -m retort_engine.cli self-evolve --project . --run-local-gates
