from typing import Literal, Optional

from pydantic import ConfigDict, field_validator, model_validator
from pydantic_settings import BaseSettings

MANAGED_STORAGE_BUCKETS = (
    "tenant-assets", "tenant-documents", "tenant-exports", "tenant-integrations",
)

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")
    PROJECT_NAME: str = "Dashem POS"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    
    # Required in every environment. Local Docker values come from the root .env.
    DATABASE_URL: str
    DATABASE_ADMIN_URL: Optional[str] = None
    RUNTIME_DB_ROLE: str = "dashem_runtime"
    SECRET_KEY: str

    # Supabase proves identity; Dashem remains the authorization authority.
    AUTH_MODE: Literal["required", "test", "disabled"] = "required"
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SECRET_KEY: Optional[str] = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    AUTH_TEST_SECRET: Optional[str] = None
    APP_URL: str = "http://localhost:5173"

    # Optional provider-neutral ingress for SaaS receipt confirmations. The
    # endpoint remains unavailable until both values are configured; it never
    # acknowledges a provider event without authenticated evidence.
    SAAS_PAYMENT_WEBHOOK_SECRET: Optional[str] = None
    SAAS_PAYMENT_WEBHOOK_ACTOR_ID: Optional[str] = None

    # Conservative defaults for small managed Postgres instances. These values
    # can be overridden per environment without changing application code.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    # Storage quota enforcement is fail-closed unless a complete provider
    # inventory is newer than this configurable policy window.
    STORAGE_MEASUREMENT_MAX_AGE_HOURS: int = 24
    STORAGE_RESERVATION_TTL_MINUTES: int = 15
    STORAGE_TENANT_WARNING_PERCENT: int = 70
    STORAGE_TENANT_CRITICAL_PERCENT: int = 85
    STORAGE_MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    SUPABASE_STORAGE_BUCKETS: str = ",".join(MANAGED_STORAGE_BUCKETS)
    # Declared from the actual provider plan. None means unavailable; the app
    # never assumes that a Supabase project owns the current Free allowance.
    SUPABASE_STORAGE_CAPACITY_BYTES: Optional[int] = None
    SUPABASE_STORAGE_RESERVED_MARGIN_BYTES: int = 0

    @field_validator("SUPABASE_STORAGE_CAPACITY_BYTES", mode="before")
    @classmethod
    def empty_capacity_is_not_configured(cls, value):
        return None if value == "" else value

    @property
    def supabase_storage_buckets(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            item.strip() for item in self.SUPABASE_STORAGE_BUCKETS.split(",") if item.strip()
        ))

    @property
    def supabase_storage_configured(self) -> bool:
        return bool(
            self.SUPABASE_URL
            and self.SUPABASE_SECRET_KEY
            and self.SUPABASE_STORAGE_CAPACITY_BYTES
            and self.supabase_storage_buckets
        )
    
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    @property
    def supabase_issuer(self) -> Optional[str]:
        return f"{self.SUPABASE_URL.rstrip('/')}/auth/v1" if self.SUPABASE_URL else None

    @property
    def supabase_jwks_url(self) -> Optional[str]:
        issuer = self.supabase_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else None

    @model_validator(mode="after")
    def validate_auth_configuration(self):
        if self.ENVIRONMENT.lower() in {"production", "prod"} and self.AUTH_MODE != "required":
            raise ValueError("AUTH_MODE must be 'required' in production")
        if self.ENVIRONMENT.lower() in {"production", "prod"} and not self.SUPABASE_URL:
            raise ValueError("SUPABASE_URL is required in production")
        if self.AUTH_MODE == "test" and not self.AUTH_TEST_SECRET:
            raise ValueError("AUTH_TEST_SECRET is required in test auth mode")
        if not 1 <= self.STORAGE_TENANT_WARNING_PERCENT < self.STORAGE_TENANT_CRITICAL_PERCENT < 100:
            raise ValueError("Storage warning and critical percentages must satisfy 1 <= warning < critical < 100")
        if self.STORAGE_MAX_UPLOAD_BYTES <= 0:
            raise ValueError("STORAGE_MAX_UPLOAD_BYTES must be greater than zero")
        if self.SUPABASE_STORAGE_RESERVED_MARGIN_BYTES < 0:
            raise ValueError("SUPABASE_STORAGE_RESERVED_MARGIN_BYTES cannot be negative")
        if self.SUPABASE_STORAGE_CAPACITY_BYTES is not None:
            if self.SUPABASE_STORAGE_CAPACITY_BYTES <= 0:
                raise ValueError("SUPABASE_STORAGE_CAPACITY_BYTES must be greater than zero when configured")
            if self.SUPABASE_STORAGE_RESERVED_MARGIN_BYTES >= self.SUPABASE_STORAGE_CAPACITY_BYTES:
                raise ValueError("The Supabase Storage reserved margin must be smaller than its capacity")
        if set(self.supabase_storage_buckets) != set(MANAGED_STORAGE_BUCKETS):
            raise ValueError(
                "SUPABASE_STORAGE_BUCKETS must match the versioned restrictive policies in supabase/migrations"
            )
        return self

settings = Settings()
