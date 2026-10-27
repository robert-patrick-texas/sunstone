# Sunstone common tasks. `make help` lists them.

TOPOLOGY ?= data/sample/small.yaml

.PHONY: help setup dev-api dev-web build serve test e2e bench data api-types

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## Install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && npm ci

dev-api: ## API on :8000, restarting on code or topology changes (TOPOLOGY=file)
	cd backend && uv run sunstone --topology ../$(TOPOLOGY) --reload

dev-web: ## Vite dev server on :5173, proxying /api to dev-api
	cd frontend && npm run dev

build: ## Build the web UI into frontend/build
	cd frontend && npm run build

serve: build ## Serve the built UI and the API together on :8000 (TOPOLOGY=file)
	cd backend && uv run sunstone --topology ../$(TOPOLOGY) --web-dir ../frontend/build

test: ## Unit tests, linters, formatters, and type checks
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
	cd frontend && npm run check && npm run format:check && npm test

e2e: build ## Browser tests; set PW_WS_ENDPOINT to use the Playwright container
	cd frontend && npx playwright test

bench: build ## Time the large sample in a browser and print a table (see README)
	cd frontend && npx playwright test --config playwright.bench.config.ts

data: ## Regenerate the mock topologies in data/sample
	cd backend && uv run python -m sunstone.mockgen --preset small -o ../data/sample/small.yaml
	cd backend && uv run python -m sunstone.mockgen --preset large -o ../data/sample/large.yaml

api-types: ## Regenerate the frontend's API types after changing backend models
	cd backend && uv run python -c "import json, pathlib, sunstone.api as a; \
		print(json.dumps(a.create_app(pathlib.Path('../data/sample/small.yaml')).openapi(), indent=1))" \
		> ../frontend/openapi.json
	cd frontend && npm run gen:api
