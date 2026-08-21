from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.middleware import CorrelationIdMiddleware
from app.api.v1.router import api_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware for React frontend on http://localhost:5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# X-Correlation-ID Middleware
app.add_middleware(CorrelationIdMiddleware)

# Healthcheck Endpoint
@app.get("/health", tags=["Health"])
def healthcheck():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT
    }

# API v1 Router
app.include_router(api_router, prefix="/api/v1")
