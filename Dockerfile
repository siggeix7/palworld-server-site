FROM node:26-alpine@sha256:ef24c5053d50fdc3e4e56eb4e7ddb7861874ab0fdc797046ba897581deb8e868 AS live-map-build

WORKDIR /build
COPY web/live-map/package.json web/live-map/package-lock.json ./
RUN npm ci
COPY web/dashboard/api/openapi.json /dashboard/api/openapi.json
COPY web/live-map/ ./
RUN npm run generate:api
RUN npm run check
RUN npm test
RUN npm run build

FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS map-assets

WORKDIR /build
COPY docker/map-tiles-requirements.txt docker/generate-map-tiles.py ./tools/
COPY web/dashboard/static/dashboard/live-map/maps ./maps
RUN python -m pip install --disable-pip-version-check --no-cache-dir \
      --only-binary=Pillow --require-hashes --requirement tools/map-tiles-requirements.txt \
    && printf '%s  %s\n%s  %s\n' \
      '9961632d5c38a0a67fd18713fa63af0ac6f192e71fadeb5ba53ae696b8914dd1' \
      'maps/palpagos.jpg' \
      '77fee7b2bb90fa62f26eeb862396d54dbc8c7d2f0f5b12339c12585474f7c521' \
      'maps/world-tree.jpg' | sha256sum --check --strict \
    && python tools/generate-map-tiles.py --if-needed maps \
    && printf '%s  %s\n' \
      '9de64557908c4ff415bda9829836d05826b5de3a2929fa1b0621e522d7c8326d' \
      'maps/manifest.json' | sha256sum --check --strict

FROM rockylinux/rockylinux:10@sha256:827d37bc128288ccf160ee318bb3cb92d591164cb217e92f8bc61e3982ae1834

ARG APP_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="Palworld Server Observatory" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/siggeix7/palworld-server-site"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=palworld_site.settings \
    APP_VERSION=${APP_VERSION} \
    DATABASE_PATH=/data/palworld-site.sqlite3 \
    STATIC_ROOT=/app/staticfiles \
    SITE_INTERNAL_PORT=8000 \
    PRIVATE_INTERNAL_PORT=8001 \
    TIME_ZONE=Europe/Rome \
    COLLECTOR_LOCK_PATH=/data/palworld-collector.lock \
    RETENTION_CLEANUP_LOCK_PATH=/data/palworld-retention-cleanup.lock \
    WEEKLY_REPORT_SCHEDULER_LOCK_PATH=/data/palworld-weekly-scheduler.lock \
    PATH=/app:$PATH

WORKDIR /app

RUN sed -i \
      -e 's|^mirrorlist=|#mirrorlist=|' \
      -e 's|^#baseurl=http://dl.rockylinux.org/|baseurl=https://dl.rockylinux.org/|' \
      /etc/yum.repos.d/rocky.repo \
    && dnf -y upgrade --security \
    && dnf -y install python3-pip shadow-utils \
    && dnf clean all \
    && ln -sf python3 /usr/bin/python

COPY requirements.txt ./
RUN pip3 install --no-cache-dir --require-hashes -r requirements.txt

RUN useradd --create-home --uid 1000 palworld-site \
    && mkdir -p /data /app/staticfiles \
    && chown -R palworld-site:palworld-site /data /app/staticfiles \
    && chmod 0700 /data

COPY web/palworld_site/ ./web/palworld_site/
COPY web/dashboard/ ./web/dashboard/
COPY web/manage.py ./web/
COPY docker/ ./docker/
COPY --from=live-map-build /build/dist/ ./web/dashboard/static/dashboard/live-map/
RUN chmod +x /app/docker/entrypoint.sh \
    && DJANGO_SECRET_KEY=build-collectstatic-key \
       PLAYER_HASH_SECRET=build-collectstatic-player-hash-key \
       PUBLIC_SITE_URL=https://build.invalid \
       SITE_ADMIN_USERS=build-admin@example.invalid \
       PRIVACY_CONTROLLER_NAME=build-artifact-controller \
       PRIVACY_CONTACT_EMAIL=build@local \
       python3 web/manage.py collectstatic --noinput
COPY --from=map-assets /build/maps/*.webp ./staticfiles/dashboard/live-map/maps/

VOLUME ["/data"]
EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=35s --retries=3 \
    CMD python3 -c "import os,urllib.request; h={'X-Forwarded-Proto':'https'}; [urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+os.environ[p]+'/healthz/',headers=h),timeout=4).read() for p in ('SITE_INTERNAL_PORT','PRIVATE_INTERNAL_PORT')]"

USER palworld-site

ENTRYPOINT ["/app/docker/entrypoint.sh"]
