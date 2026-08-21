from typing import Literal, Optional

from pydantic import ConfigDict, model_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")
    PROJECT_NAME: str = "Dashem POS"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    
    # Required in every environment. Local Docker values come from the root .env.
    DATABASE_URL: str
    SECRET_KEY: str

    # Supabase proves identity; Dashem remains the authorization authority.
    AUTH_MODE: Literal["required", "test", "disabled"] = "required"
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SECRET_KEY: Optional[str] = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    AUTH_TEST_SECRET: Optional[str] = None
    APP_URL: str = "http://localhost:5173"

    # Conservative defaults for small managed Postgres instances. These values
    # can be overridden per environment without changing application code.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    
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
        return self

settings = Settings()
