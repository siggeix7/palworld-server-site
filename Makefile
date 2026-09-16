IMAGE ?= palworld-server-site
TAG ?= latest
IMAGE_BASENAME := $(notdir $(IMAGE))
SITE_PORT ?= 8080
PRIVATE_PORT ?= 8081
TMP_IMAGE ?= /tmp/$(IMAGE_BASENAME)-$(TAG).tar
PYTHON ?= python3
FRONTEND_DIR := web/live-map
RUFF := $(PYTHON) -m ruff
VCS_REF ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || printf unknown)
POSTGRES_TEST_IMAGE ?= postgres:17-bookworm@sha256:9b18b78397054fce88a9552e9d5a3ad5bb7fd258c5b3cc1c5028e46373d6ea8f
POSTGRES_TEST_CONTAINER ?= palworld-server-site-test-postgres
POSTGRES_TEST_PORT ?= 55432

TEST_ENV := DJANGO_SECRET_KEY=test-key PLAYER_HASH_SECRET=test-player-key \
	PUBLIC_SITE_URL=https://testserver SITE_ADMIN_USERS=admin@example.com \
	PRIVATE_API_TOKEN=test-private-token \
	PRIVACY_CONTROLLER_NAME=test-controller PRIVACY_CONTACT_EMAIL=privacy@testserver \
	DATABASE_PATH=/tmp/palworld-server-site-test.sqlite3

.PHONY: all setup build docker-build save run shell lint format check test test-ops test-postgres \
	test-frontend test-all security clean

all: save

setup:
	$(PYTHON) -m pip install --requirement requirements.txt
	$(PYTHON) -m pip install --requirement requirements-dev.txt
	cd $(FRONTEND_DIR) && npm ci

build:
	docker build --build-arg APP_VERSION=$(TAG) --build-arg VCS_REF=$(VCS_REF) -t $(IMAGE):$(TAG) .

docker-build: build

save: build
	docker save $(IMAGE):$(TAG) -o $(TMP_IMAGE)
	@printf 'Container image saved in %s\n' "$(TMP_IMAGE)"

run: build
	docker run --rm \
		-p $(SITE_PORT):8000 \
		-p $(PRIVATE_PORT):8001 \
		-e DJANGO_SECRET_KEY=local-development-secret \
		-e PLAYER_HASH_SECRET=local-player-hash-secret \
		-e PRIVATE_API_TOKEN=local-private-token \
		-e PALWORLD_API_URL=http://host.docker.internal:8212 \
		-e PALWORLD_API_PASSWORD=local-admin-password \
		-e PALWORLD_API_ALLOW_INSECURE_HTTP=true \
		-e PUBLIC_SITE_URL=https://localhost \
		-e SITE_ADMIN_USERS=admin@example.com \
		-e PRIVACY_CONTROLLER_NAME=local-development-controller \
		-e PRIVACY_CONTACT_EMAIL=privacy@localhost \
		-e COLLECTOR_LOCK_PATH=/data/palworld-collector.lock \
		-e RETENTION_CLEANUP_LOCK_PATH=/data/palworld-retention-cleanup.lock \
		-e WEEKLY_REPORT_SCHEDULER_LOCK_PATH=/data/palworld-weekly-scheduler.lock \
		-v palworld-site-data:/data \
		$(IMAGE):$(TAG)

shell: build
	docker run --rm -it \
		-e DJANGO_SECRET_KEY=local-development-secret \
		-e PLAYER_HASH_SECRET=local-player-hash-secret \
		-e PRIVATE_API_TOKEN=local-private-token \
		-e PUBLIC_SITE_URL=https://localhost \
		-e SITE_ADMIN_USERS=admin@example.com \
		-e PRIVACY_CONTROLLER_NAME=local-development-controller \
		-e PRIVACY_CONTACT_EMAIL=privacy@localhost \
		-v palworld-site-data:/data \
		--entrypoint python3 \
		$(IMAGE):$(TAG) web/manage.py shell

lint:
	$(RUFF) check web/dashboard web/palworld_site ops/PalworldGuildSync
	$(RUFF) format --check web/dashboard web/palworld_site ops/PalworldGuildSync

format:
	$(RUFF) format web/dashboard web/palworld_site ops/PalworldGuildSync

test:
	$(TEST_ENV) $(PYTHON) web/manage.py check
	$(TEST_ENV) $(PYTHON) web/manage.py makemigrations --check --dry-run
	$(TEST_ENV) $(PYTHON) web/manage.py test dashboard

test-ops:
	bash -n docker/postgres-entrypoint.sh ops/PalworldGuildSync/install.sh \
		ops/PalworldGuildSync/guild_sync_cron.sh \
		ops/PalworldGuildSync/backup.sh ops/PalworldGuildSync/restore.sh
	test -x docker/postgres-entrypoint.sh
	for script in ops/PalworldGuildSync/install.sh ops/PalworldGuildSync/guild_sync_cron.sh \
		ops/PalworldGuildSync/backup.sh ops/PalworldGuildSync/restore.sh; do test -x "$$script"; done
	test -f ops/PalworldGuildSync/cron.d/palworld-guild-sync
	test -f ops/PalworldGuildSync/logrotate.d/palworld-guild-sync

test-postgres:
	@set -eu; \
		container='$(POSTGRES_TEST_CONTAINER)'; \
		docker rm -f "$$container" >/dev/null 2>&1 || true; \
		docker run --rm -d --name "$$container" \
			-e POSTGRES_PASSWORD=test-postgres-password \
			-e POSTGRES_DB=postgres \
			-p 127.0.0.1:$(POSTGRES_TEST_PORT):5432 \
			$(POSTGRES_TEST_IMAGE) >/dev/null; \
		cleanup() { docker rm -f "$$container" >/dev/null 2>&1 || true; }; \
		trap cleanup EXIT INT TERM; \
		ready=false; \
		for attempt in $$(seq 1 60); do \
			if docker exec "$$container" pg_isready -U postgres -d postgres >/dev/null 2>&1; then ready=true; break; fi; \
			sleep 1; \
		done; \
		if [ "$$ready" != true ]; then printf 'PostgreSQL did not become ready\n' >&2; exit 1; fi; \
		$(TEST_ENV) DATABASE_ENGINE=postgresql DB_HOST=127.0.0.1 DB_PORT=$(POSTGRES_TEST_PORT) \
		DB_NAME=postgres DB_USER=postgres DB_PASSWORD=test-postgres-password \
		$(PYTHON) web/manage.py test dashboard

test-frontend:
	cd $(FRONTEND_DIR) && npm ci && npm run generate:api && npm run check && npm test && npm run build

security:
	pip-audit --requirement requirements.txt
	cd $(FRONTEND_DIR) && npm ci && npm audit --audit-level=high

check: lint test test-ops test-frontend

test-all: check security

clean:
	rm -f $(TMP_IMAGE)
