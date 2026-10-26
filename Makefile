.PHONY: up down logs backend-shell migrate seed test lint prod-up prod-update prod-backup prod-smoke prod-bundle

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

backend-shell:
	docker compose exec backend bash

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python -m app.seed

test:
	cd backend && python3 -m pytest -q

lint:
	cd frontend && npm run lint

# --- production (RHEL VM) -- see docs/DEPLOYMENT_RHEL.md ---
prod-up:
	deploy/netsphere up
prod-update:
	deploy/netsphere update
prod-backup:
	deploy/netsphere backup
prod-smoke:
	deploy/netsphere smoke
prod-bundle:
	deploy/netsphere bundle amd64
