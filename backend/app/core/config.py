from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Dashem POS"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    
    # Required in every environment. Local Docker values come from the root .env.
    DATABASE_URL: str
    SECRET_KEY: str
    
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
