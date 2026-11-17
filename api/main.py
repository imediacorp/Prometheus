"""
Prometheus UAP Reporting API — FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload --port 8000

OpenAPI docs available at:
    http://localhost:8000/docs
    http://localhost:8000/redoc

Environment variables:
    NEO4J_URI       bolt://localhost:7687
    NEO4J_USER      neo4j
    NEO4J_PASSWORD  (required)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

from api.routers import stats, incidents, analytics, sites, search


NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "$Istanbul#1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.driver = GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    app.state.driver.verify_connectivity()
    print(f"[api] Connected to Neo4j at {NEO4J_URI}")
    yield
    app.state.driver.close()
    print("[api] Neo4j driver closed")


app = FastAPI(
    title="Prometheus UAP Reporting API",
    description=(
        "REST API over the Prometheus Neo4j UAP incident graph. "
        "Exposes corroboration analysis, flap detection, sensitive-site proximity, "
        "semantic nearest-neighbour search, and fulltext search."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(stats.router,     prefix="",           tags=["Stats"])
app.include_router(incidents.router, prefix="/incidents", tags=["Incidents"])
app.include_router(analytics.router, prefix="",           tags=["Analytics"])
app.include_router(sites.router,     prefix="/sites",     tags=["Sensitive Sites"])
app.include_router(search.router,    prefix="/search",    tags=["Search"])


@app.get("/", include_in_schema=False)
def root():
    return {"service": "Prometheus UAP API", "docs": "/docs"}
