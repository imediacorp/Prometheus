"""
FastAPI dependency — Neo4j session injection.

Each request gets a fresh driver session that is closed after the response.
The driver is created once at application startup via the lifespan context
in main.py and stored in app.state.driver.
"""

from __future__ import annotations

from typing import Generator
from fastapi import Depends, Request
from neo4j import Session


def get_driver(request: Request):
    return request.app.state.driver


def get_session(driver=Depends(get_driver)) -> Generator[Session, None, None]:
    with driver.session() as session:
        yield session
