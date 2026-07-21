FROM rockylinux/rockylinux:10

ARG APP_VERSION=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=palworld_site.settings \
    APP_VERSION=${APP_VERSION} \
    DATABASE_PATH=/data/palworld-site.sqlite3 \
    STATIC_ROOT=/app/staticfiles \
    SITE_INTERNAL_PORT=8000 \
    INGEST_INTERNAL_PORT=8001 \
    TIME_ZONE=Europe/Rome \
    PATH=/app:$PATH

WORKDIR /app

RUN dnf -y install python3-pip shadow-utils \
    && dnf clean all \
    && ln -sf python3 /usr/bin/python

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

RUN useradd --create-home --uid 1000 palworld-site \
    && mkdir -p /data /app/staticfiles \
    && chown -R palworld-site:palworld-site /data /app/staticfiles

COPY . .
RUN chmod +x /app/docker/entrypoint.sh \
    && DJANGO_SECRET_KEY=build-collectstatic-key \
       PUBLIC_SITE_URL=https://build.invalid \
       SITE_ADMIN_USERS=build-admin@example.invalid \
       ZABBIX_SOURCE_HOST=build-host \
       python3 web/manage.py collectstatic --noinput

VOLUME ["/data"]
EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=6s --start-period=35s --retries=3 \
    CMD python3 -c "import os,urllib.request; h={'X-Forwarded-Proto':'https'}; [urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+os.environ[p]+'/healthz/',headers=h),timeout=4).read() for p in ('SITE_INTERNAL_PORT','INGEST_INTERNAL_PORT')]"

USER palworld-site

ENTRYPOINT ["/app/docker/entrypoint.sh"]
