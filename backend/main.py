from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import get_settings

# Import all models so Base.metadata is populated before any route is called
import backend.models  # noqa: F401

app = FastAPI(title="Alpha Miner", version="0.1.0")

settings = get_settings()
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers are mounted here; add as each task completes
from backend.api import alphas, generate, submit, pool  # noqa: E402

app.include_router(alphas.router, prefix="/api")
app.include_router(generate.router, prefix="/api")
app.include_router(submit.router, prefix="/api")
app.include_router(pool.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
