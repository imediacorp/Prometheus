"""
GET /corroboration   — multi-agency corroborated incidents
GET /flaps           — spatio-temporal wave / cluster detection
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from neo4j import Session

from api.deps import get_session
from api.models import (
    CorroborationResponse, CorroboratedIncident, PageMeta,
    FlapResponse, FlapCluster,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Corroboration
# ---------------------------------------------------------------------------

_CORROBORATION_CYPHER = """
MATCH (s:SourceRecord)-[:DESCRIBES]->(i:Incident)
MATCH (s)-[:REPORTED_BY]->(o:Observer)
WITH i, collect(DISTINCT s.source_name) AS sources,
        collect(DISTINCT o.observer_type) AS observer_types
WHERE any(ot IN observer_types WHERE ot IN ['Civilian'])
  AND any(ot IN observer_types WHERE ot IN
      ['Military','Police','Radar','Pilot','Intelligence','Official'])
OPTIONAL MATCH (i)-[:OCCURRED_AT]->(l:Location)
OPTIONAL MATCH (i)-[:INVOLVES]->(ph:Phenomenon)
WITH i, sources, observer_types, l,
     collect(DISTINCT ph.behavior) AS behaviors
RETURN i.incident_id            AS incident_id,
       toString(i.datetime_utc) AS datetime_utc,
       coalesce(l.city + ', ' + l.country, l.country, l.city) AS location,
       sources,
       observer_types,
       behaviors,
       i.summary                AS summary
ORDER BY i.datetime_utc DESC
SKIP $offset LIMIT $limit
"""

_CORROBORATION_COUNT_CYPHER = """
MATCH (s:SourceRecord)-[:DESCRIBES]->(i:Incident)
MATCH (s)-[:REPORTED_BY]->(o:Observer)
WITH i, collect(DISTINCT o.observer_type) AS observer_types
WHERE any(ot IN observer_types WHERE ot IN ['Civilian'])
  AND any(ot IN observer_types WHERE ot IN
      ['Military','Police','Radar','Pilot','Intelligence','Official'])
RETURN count(i) AS total
"""


@router.get("/corroboration", response_model=CorroborationResponse,
            summary="Multi-agency corroborated incidents")
def get_corroboration(
    limit:   int = Query(50, ge=1, le=500),
    offset:  int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> CorroborationResponse:
    rows = session.run(_CORROBORATION_CYPHER, limit=limit, offset=offset).data()
    total_row = session.run(_CORROBORATION_COUNT_CYPHER).single()
    total = total_row["total"] if total_row else 0

    items = [
        CorroboratedIncident(
            incident_id=r["incident_id"],
            datetime_utc=r.get("datetime_utc"),
            location=r.get("location"),
            sources=r.get("sources") or [],
            observer_types=r.get("observer_types") or [],
            behaviors=r.get("behaviors") or [],
            summary=r.get("summary"),
        )
        for r in rows
    ]
    return CorroborationResponse(
        meta=PageMeta(total=total, limit=limit, offset=offset),
        items=items,
    )


# ---------------------------------------------------------------------------
# Flap detection
# ---------------------------------------------------------------------------

_FLAP_CYPHER = """
MATCH (anchor:Incident)-[:OCCURRED_AT]->(anchor_loc:Location)
WHERE anchor_loc.coords IS NOT NULL
MATCH (other:Incident)-[:OCCURRED_AT]->(other_loc:Location)
WHERE other_loc.coords IS NOT NULL
  AND elementId(anchor) <> elementId(other)
  AND point.distance(anchor_loc.coords, other_loc.coords) <= ($radius_km * 1000)
  AND duration.inDays(anchor.datetime_utc, other.datetime_utc).days >= 0
  AND duration.inDays(anchor.datetime_utc, other.datetime_utc).days <= $window_days
WITH anchor, anchor_loc,
     collect(DISTINCT elementId(other)) AS cluster_ids,
     count(DISTINCT other)              AS cluster_size
WHERE cluster_size >= $min_cluster
OPTIONAL MATCH (s:SourceRecord)-[:DESCRIBES]->(anchor)
OPTIONAL MATCH (anchor)-[:INVOLVES]->(ph:Phenomenon)
WITH anchor, anchor_loc, cluster_ids, cluster_size,
     collect(DISTINCT s.source_name)   AS sources,
     collect(DISTINCT ph.behavior)     AS behaviors
RETURN toString(anchor.datetime_utc)   AS window_start,
       coalesce(anchor_loc.region + ', ' + anchor_loc.country,
                anchor_loc.country,
                anchor_loc.city)       AS region,
       cluster_size,
       anchor.incident_id              AS anchor_incident,
       cluster_ids[0..5]               AS sample_ids,
       behaviors,
       sources
ORDER BY cluster_size DESC
LIMIT $limit
"""


@router.get("/flaps", response_model=FlapResponse,
            summary="Spatio-temporal flap / wave cluster detection")
def get_flaps(
    radius_km:   float = Query(100.0, ge=1.0,  le=5000.0),
    window_days: int   = Query(7,     ge=1,    le=365),
    min_cluster: int   = Query(5,     ge=2,    le=1000),
    limit:       int   = Query(50,    ge=1,    le=200),
    session: Session = Depends(get_session),
) -> FlapResponse:
    rows = session.run(
        _FLAP_CYPHER,
        radius_km=radius_km,
        window_days=window_days,
        min_cluster=min_cluster,
        limit=limit,
    ).data()

    items = [
        FlapCluster(
            window_start=r.get("window_start"),
            region=r.get("region"),
            cluster_size=r["cluster_size"],
            anchor_incident=r.get("anchor_incident"),
            sample_ids=r.get("sample_ids") or [],
            behaviors=r.get("behaviors") or [],
            sources=r.get("sources") or [],
        )
        for r in rows
    ]
    return FlapResponse(
        params={"radius_km": radius_km, "window_days": window_days, "min_cluster": min_cluster},
        items=items,
    )
