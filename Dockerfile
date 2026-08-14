FROM node:24-alpine AS live-map-build

WORKDIR /build
COPY web/live-map/package.json web/live-map/package-lock.json ./
RUN npm ci
COPY web/dashboard/api/openapi.json /dashboard/api/openapi.json
COPY web/live-map/ ./
RUN npm run generate:api
RUN npm run check
RUN npm test
RUN npm run build

FROM python:3.13.5-slim-bookworm AS map-assets

WORKDIR /build
COPY docker/map-tiles-requirements.txt docker/generate-map-tiles.py ./tools/
COPY web/dashboard/static/dashboard/live-map/maps ./maps
RUN python -m pip install --disable-pip-version-check --no-cache-dir \
      --only-binary=Pillow --requirement tools/map-tiles-requirements.txt \
    && printf '%s  %s\n%s  %s\n' \
      '9961632d5c38a0a67fd18713fa63af0ac6f192e71fadeb5ba53ae696b8914dd1' \
      'maps/palpagos.jpg' \
      '77fee7b2bb90fa62f26eeb862396d54dbc8c7d2f0f5b12339c12585474f7c521' \
      'maps/world-tree.jpg' | sha256sum --check --strict \
    && python tools/generate-map-tiles.py --if-needed maps \
    && printf '%s  %s\n' \
      'b1454293f3258c2db74fc51f984e864452554df9527d9146dea6992872afc261' \
      'maps/manifest.json' | sha256sum --check --strict

FROM rockylinux/rockylinux:10

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
    PATH=/app:$PATH

WORKDIR /app

RUN dnf -y upgrade --security \
    && dnf -y install python3-pip shadow-utils \
    && dnf clean all \
    && ln -sf python3 /usr/bin/python

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

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
       PUBLIC_SITE_URL=https://build.invalid \
       SITE_ADMIN_USERS=build-admin@example.invalid \
       python3 web/manage.py collectstatic --noinput
COPY --from=map-assets /build/maps/*.webp ./staticfiles/dashboard/live-map/maps/

VOLUME ["/data"]
EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=35s --retries=3 \
    CMD python3 -c "import os,urllib.request; h={'X-Forwarded-Proto':'https'}; [urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+os.environ[p]+'/healthz/',headers=h),timeout=4).read() for p in ('SITE_INTERNAL_PORT','PRIVATE_INTERNAL_PORT')]"

USER palworld-site

ENTRYPOINT ["/app/docker/entrypoint.sh"]
