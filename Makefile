.PHONY: setup test test-backend run-backend run-frontend docker-up docker-down

setup:
	@echo "Setting up backend dependencies..."
	cd backend && python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt
	@echo "Setting up frontend dependencies..."
	cd frontend && npm install

test: test-backend

test-backend:
	cd backend && pytest -v

run-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

run-frontend:
	cd frontend && npm run dev

docker-up:
	docker-compose up --build -d

docker-down:
	docker-compose down
