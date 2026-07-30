# Cistron — single free-tier service (API + built Studio SPA)
# Build: docker build -t cistron .
# Run:   docker run -p 8000:8000 cistron

FROM node:22-alpine AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin API when UI is served by FastAPI
ENV VITE_API_BASE=
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY cistron ./cistron
RUN pip install --upgrade pip && pip install -e ".[api]"

COPY --from=frontend /ui/dist ./frontend/dist

EXPOSE 8000
CMD ["sh", "-c", "uvicorn cistron.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
