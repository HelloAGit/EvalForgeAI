.PHONY: setup test test-backend test-frontend run-backend run-worker run-frontend docker-up docker-down docker-build

setup:
	@echo "Setting up backend dependencies..."
	cd backend && python3 -m venv venv && . venv/bin/activate && pip install -r requirements-dev.txt
	@echo "Setting up frontend dependencies..."
	cd frontend && npm install

test: test-backend test-frontend

test-backend:
	cd backend && python3 -m pytest -v

test-frontend:
	cd frontend && npm test

run-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

run-worker:
	cd backend && python3 -m app.worker

run-frontend:
	cd frontend && npm run dev

docker-build:
	docker compose build

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
