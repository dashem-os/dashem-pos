from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Dashem POS"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    
    # Required in every environment. Local Docker values come from the root .env.
    DATABASE_URL: str
    SECRET_KEY: str

    # Conservative defaults for small managed Postgres instances. These values
    # can be overridden per environment without changing application code.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
