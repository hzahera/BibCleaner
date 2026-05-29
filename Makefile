.DEFAULT_GOAL := help

.PHONY: help setup requirements format lint test compose-up

help: ## Show available targets
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install runtime and dev dependencies
	uv sync --all-groups

requirements: ## Generate requirements.txt from pyproject dependencies
	uv export --format requirements-txt --no-hashes -o requirements.txt

format: ## Format project code with ruff
	uv run ruff format bibcleaner providers tests

lint: ## Run lint checks with ruff
	uv run ruff check bibcleaner providers tests

test: ## Run test suite
	uv run pytest

compose-up: ## Start the API and frontend compose stack
	docker compose up --build
