from dataclasses import dataclass
from typing import Any, Optional
import uuid

import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient

from app.core.config import settings


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    email: Optional[str]
    session_id: Optional[str]
    assurance_level: str
    claims: dict[str, Any]
    provider: Optional[str] = None
    legacy_user_id: Optional[uuid.UUID] = None
    bypass: bool = False


_jwks_client: Optional[PyJWKClient] = None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate a Supabase access token (or an isolated local test token)."""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        if unverified.get("iss") == "dashem-operational":
            return jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                audience="dashem-pos",
                issuer="dashem-operational",
                options={"require": ["exp", "iat", "sub", "aud", "iss", "tenant_id", "store_id", "membership_id"]},
            )
        if settings.AUTH_MODE == "test":
            if not settings.AUTH_TEST_SECRET:
                raise RuntimeError("AUTH_TEST_SECRET is required in test auth mode")
            return jwt.decode(
                token,
                settings.AUTH_TEST_SECRET,
                algorithms=["HS256"],
                audience=settings.SUPABASE_JWT_AUDIENCE,
                options={"require": ["exp", "sub", "aud"]},
            )

        if not settings.supabase_jwks_url or not settings.supabase_issuer:
            raise RuntimeError("SUPABASE_URL is required when authentication is enabled")

        global _jwks_client
        if _jwks_client is None:
            _jwks_client = PyJWKClient(settings.supabase_jwks_url, cache_keys=True)
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience=settings.SUPABASE_JWT_AUDIENCE,
            issuer=settings.supabase_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except RuntimeError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Authentication token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Invalid authentication token.") from exc


def get_current_principal(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
) -> AuthPrincipal:
    if settings.AUTH_MODE == "disabled":
        legacy_user_id = None
        if x_user_id:
            try:
                legacy_user_id = uuid.UUID(x_user_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid X-User-ID UUID.") from exc
        return AuthPrincipal(
            subject="local-auth-bypass",
            email=None,
            session_id=None,
            assurance_level="aal1",
            claims={},
            provider="local",
            legacy_user_id=legacy_user_id,
            bypass=True,
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized("Bearer authentication is required.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _unauthorized("Bearer authentication is required.")

    claims = decode_access_token(token)
    subject = claims.get("sub")
    if not subject:
        raise _unauthorized("Authentication token has no subject.")
    return AuthPrincipal(
        subject=str(subject),
        email=claims.get("email"),
        session_id=claims.get("session_id"),
        assurance_level=claims.get("aal", "aal1"),
        claims=claims,
        provider=(claims.get("app_metadata") or {}).get("provider"),
        legacy_user_id=uuid.UUID(str(subject)) if (claims.get("app_metadata") or {}).get("provider") == "operational" else None,
    )
