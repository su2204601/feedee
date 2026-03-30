.PHONY: help dev up down logs build test migrate shell worker \
       prod-up prod-down prod-logs prod-build prod-migrate prod-shell \
       backup backup-dev backup-prod restore-dev restore-prod \
       lint fmt clean \
       fe-install fe-dev fe-build

# -------------------------------------------------------------------
# Variables
# -------------------------------------------------------------------
COMPOSE         := docker compose
COMPOSE_PROD    := docker compose -f compose.prod.yaml
TIMESTAMP       := $(shell date +%Y%m%d_%H%M%S)
BACKUP_DIR      := backups

# -------------------------------------------------------------------
# Help
# -------------------------------------------------------------------
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ===================================================================
#  Development
# ===================================================================
dev: ## Start dev environment (foreground)
	$(COMPOSE) up --build

up: ## Start dev environment (background)
	$(COMPOSE) up --build -d

down: ## Stop dev environment
	$(COMPOSE) down

logs: ## Tail dev logs
	$(COMPOSE) logs -f

build: ## Build dev images
	$(COMPOSE) build

test: ## Run Django tests
	uv run python manage.py test apps.rssapp

migrate: ## Run Django migrations (local)
	uv run python manage.py migrate

shell: ## Open Django shell (local)
	uv run python manage.py shell

worker: ## Run RSS worker locally
	go run rss_worker/main.go

# ===================================================================
#  Production
# ===================================================================
prod-up: ## Start production environment
	$(COMPOSE_PROD) up --build -d

prod-down: ## Stop production environment
	$(COMPOSE_PROD) down

prod-logs: ## Tail production logs
	$(COMPOSE_PROD) logs -f

prod-build: ## Build production images
	$(COMPOSE_PROD) build

prod-migrate: ## Run migrations in production
	$(COMPOSE_PROD) exec web python manage.py migrate --noinput

prod-shell: ## Open Django shell in production
	$(COMPOSE_PROD) exec web python manage.py shell

# ===================================================================
#  Backup
# ===================================================================
backup-dev: ## Backup dev SQLite database
	@mkdir -p $(BACKUP_DIR)/dev
	cp db.sqlite3 $(BACKUP_DIR)/dev/db_$(TIMESTAMP).sqlite3
	@echo "✓ Dev backup: $(BACKUP_DIR)/dev/db_$(TIMESTAMP).sqlite3"

backup-prod: ## Backup production PostgreSQL database
	@mkdir -p $(BACKUP_DIR)/prod
	$(COMPOSE_PROD) exec -T db pg_dump \
		-U $${POSTGRES_USER:-feedee} \
		-d $${POSTGRES_DB:-feedee} \
		--clean --if-exists \
		| gzip > $(BACKUP_DIR)/prod/db_$(TIMESTAMP).sql.gz
	@echo "✓ Prod backup: $(BACKUP_DIR)/prod/db_$(TIMESTAMP).sql.gz"

backup: backup-dev ## Alias: backup dev database

restore-dev: ## Restore dev SQLite (usage: make restore-dev FILE=backups/dev/db_xxx.sqlite3)
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make restore-dev FILE=backups/dev/db_xxx.sqlite3"; \
		echo "Available backups:"; ls -1t $(BACKUP_DIR)/dev/ 2>/dev/null || echo "  (none)"; \
		exit 1; \
	fi
	cp $(FILE) db.sqlite3
	@echo "✓ Restored from $(FILE)"

restore-prod: ## Restore production PostgreSQL (usage: make restore-prod FILE=backups/prod/db_xxx.sql.gz)
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make restore-prod FILE=backups/prod/db_xxx.sql.gz"; \
		echo "Available backups:"; ls -1t $(BACKUP_DIR)/prod/ 2>/dev/null || echo "  (none)"; \
		exit 1; \
	fi
	gunzip -c $(FILE) | $(COMPOSE_PROD) exec -T db psql \
		-U $${POSTGRES_USER:-feedee} \
		-d $${POSTGRES_DB:-feedee}
	@echo "✓ Restored from $(FILE)"

list-backups: ## List all backups
	@echo "=== Dev backups ==="
	@ls -1t $(BACKUP_DIR)/dev/ 2>/dev/null || echo "  (none)"
	@echo ""
	@echo "=== Prod backups ==="
	@ls -1t $(BACKUP_DIR)/prod/ 2>/dev/null || echo "  (none)"

# ===================================================================
#  Frontend (Vite + Tailwind)
# ===================================================================
fe-install: ## Install frontend dependencies
	npm install

fe-dev: ## Start Vite dev server (HMR)
	npm run dev

fe-build: ## Build frontend for production
	npm run build

# ===================================================================
#  Utilities
# ===================================================================
clean: ## Remove Python cache and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.py[co]' -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info

superuser: ## Create Django superuser (local)
	uv run python manage.py createsuperuser

collectstatic: ## Collect static files (local)
	uv run python manage.py collectstatic --noinput
