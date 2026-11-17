"""
GET /stats — graph-wide summary counts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from neo4j import Session

from api.deps import get_session
from api.models import GraphStats, SourceBreakdown, ResolutionStats

router = APIRouter()

_STATS_CYPHER = """
MATCH (i:Incident)   WITH count(i) AS incidents
MATCH (s:SourceRecord) WITH incidents, count(s) AS source_records
MATCH (l:Location)   WITH incidents, source_records, count(l) AS locations
MATCH (o:Observer)   WITH incidents, source_records, locations, count(o) AS observers
MATCH (p:Phenomenon) WITH incidents, source_records, locations, observers, count(p) AS phenomena
OPTIONAL MATCH (ss:SensitiveSite)
RETURN incidents, source_records, locations, observers, phenomena,
       count(ss) AS sensitive_sites
"""

_SOURCE_BREAKDOWN_CYPHER = """
MATCH (s:SourceRecord)
RETURN s.source_name AS source, count(s) AS count
ORDER BY count DESC
"""

_RESOLUTION_CYPHER = """
MATCH ()-[m:MERGED_INTO]->() WITH count(m) AS auto_merged
MATCH ()-[p:POTENTIAL_DUPLICATE]->() WITH auto_merged, count(p) AS flagged
MATCH (s:SourceRecord WHERE s.embedding IS NOT NULL)
RETURN auto_merged, flagged AS flagged_for_review, count(s) AS embedded
"""

_LAST_INGEST_CYPHER = """
MATCH (s:SourceRecord)
WHERE s.loaded_at IS NOT NULL
RETURN max(s.loaded_at) AS last_ingest
"""


@router.get("/stats", response_model=GraphStats, summary="Graph summary counts")
def get_stats(session: Session = Depends(get_session)) -> GraphStats:
    # Main counts
    row = session.run(_STATS_CYPHER).single()
    counts = dict(row) if row else {}

    # Source breakdown
    sources = [
        SourceBreakdown(source=r["source"], count=r["count"])
        for r in session.run(_SOURCE_BREAKDOWN_CYPHER)
    ]

    # Resolution stats
    res_row = session.run(_RESOLUTION_CYPHER).single()
    resolution = ResolutionStats(**(dict(res_row) if res_row else {}))

    # Last ingest timestamp
    li_row = session.run(_LAST_INGEST_CYPHER).single()
    last_ingest = None
    if li_row and li_row["last_ingest"]:
        last_ingest = str(li_row["last_ingest"])

    return GraphStats(
        incidents=counts.get("incidents", 0),
        source_records=counts.get("source_records", 0),
        locations=counts.get("locations", 0),
        observers=counts.get("observers", 0),
        phenomena=counts.get("phenomena", 0),
        sensitive_sites=counts.get("sensitive_sites", 0),
        sources=sources,
        resolution=resolution,
        last_ingest=last_ingest,
    )
