from fastapi import FastAPI

from api.logging_config import configure_logging
from api.middleware import CorrelationIdMiddleware
from api.schemas import HealthResponse

configure_logging()

app = FastAPI(title="MarginMaestro API")
app.add_middleware(CorrelationIdMiddleware)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    return HealthResponse(status="ready")
