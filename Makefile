.DEFAULT_GOAL := help
PY ?= python
COMPOSE := docker compose

.PHONY: help install run migrate superuser test cov lint format check up down logs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies and git hooks
	$(PY) -m pip install -r requirements-dev.txt
	pre-commit install

run: ## Run the dev server
	$(PY) manage.py runserver

migrate: ## Apply database migrations
	$(PY) manage.py migrate

superuser: ## Create an admin account
	$(PY) manage.py createsuperuser

test: ## Run the test suite
	pytest

cov: ## Run tests with coverage report
	pytest --cov --cov-report=term-missing

lint: ## Lint and check formatting
	ruff check .
	ruff format --check .

format: ## Auto-fix lint issues and format code
	ruff check --fix .
	ruff format .

check: lint ## Lint + Django checks + migrations + tests
	$(PY) manage.py check
	$(PY) manage.py makemigrations --check --dry-run
	pytest

up: ## Build and start the Docker stack (API on :18300)
	$(COMPOSE) up -d --build

down: ## Stop the Docker stack and remove volumes
	$(COMPOSE) down -v

logs: ## Tail container logs
	$(COMPOSE) logs -f web
