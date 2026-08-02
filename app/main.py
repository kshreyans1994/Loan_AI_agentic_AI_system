"""FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.logging_config import configure_logging

# Must run before any other module's logger is used, so every log line
# — including ones emitted during router import — uses the configured
# format/level rather than Python's unconfigured default.
configure_logging()
logger = logging.getLogger("app.http")

app = FastAPI(
    title="AI-Powered Loan Application Chat Agent",
    description="Multi-plugin, RAG-grounded loan assistant built with LangGraph + Groq + pgvector",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Request-level log line — method, path, status, latency — for
    every HTTP call, independent of the graph-level node tracing in
    app/graph/node_tracing.py. This catches things node tracing can't:
    a request that 4xx's before ever reaching the graph (bad JSON, a
    missing field), or one that never returns at all.
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        f"{request.method} {request.url.path} -> {response.status_code}",
        extra={"duration_ms": duration_ms},
    )
    return response


app.include_router(router, prefix="/api/v1")
