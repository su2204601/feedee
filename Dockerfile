# ---- Frontend build stage: Vite + Tailwind ----
FROM node:22-slim AS frontend

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY vite.config.js tailwind.config.js postcss.config.js ./
COPY frontend/ frontend/
COPY templates/ templates/
RUN npm run build

# ---- Python dependency stage ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

# ---- Runtime stage ----
FROM python:3.13-slim

RUN addgroup --system app && adduser --system --ingroup app app

COPY --from=builder /usr/local /usr/local

WORKDIR /app
COPY . .

# Copy Vite build output
COPY --from=frontend /app/static/dist/ static/dist/

RUN chmod +x docker/entrypoint.sh

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
