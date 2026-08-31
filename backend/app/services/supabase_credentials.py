"""Server-only Supabase API key headers for modern and legacy credentials."""

from app.core.config import settings


class SupabaseCredentialError(RuntimeError):
    pass


def supabase_server_headers(*, content_type: str | None = None) -> dict[str, str]:
    key = (settings.SUPABASE_SECRET_KEY or "").strip()
    if not key:
        raise SupabaseCredentialError("A chave secreta do Supabase não está configurada.")
    if key.startswith("sb_publishable_"):
        raise SupabaseCredentialError("Uma chave pública não pode autorizar o backend do Supabase.")
    headers = {"apikey": key}
    # Modern sb_secret_* keys are opaque API keys, not JWTs. The Supabase
    # gateway translates the apikey for downstream services. Legacy
    # service_role JWTs still require the Bearer header.
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers
