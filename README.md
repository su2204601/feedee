# Feedee

Django + Go based RSS ingestion system.

## Features

- Web dashboard with Tailwind-based UI for feed subscription and article browsing
- API endpoints for worker integration
  - `GET /api/feeds/`
  - `POST /api/articles/ingest/`
- Go worker with concurrent RSS fetch, dedup within batch, and ingest retries

## Run

1. Sync Python deps

```bash
uv sync
```

2. Migrate DB

```bash
.venv/bin/python manage.py migrate
```

3. Start Django

```bash
.venv/bin/python manage.py runserver
```

4. Run worker (new terminal)

```bash
go run rss_worker/main.go
```

## Worker environment variables

- `DJANGO_BASE_URL` (default: `http://127.0.0.1:8000`)
- `HTTP_TIMEOUT_SECONDS` (default: `15`)
- `MAX_CONCURRENCY` (default: `8`)
- `INGEST_MAX_RETRY` (default: `3`)
- `INGEST_INITIAL_BACKOFF_SECONDS` (default: `1`)

## Structure

- `config/`: Django project settings and URL root
- `apps/rssapp/`: app code (models, views, serializers, forms, urls)
- `templates/`: UI templates
- `rss_worker/`: Go ingestion worker
