"""
GET  /search/nearest      — ANN vector nearest-neighbour search
POST /incidents/search    — fulltext search over SourceRecord narratives
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from neo4j import Session

from api.deps import get_session
from api.models import NearestResponse, NearestNeighbour, FulltextResponse, FulltextResult, PageMeta

router = APIRouter()

# ---------------------------------------------------------------------------
# ANN nearest-neighbour
# ---------------------------------------------------------------------------

_ANN_CYPHER = """
MATCH (anchor:SourceRecord {source_name: $source_name, external_case_id: $ext_id})
WHERE anchor.embedding IS NOT NULL
CALL db.index.vector.queryNodes(
    'source_narrative_vec_idx',
    $top_k,
    anchor.embedding
) YIELD node AS candidate, score
WHERE candidate <> anchor
OPTIONAL MATCH (candidate)-[:DESCRIBES]->(inc:Incident)
OPTIONAL MATCH (inc)-[:OCCURRED_AT]->(loc:Location)
RETURN candidate.source_name       AS source,
       candidate.external_case_id  AS case_id,
       score                       AS cosine_similarity,
       inc.incident_id             AS incident_id,
       toString(inc.datetime_utc)  AS timestamp,
       coalesce(loc.city + ', ' + loc.country, loc.country, loc.city) AS location
ORDER BY score DESC
"""


@router.get("/nearest", response_model=NearestResponse,
            summary="Semantic nearest-neighbour search via ANN vector index")
def nearest_neighbours(
    source:  str = Query(..., description="Source name, e.g. NUFORC"),
    case_id: str = Query(..., description="External case ID"),
    top_k:   int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session),
) -> NearestResponse:
    # Verify anchor record has an embedding
    check = session.run(
        "MATCH (s:SourceRecord {source_name: $src, external_case_id: $cid}) "
        "RETURN s.embedding IS NOT NULL AS has_embedding LIMIT 1",
        src=source, cid=case_id,
    ).single()
    if not check:
        raise HTTPException(status_code=404, detail=f"SourceRecord {source}/{case_id} not found")
    if not check["has_embedding"]:
        raise HTTPException(
            status_code=422,
            detail=f"SourceRecord {source}/{case_id} has no embedding. Run `etl.ingest embed` first.",
        )

    rows = session.run(_ANN_CYPHER, source_name=source, ext_id=case_id, top_k=top_k).data()
    items = [
        NearestNeighbour(
            source=r["source"],
            case_id=r["case_id"],
            cosine_similarity=round(r["cosine_similarity"], 6),
            incident_id=r.get("incident_id"),
            timestamp=r.get("timestamp"),
            location=r.get("location"),
        )
        for r in rows
    ]
    return NearestResponse(anchor_source=source, anchor_case_id=case_id, top_k=top_k, items=items)


# ---------------------------------------------------------------------------
# Fulltext search
# ---------------------------------------------------------------------------

_FULLTEXT_CYPHER = """
CALL db.index.fulltext.queryNodes('source_narrative_ft_idx', $query)
YIELD node AS s, score
OPTIONAL MATCH (s)-[:DESCRIBES]->(i:Incident)
RETURN elementId(s)         AS source_record_id,
       s.source_name        AS source_name,
       s.external_case_id   AS external_case_id,
       score,
       left(s.raw_text, 300) AS snippet,
       i.incident_id        AS incident_id
ORDER BY score DESC
SKIP $offset LIMIT $limit
"""

_FULLTEXT_COUNT_CYPHER = """
CALL db.index.fulltext.queryNodes('source_narrative_ft_idx', $query)
YIELD node
RETURN count(node) AS total
"""


class FulltextQuery(BaseModel):
    q: str


@router.post("/fulltext", response_model=FulltextResponse,
             summary="Full-text search over SourceRecord narratives")
def fulltext_search(
    body:    FulltextQuery,
    limit:   int = Query(50, ge=1, le=500),
    offset:  int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> FulltextResponse:
    if not body.q or not body.q.strip():
        raise HTTPException(status_code=422, detail="Query string 'q' must not be empty")

    rows = session.run(_FULLTEXT_CYPHER, query=body.q, limit=limit, offset=offset).data()
    total_row = session.run(_FULLTEXT_COUNT_CYPHER, query=body.q).single()
    total = total_row["total"] if total_row else 0

    items = [
        FulltextResult(
            source_record_id=r["source_record_id"],
            source_name=r["source_name"],
            external_case_id=r["external_case_id"],
            score=round(r["score"], 6),
            snippet=r.get("snippet"),
            incident_id=r.get("incident_id"),
        )
        for r in rows
    ]
    return FulltextResponse(
        query=body.q,
        meta=PageMeta(total=total, limit=limit, offset=offset),
        items=items,
    )
