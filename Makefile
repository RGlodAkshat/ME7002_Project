.PHONY: setup up down logs ps test build clean

setup:
	@test -f .env || cp .env.example .env
	@python3 infra/prepare-secrets.py .env --database

up: setup
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=150

ps:
	docker compose ps

test: setup
	docker compose run --rm -v ./backend/tests:/app/tests:ro -v ./configs:/configs:ro backend pytest

build:
	docker compose build

# Removes containers but deliberately preserves database/evidence volumes.
clean:
	docker compose down --remove-orphans
