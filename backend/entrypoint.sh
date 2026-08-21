#!/bin/sh
set -e

echo "[Dashem POS Entrypoint] Running Database Migrations (alembic upgrade head)..."
alembic upgrade head

echo "[Dashem POS Entrypoint] Migrations completed successfully! Starting Uvicorn API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
