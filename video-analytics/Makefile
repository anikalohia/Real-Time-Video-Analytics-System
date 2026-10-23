.PHONY: test lint up down dev-worker dev-ingestion dev-api dev-ep

test:
	pytest -q

lint:
	ruff check services

up:
	docker compose -f infra/docker-compose.yml up --build

down:
	docker compose -f infra/docker-compose.yml down -v

# Local development (requires redis + postgres running)
dev-ingestion:
	cd services/ingestion && python run.py

dev-worker:
	cd services/worker && python run.py

dev-ep:
	cd services/event-processor && python run.py

dev-api:
	cd services/api && uvicorn main:app --reload --port 8000

web:
	cd web && npm install && npm run dev
