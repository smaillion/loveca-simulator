FROM python:3.12-slim AS runtime

ARG LOVECA_DEPLOY_GIT_SHA=unknown
ARG LOVECA_DEPLOY_GIT_REF=unknown
ARG LOVECA_DEPLOY_GITHUB_RUN_ID=unknown
ARG LOVECA_DEPLOY_IMAGE=unknown
ARG LOVECA_DEPLOY_IMAGE_TAG=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LOVECA_CARD_DB=/app/data/loveca.sqlite3 \
    LOVECA_MATCH_DB=/app/runtime/matches.sqlite3 \
    LOVECA_IMAGE_CACHE=/app/data/card_images \
    LOVECA_WEB_DIST=/app/web/dist \
    LOVECA_DEPLOY_GIT_SHA=${LOVECA_DEPLOY_GIT_SHA} \
    LOVECA_DEPLOY_GIT_REF=${LOVECA_DEPLOY_GIT_REF} \
    LOVECA_DEPLOY_GITHUB_RUN_ID=${LOVECA_DEPLOY_GITHUB_RUN_ID} \
    LOVECA_DEPLOY_IMAGE=${LOVECA_DEPLOY_IMAGE} \
    LOVECA_DEPLOY_IMAGE_TAG=${LOVECA_DEPLOY_IMAGE_TAG}

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin loveca

COPY pyproject.toml README.md ./
COPY src ./src
COPY tools ./tools
COPY data_sources ./data_sources
COPY data/loveca.sqlite3 ./data/loveca.sqlite3
COPY data/loveca-db-manifest.json ./data/loveca-db-manifest.json

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

RUN mkdir -p /app/data /app/runtime /app/logs \
    && chown -R loveca:loveca /app

USER loveca

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3).read()"

CMD ["python", "-m", "uvicorn", "loveca.webapp:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
