.PHONY: up down clean build test lint fmt smoke bench web-test web-build typecheck local-e2e

up:
	docker compose up --build -d
	@echo "Waiting for the stack to become healthy..."
	@docker compose ps

down:
	docker compose down

clean:
	docker compose down -v --remove-orphans

build:
	docker compose build

test:
	pytest -q

lint:
	ruff check services scripts benchmarks
	ruff format --check services scripts benchmarks

fmt:
	ruff check --fix services scripts benchmarks
	ruff format services scripts benchmarks

typecheck:
	cd web && npm run typecheck

web-test: typecheck

web-build:
	cd web && npm run build

smoke:
	bash scripts/smoke.sh

bench:
	python benchmarks/load_test.py --help

local-e2e:
	python scripts/local_pipeline.py --backend mock --seconds 20

# Local development (requires redis + postgres running)
dev-ingestion:
	cd services/ingestion && python run.py --manager

dev-worker:
	cd services/worker && python run.py

dev-ep:
	cd services/event-processor && python run.py

dev-api:
	cd services/api && uvicorn main:app --reload --port 8000

web:
	cd web && npm install && npm run dev
