from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


def invite_user(*, email: str, full_name: str, tenant_id: str) -> dict[str, Any]:
    """Create a Supabase identity and ask Auth to deliver its invite.

    The administrative credential never leaves the backend. Delivery is owned
    by Supabase Auth and its configured SMTP provider (Resend in production).
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Convites aguardam a configuração segura do Supabase Admin no backend.",
        )

    redirect_to = f"{settings.APP_URL.rstrip('/')}/login?mode=invite"
    query = urlencode({"redirect_to": redirect_to})
    try:
        response = httpx.post(
            f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/invite?{query}",
            headers={
                "apikey": settings.SUPABASE_SECRET_KEY,
                "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "data": {"full_name": full_name, "tenant_id": tenant_id},
            },
            timeout=15.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O provedor de identidade não respondeu ao convite.",
        ) from exc

    if response.is_error:
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        detail = payload.get("msg") or payload.get("message") or payload.get("error_description")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail or "O provedor de identidade recusou o convite.",
        )

    payload = response.json()
    user = payload.get("user", payload)
    if not user.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="O provedor de identidade não retornou o usuário convidado.",
        )
    return user
