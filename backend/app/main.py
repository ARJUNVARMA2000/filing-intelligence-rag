import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import chat, documents, health

app = FastAPI(
    title="Financial Research API",
    description="Source-grounded financial research answers and document evidence.",
    version="1.0.0",
)

# Configure CORS - allow frontend URL from environment or default to localhost
# Railway will set FRONTEND_URL environment variable
frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:8501")
allowed_origins = list(
    dict.fromkeys([frontend_url, "http://localhost:8501", "http://127.0.0.1:8501"])
)

# Add CORS middleware to allow PDF.js to load PDFs
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


@app.get("/")
def root() -> dict:
    return {"name": "Financial Research API", "version": app.version}


app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(documents.router, tags=["documents"])
