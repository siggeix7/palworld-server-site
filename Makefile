IMAGE ?= palworld-server-site
TAG ?= latest
IMAGE_BASENAME := $(notdir $(IMAGE))
SITE_PORT ?= 8080
PRIVATE_PORT ?= 8081
TMP_IMAGE ?= /tmp/$(IMAGE_BASENAME)-$(TAG).tar
PYTHON ?= python3
TEST_ENV := DJANGO_SECRET_KEY=test-key PLAYER_HASH_SECRET=test-player-key \
	PUBLIC_SITE_URL=https://testserver SITE_ADMIN_USERS=admin@example.com \
	PRIVATE_API_TOKEN=test-private-token \
	DATABASE_PATH=/tmp/palworld-server-site-test.sqlite3

.PHONY: all build save run shell test clean

all: save

build:
	docker build --build-arg APP_VERSION=$(TAG) -t $(IMAGE):$(TAG) .

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
		-e PUBLIC_SITE_URL=https://localhost \
		-e SITE_ADMIN_USERS=admin@example.com \
		-v palworld-site-data:/data \
		$(IMAGE):$(TAG)

shell: build
	docker run --rm -it \
		-e DJANGO_SECRET_KEY=local-development-secret \
		-e PRIVATE_API_TOKEN=local-private-token \
		-e PUBLIC_SITE_URL=https://localhost \
		-e SITE_ADMIN_USERS=admin@example.com \
		-v palworld-site-data:/data \
		--entrypoint python3 \
		$(IMAGE):$(TAG) web/manage.py shell

test:
	$(TEST_ENV) $(PYTHON) web/manage.py check
	$(TEST_ENV) $(PYTHON) web/manage.py makemigrations --check --dry-run
	$(TEST_ENV) $(PYTHON) web/manage.py test dashboard

clean:
	rm -f $(TMP_IMAGE)
