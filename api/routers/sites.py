"""
GET /sites                        — list sensitive sites with incident proximity counts
GET /sites/{name}/incidents       — incidents within radius of a named facility
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, HTTPException
from neo4j import Session

from api.deps import get_session
from api.models import SiteListResponse, SiteSummary, SiteIncidentResponse, SiteIncident, PageMeta

router = APIRouter()

_SITE_LIST_CYPHER = """
MATCH (ss:SensitiveSite)
OPTIONAL MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE l.coords IS NOT NULL AND ss.coords IS NOT NULL
  AND point.distance(ss.coords, l.coords) <= ($radius_km * 1000)
WITH ss,
     ss.latitude  AS lat,
     ss.longitude AS lon,
     count(i)     AS incident_count
RETURN ss.name      AS site_name,
       ss.site_type AS site_type,
       lat, lon,
       incident_count
ORDER BY incident_count DESC
"""

_SITE_INCIDENTS_CYPHER = """
MATCH (ss:SensitiveSite {name: $site_name})
WHERE ss.coords IS NOT NULL
MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE l.coords IS NOT NULL
  AND point.distance(ss.coords, l.coords) <= ($radius_km * 1000)
OPTIONAL MATCH (s:SourceRecord)-[:DESCRIBES]->(i)
OPTIONAL MATCH (i)-[:INVOLVES]->(ph:Phenomenon)
WITH i, l,
     round(point.distance(ss.coords, l.coords) / 1000.0 * 10) / 10 AS distance_km,
     collect(DISTINCT s.source_name) AS sources,
     collect(DISTINCT ph.shape)      AS shapes,
     collect(DISTINCT ph.behavior)   AS behaviors
RETURN i.incident_id            AS incident_id,
       toString(i.datetime_utc) AS datetime_utc,
       distance_km,
       sources,
       shapes,
       behaviors,
       i.summary                AS summary
ORDER BY distance_km ASC, i.datetime_utc DESC
SKIP $offset LIMIT $limit
"""

_SITE_INCIDENTS_COUNT_CYPHER = """
MATCH (ss:SensitiveSite {name: $site_name})
WHERE ss.coords IS NOT NULL
MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE l.coords IS NOT NULL
  AND point.distance(ss.coords, l.coords) <= ($radius_km * 1000)
RETURN count(i) AS total
"""


@router.get("", response_model=SiteListResponse,
            summary="List sensitive sites with incident counts")
def list_sites(
    radius_km: float = Query(25.0, ge=1.0, le=1000.0),
    session: Session = Depends(get_session),
) -> SiteListResponse:
    rows = session.run(_SITE_LIST_CYPHER, radius_km=radius_km).data()
    items = [
        SiteSummary(
            site_name=r["site_name"],
            site_type=r.get("site_type"),
            latitude=r.get("lat"),
            longitude=r.get("lon"),
            incident_count=r["incident_count"],
        )
        for r in rows
    ]
    return SiteListResponse(radius_km=radius_km, items=items)


@router.get("/{site_name}/incidents", response_model=SiteIncidentResponse,
            summary="Incidents near a named sensitive facility")
def site_incidents(
    site_name: str,
    radius_km: float = Query(25.0, ge=1.0, le=1000.0),
    limit:     int   = Query(50, ge=1, le=500),
    offset:    int   = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> SiteIncidentResponse:
    # Verify site exists
    check = session.run(
        "MATCH (ss:SensitiveSite {name: $name}) RETURN ss LIMIT 1",
        name=site_name,
    ).single()
    if not check:
        raise HTTPException(status_code=404, detail=f"Sensitive site '{site_name}' not found")

    rows = session.run(
        _SITE_INCIDENTS_CYPHER,
        site_name=site_name, radius_km=radius_km, limit=limit, offset=offset,
    ).data()
    total_row = session.run(
        _SITE_INCIDENTS_COUNT_CYPHER,
        site_name=site_name, radius_km=radius_km,
    ).single()
    total = total_row["total"] if total_row else 0

    items = [
        SiteIncident(
            incident_id=r["incident_id"],
            datetime_utc=r.get("datetime_utc"),
            distance_km=r.get("distance_km"),
            sources=r.get("sources") or [],
            shapes=r.get("shapes") or [],
            behaviors=r.get("behaviors") or [],
            summary=r.get("summary"),
        )
        for r in rows
    ]
    return SiteIncidentResponse(
        site_name=site_name,
        radius_km=radius_km,
        meta=PageMeta(total=total, limit=limit, offset=offset),
        items=items,
    )
