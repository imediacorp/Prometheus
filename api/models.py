"""
Pydantic response schemas for the Prometheus reporting API.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared / primitives
# ---------------------------------------------------------------------------

class PageMeta(BaseModel):
    total: int | None = None
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Graph stats
# ---------------------------------------------------------------------------

class SourceBreakdown(BaseModel):
    source: str
    count: int


class ResolutionStats(BaseModel):
    auto_merged: int = 0
    flagged_for_review: int = 0
    embedded: int = 0


class GraphStats(BaseModel):
    incidents: int
    source_records: int
    locations: int
    observers: int
    phenomena: int
    sensitive_sites: int
    sources: list[SourceBreakdown] = Field(default_factory=list)
    resolution: ResolutionStats = Field(default_factory=ResolutionStats)
    last_ingest: str | None = None


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

class IncidentSummary(BaseModel):
    incident_id: str
    datetime_utc: str | None
    city: str | None
    region: str | None
    country: str | None
    source_count: int = 0
    sources: list[str] = Field(default_factory=list)
    shapes: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    classification: str | None = None


class IncidentDetail(IncidentSummary):
    observer_types: list[str] = Field(default_factory=list)
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    phenomena: list[dict[str, Any]] = Field(default_factory=list)
    source_records: list[dict[str, Any]] = Field(default_factory=list)


class IncidentListResponse(BaseModel):
    meta: PageMeta
    items: list[IncidentSummary]


# ---------------------------------------------------------------------------
# Corroboration
# ---------------------------------------------------------------------------

class CorroboratedIncident(BaseModel):
    incident_id: str
    datetime_utc: str | None
    location: str | None
    sources: list[str]
    observer_types: list[str]
    behaviors: list[str] = Field(default_factory=list)
    summary: str | None


class CorroborationResponse(BaseModel):
    meta: PageMeta
    items: list[CorroboratedIncident]


# ---------------------------------------------------------------------------
# Flap detection
# ---------------------------------------------------------------------------

class FlapCluster(BaseModel):
    window_start: str | None
    region: str | None
    cluster_size: int
    anchor_incident: str | None
    sample_ids: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class FlapResponse(BaseModel):
    params: dict[str, Any]
    items: list[FlapCluster]


# ---------------------------------------------------------------------------
# Sensitive sites
# ---------------------------------------------------------------------------

class SiteSummary(BaseModel):
    site_name: str
    site_type: str | None
    latitude: float | None
    longitude: float | None
    incident_count: int


class SiteIncident(BaseModel):
    incident_id: str
    datetime_utc: str | None
    distance_km: float | None
    sources: list[str] = Field(default_factory=list)
    shapes: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    summary: str | None


class SiteListResponse(BaseModel):
    radius_km: float
    items: list[SiteSummary]


class SiteIncidentResponse(BaseModel):
    site_name: str
    radius_km: float
    meta: PageMeta
    items: list[SiteIncident]


# ---------------------------------------------------------------------------
# Vector / semantic search
# ---------------------------------------------------------------------------

class NearestNeighbour(BaseModel):
    source: str
    case_id: str
    cosine_similarity: float
    incident_id: str | None
    timestamp: str | None
    location: str | None


class NearestResponse(BaseModel):
    anchor_source: str
    anchor_case_id: str
    top_k: int
    items: list[NearestNeighbour]


class FulltextResult(BaseModel):
    source_record_id: str
    source_name: str
    external_case_id: str
    score: float
    snippet: str | None
    incident_id: str | None


class FulltextResponse(BaseModel):
    query: str
    meta: PageMeta
    items: list[FulltextResult]
