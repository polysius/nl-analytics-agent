# Targets run inside the `app` container so they behave the same on Windows ARM, Linux and CI.
RUN = docker compose --profile tools run --rm app
SUBSET ?= 20

# Model calls go through the Claude Code CLI bridge. Start it first on the host:
#   python scripts/claude_cli_bridge.py
BRIDGE_ENV = -e LLM_PROVIDER=openai -e LLM_BASE_URL=http://host.docker.internal:8787/v1 -e LLM_MODEL=sonnet -e LLM_API_KEY=x
RUN_BRIDGE = docker compose --profile tools run --rm -T $(BRIDGE_ENV) app

.PHONY: up load-data test lint eval eval-subset gate-baseline eval-all retrieval-eval judge-eval graph-diagram down

up:
	docker compose up -d --wait postgres

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

# The accuracy gate: a fixed subset of the benchmark, compared with benchmark/ci_baseline.json.
# Fails (exit 1) when accuracy drops more than 10 points. Run it before merging prompt changes.
eval-subset:
	$(RUN_BRIDGE) python -m nlagent.evaluate --config graph --limit $(SUBSET) --out reports/pr.json
	$(RUN_BRIDGE) python -m nlagent.regression --report reports/pr.json --baseline benchmark/ci_baseline.json

# Rewrite the baseline after an intentional change, from a fresh run of the same subset.
gate-baseline:
	$(RUN_BRIDGE) python -m nlagent.evaluate --config graph --limit $(SUBSET) --out reports/pr.json
	$(RUN_BRIDGE) python -m nlagent.regression --report reports/pr.json --baseline benchmark/ci_baseline.json --write-baseline

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
