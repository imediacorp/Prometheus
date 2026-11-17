"""
GET /incidents          — paginated incident list with filters
GET /incidents/{id}     — single incident with full detail
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from neo4j import Session

from api.deps import get_session
from api.models import (
    IncidentListResponse, IncidentDetail, IncidentSummary, PageMeta
)

router = APIRouter()

_LIST_CYPHER = """
MATCH (i:Incident)
OPTIONAL MATCH (i)-[:OCCURRED_AT]->(l:Location)
OPTIONAL MATCH (s:SourceRecord)-[:DESCRIBES]->(i)
OPTIONAL MATCH (i)-[:INVOLVES]->(ph:Phenomenon)
WITH i, l,
     collect(DISTINCT s.source_name)   AS sources,
     collect(DISTINCT ph.shape)        AS shapes,
     collect(DISTINCT ph.behavior)     AS behaviors,
     count(DISTINCT s)                 AS source_count
WHERE ($country  IS NULL OR toLower(l.country)  CONTAINS toLower($country))
  AND ($region   IS NULL OR toLower(l.region)   CONTAINS toLower($region))
  AND ($shape    IS NULL OR any(sh IN shapes WHERE toLower(sh) CONTAINS toLower($shape)))
  AND ($source   IS NULL OR any(src IN sources WHERE toLower(src) CONTAINS toLower($source)))
  AND ($date_from IS NULL OR i.datetime_utc >= datetime($date_from))
  AND ($date_to   IS NULL OR i.datetime_utc <= datetime($date_to))
RETURN i.incident_id        AS incident_id,
       toString(i.datetime_utc) AS datetime_utc,
       l.city               AS city,
       l.region             AS region,
       l.country            AS country,
       source_count,
       sources,
       shapes,
       behaviors,
       i.classification     AS classification
ORDER BY i.datetime_utc DESC
SKIP $offset LIMIT $limit
"""

_COUNT_CYPHER = """
MATCH (i:Incident)
OPTIONAL MATCH (i)-[:OCCURRED_AT]->(l:Location)
OPTIONAL MATCH (s:SourceRecord)-[:DESCRIBES]->(i)
OPTIONAL MATCH (i)-[:INVOLVES]->(ph:Phenomenon)
WITH i, l,
     collect(DISTINCT s.source_name) AS sources,
     collect(DISTINCT ph.shape)      AS shapes
WHERE ($country  IS NULL OR toLower(l.country) CONTAINS toLower($country))
  AND ($region   IS NULL OR toLower(l.region)  CONTAINS toLower($region))
  AND ($shape    IS NULL OR any(sh IN shapes WHERE toLower(sh) CONTAINS toLower($shape)))
  AND ($source   IS NULL OR any(src IN sources WHERE toLower(src) CONTAINS toLower($source)))
  AND ($date_from IS NULL OR i.datetime_utc >= datetime($date_from))
  AND ($date_to   IS NULL OR i.datetime_utc <= datetime($date_to))
RETURN count(i) AS total
"""

_DETAIL_CYPHER = """
MATCH (i:Incident {incident_id: $incident_id})
OPTIONAL MATCH (i)-[:OCCURRED_AT]->(l:Location)
OPTIONAL MATCH (s:SourceRecord)-[:DESCRIBES]->(i)
OPTIONAL MATCH (i)-[:INVOLVES]->(ph:Phenomenon)
OPTIONAL MATCH (i)<-[:OBSERVED_BY]-(obs:Observer)
OPTIONAL MATCH (i)-[:TAGGED_WITH]->(t:Tag)
WITH i, l,
     collect(DISTINCT {
         source_name: s.source_name,
         external_case_id: s.external_case_id,
         raw_text: s.raw_text,
         loaded_at: toString(s.loaded_at)
     }) AS source_records,
     collect(DISTINCT {shape: ph.shape, color: ph.color, behavior: ph.behavior, count: ph.count}) AS phenomena,
     collect(DISTINCT obs.observer_type) AS observer_types,
     collect(DISTINCT t.name)            AS tags,
     collect(DISTINCT s.source_name)     AS sources,
     collect(DISTINCT ph.shape)          AS shapes,
     collect(DISTINCT ph.behavior)       AS behaviors,
     count(DISTINCT s)                   AS source_count
RETURN i.incident_id            AS incident_id,
       toString(i.datetime_utc) AS datetime_utc,
       l.city                   AS city,
       l.region                 AS region,
       l.country                AS country,
       source_count,
       sources,
       shapes,
       behaviors,
       i.classification         AS classification,
       observer_types,
       i.summary                AS summary,
       tags,
       phenomena,
       source_records
"""


@router.get("", response_model=IncidentListResponse, summary="List incidents")
def list_incidents(
    country:   Optional[str] = Query(None),
    region:    Optional[str] = Query(None),
    shape:     Optional[str] = Query(None),
    source:    Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="ISO datetime, e.g. 2020-01-01"),
    date_to:   Optional[str] = Query(None, description="ISO datetime, e.g. 2024-12-31"),
    limit:     int = Query(50, ge=1, le=500),
    offset:    int = Query(0, ge=0),
    session:   Session = Depends(get_session),
) -> IncidentListResponse:
    params = dict(
        country=country, region=region, shape=shape, source=source,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    rows = session.run(_LIST_CYPHER, **params).data()
    total_row = session.run(_COUNT_CYPHER, **{k: v for k, v in params.items() if k not in ("limit", "offset")}).single()
    total = total_row["total"] if total_row else 0

    items = [IncidentSummary(**_coerce(r)) for r in rows]
    return IncidentListResponse(meta=PageMeta(total=total, limit=limit, offset=offset), items=items)


@router.get("/{incident_id}", response_model=IncidentDetail, summary="Get incident detail")
def get_incident(
    incident_id: str,
    session: Session = Depends(get_session),
) -> IncidentDetail:
    row = session.run(_DETAIL_CYPHER, incident_id=incident_id).single()
    if not row:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    return IncidentDetail(**_coerce(dict(row)))


def _coerce(row: dict) -> dict:
    """Ensure list fields are always lists, not None."""
    for field in ("sources", "shapes", "behaviors", "observer_types", "tags", "phenomena", "source_records"):
        if row.get(field) is None:
            row[field] = []
    return row
