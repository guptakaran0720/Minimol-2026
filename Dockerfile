# syntax=docker/dockerfile:1
# One image runs any node. The dashboard is built in a Node stage and served by the node at /ui.

FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

FROM python:3.11-slim AS node
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY node/ node/
COPY bench/ bench/
COPY --from=ui /ui/dist ui/dist
ENV DATA_DIR=/data PORT=8000 BIND_HOST=0.0.0.0 MDNS=0
EXPOSE 8000
HEALTHCHECK --interval=3s --timeout=2s --start-period=5s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/stats', timeout=2)"
CMD ["python", "-m", "node.main"]

# `docker compose run --rm unit`: the full pytest suite on Python 3.11, like CI.
FROM node AS test
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ tests/
CMD ["python", "-m", "pytest", "-q", "-p", "no:warnings", "tests/"]
