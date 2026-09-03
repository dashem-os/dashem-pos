#!/usr/bin/env bash
# Local verification before publishing: the same ground the CI covers, run
# against the docker-compose stack. Any failure stops the script.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
BACKEND_CONTAINER="dashem-pos-backend"
IN_CONTAINER_API="http://127.0.0.1:8000"

step() { printf '\n=== %s ===\n' "$1"; }

step "Contêineres"
docker start "$BACKEND_CONTAINER" >/dev/null 2>&1 || true
for _ in $(seq 1 25); do
  if curl --fail --silent --max-time 3 http://localhost:8002/health >/dev/null; then
    echo "API local respondendo."
    break
  fi
  sleep 3
done
curl --fail --silent --max-time 3 http://localhost:8002/health >/dev/null

step "Alembic: migração reversível e sem drift"
docker exec "$BACKEND_CONTAINER" python -m alembic upgrade head
docker exec "$BACKEND_CONTAINER" python -m alembic check

step "Backend: suíte de testes"
docker exec -e TEST_BASE_URL="$IN_CONTAINER_API" "$BACKEND_CONTAINER" python -m pytest tests -q \
  --ignore=tests/test_frontend_api_contract.py \
  --ignore=tests/test_supabase_storage_adapter.py

step "Backend: testes que leem o repositório inteiro"
# The running container only mounts backend/, so these two read frontend/ and
# supabase/ through a throwaway container with the whole repository mounted.
IMAGE="$(docker inspect "$BACKEND_CONTAINER" --format '{{.Config.Image}}')"
NETWORK="$(docker inspect "$BACKEND_CONTAINER" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
DB_URL="$(docker inspect "$BACKEND_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^DATABASE_URL=' | cut -d= -f2-)"
MSYS_NO_PATHCONV=1 docker run --rm --network "$NETWORK" -v "$ROOT:/repo" -w /repo/backend \
  -e DATABASE_URL="$DB_URL" \
  -e SECRET_KEY="local-verify-secret-key-with-at-least-32-chars" \
  -e ENVIRONMENT=development -e AUTH_MODE=disabled \
  -e TEST_BASE_URL="http://${BACKEND_CONTAINER}:8000" \
  "$IMAGE" python -m pytest tests/test_frontend_api_contract.py tests/test_supabase_storage_adapter.py -q

step "Frontend: tipos, testes e build"
cd frontend
npx tsc --noEmit
npm test
npm run build

printf '\n=== Verificação local concluída sem falhas ===\n'
