# Targets run inside the `app` container so they behave the same on Windows ARM, Linux and CI.
RUN = docker compose --profile tools run --rm app
SUBSET ?= 20

.PHONY: up load-data setup test lint eval eval-all retrieval-eval judge-eval mcp graph-diagram down

up:
	docker compose up -d postgres

# Download the f1db PostgreSQL dump, load it, create the read-only role, build the embeddings.
load-data: up
	bash scripts/load_data.sh
	$(RUN) python scripts/build_catalogue.py

test:
	$(RUN) pytest -q

lint:
	$(RUN) ruff check src tests scripts

# Benchmark one configuration. Example: make eval CONFIG=graph
CONFIG ?= graph
eval:
	$(RUN) python -m nlagent.evaluate --config $(CONFIG) --out reports/$(CONFIG).json

# Fixed subset with a spend cap, as used by CI.
eval-subset:
	$(RUN) python -m nlagent.evaluate --config graph --limit $(SUBSET) --max-cost-usd 1.00 --out reports/pr.json
	$(RUN) python -m nlagent.regression --report reports/pr.json --baseline benchmark/ci_baseline.json

eval-all:
	for c in full_schema retrieved retrieved_fewshot retrieved_fewshot_repair graph; do \
	  $(RUN) python -m nlagent.evaluate --config $$c --out reports/$$c.json || exit 1; done

retrieval-eval:
	$(RUN) python -m nlagent.retrieval_eval

judge-eval:
	$(RUN) python -m nlagent.judge

graph-diagram:
	$(RUN) python scripts/export_graph.py > docs/graph.mmd

down:
	docker compose down
