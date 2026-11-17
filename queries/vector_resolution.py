"""
Vector-enhanced entity resolution.

Upgrades the Stage 2 confidence scoring in entity_resolution.py by adding
semantic similarity between SourceRecord narrative embeddings.

Scoring weights (must sum to 1.0):
    time_score     × 0.35   (linear decay over ±7200s)
    space_score    × 0.35   (linear decay over 50 km)
    semantic_score × 0.30   (cosine similarity of raw_text embeddings)

Requires SourceRecord.embedding to be populated first (etl/embeddings.py).
Pairs where either record lacks an embedding fall back to the original
Phase 3 two-factor scoring (time 40% + space 35% + shape 25%).

Outcomes — same thresholds as Phase 3:
    confidence >= 0.80  → MERGED_INTO   {method: 'SpatioTemporal_Vector'}
    0.60 <= conf < 0.80 → POTENTIAL_DUPLICATE

Run repoint_sources() from entity_resolution.py afterward.
"""

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

# ---------------------------------------------------------------------------
# Enhanced resolution — uses vector cosine where embeddings exist
# ---------------------------------------------------------------------------

RESOLVE_VECTOR_CYPHER = """
MATCH (s1:SourceRecord)-[:DESCRIBES]->(i1:Incident)-[:OCCURRED_AT]->(l1:Location)
MATCH (s2:SourceRecord)-[:DESCRIBES]->(i2:Incident)-[:OCCURRED_AT]->(l2:Location)
WHERE elementId(i1) < elementId(i2)
  AND l1.coords IS NOT NULL AND l2.coords IS NOT NULL
  AND abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) <= 7200
  AND point.distance(l1.coords, l2.coords) <= 50000

WITH i1, i2, s1, s2,
     1.0 - (abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) / 7200.0) AS time_score,
     1.0 - (point.distance(l1.coords, l2.coords) / 50000.0) AS space_score

WITH i1, i2, s1, s2, time_score, space_score,
     CASE
         WHEN s1.embedding IS NOT NULL AND s2.embedding IS NOT NULL
         THEN vector.similarity.cosine(s1.embedding, s2.embedding)
         ELSE null
     END AS semantic_score

WITH i1, i2,
     CASE
         WHEN semantic_score IS NOT NULL
         THEN (time_score * 0.35) + (space_score * 0.35) + (semantic_score * 0.30)
         ELSE (time_score * 0.40) + (space_score * 0.35)
     END AS confidence,
     CASE WHEN semantic_score IS NOT NULL THEN 'SpatioTemporal_Vector'
          ELSE 'SpatioTemporal_Fallback'
     END AS method

FOREACH (_ IN CASE WHEN confidence >= 0.80 THEN [1] ELSE [] END |
    MERGE (i2)-[:MERGED_INTO {
        confidence:   confidence,
        method:       method,
        resolved_at:  datetime()
    }]->(i1)
)
FOREACH (_ IN CASE WHEN confidence >= 0.60 AND confidence < 0.80 THEN [1] ELSE [] END |
    MERGE (i1)-[:POTENTIAL_DUPLICATE {
        confidence:  confidence,
        method:      method,
        flagged_at:  datetime()
    }]->(i2)
)
"""

# ---------------------------------------------------------------------------
# ANN nearest-neighbour lookup — find the closest incidents to a given one
# ---------------------------------------------------------------------------

ANN_CYPHER = """
MATCH (anchor:SourceRecord {source_name: $source_name, external_case_id: $ext_id})
WHERE anchor.embedding IS NOT NULL
CALL db.index.vector.queryNodes(
    'source_narrative_vec_idx',
    $top_k,
    anchor.embedding
) YIELD node AS candidate, score
WHERE candidate <> anchor
MATCH (candidate)-[:DESCRIBES]->(inc:Incident)
OPTIONAL MATCH (inc)-[:OCCURRED_AT]->(loc:Location)
RETURN candidate.source_name    AS source,
       candidate.external_case_id AS case_id,
       score                    AS cosine_similarity,
       inc.incident_id          AS incident_id,
       inc.datetime_utc         AS timestamp,
       loc.city + ', ' + loc.country AS location
ORDER BY score DESC
"""

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

STATS_CYPHER = """
MATCH (i:Incident)
WITH count(i) AS total_incidents
OPTIONAL MATCH ()-[m:MERGED_INTO]->()
WITH total_incidents,
     count(CASE WHEN m.method = 'SpatioTemporal_Vector'   THEN 1 END) AS vector_merged,
     count(CASE WHEN m.method = 'SpatioTemporal_Fallback' THEN 1 END) AS fallback_merged
OPTIONAL MATCH ()-[:POTENTIAL_DUPLICATE]->()
RETURN total_incidents, vector_merged, fallback_merged, count(*) AS flagged_for_review
"""


def run(uri: str = NEO4J_URI, auth: tuple = NEO4J_AUTH) -> dict:
    """
    Runs vector-enhanced entity resolution across all incidents.
    Returns result stats dict.
    """
    from etl.entity_resolution import REPOINT_CYPHER

    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            print("[vector_resolve] Running vector-enhanced resolution...")
            session.run(RESOLVE_VECTOR_CYPHER)

            print("[vector_resolve] Repointing SourceRecords to canonical incidents...")
            repoint = session.run(REPOINT_CYPHER).single()
            repointed = repoint["repointed"] if repoint else 0

            stats_row = session.run(STATS_CYPHER).single()
            result = dict(stats_row) if stats_row else {}
            result["repointed"] = repointed
            return result
    finally:
        driver.close()


def nearest_neighbours(
    source_name: str,
    ext_id: str,
    top_k: int = 10,
    uri: str = NEO4J_URI,
    auth: tuple = NEO4J_AUTH,
) -> list[dict]:
    """
    Returns the top_k most semantically similar SourceRecords to the given one,
    using the ANN vector index.
    """
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            result = session.run(
                ANN_CYPHER,
                source_name=source_name,
                ext_id=ext_id,
                top_k=top_k,
            )
            return [dict(r) for r in result]
    finally:
        driver.close()


def print_report(result: dict) -> None:
    print(f"\n{'='*60}")
    print("  VECTOR-ENHANCED ENTITY RESOLUTION RESULTS")
    print(f"{'='*60}")
    print(f"  Total incidents:        {result.get('total_incidents', 'n/a')}")
    print(f"  Vector-merged:          {result.get('vector_merged', 'n/a')}")
    print(f"  Fallback-merged:        {result.get('fallback_merged', 'n/a')}")
    print(f"  Flagged for review:     {result.get('flagged_for_review', 'n/a')}")
    print(f"  Sources repointed:      {result.get('repointed', 'n/a')}")


def print_neighbours(rows: list[dict], source_name: str, ext_id: str) -> None:
    if not rows:
        print(f"No neighbours found for {source_name}/{ext_id} (embedding may be missing).")
        return
    print(f"\n{'='*60}")
    print(f"  NEAREST NEIGHBOURS: {source_name}/{ext_id}")
    print(f"{'='*60}")
    for r in rows:
        ts = str(r.get("timestamp", ""))[:19]
        sim = f"{r['cosine_similarity']:.4f}"
        print(f"  [{sim}]  {r['source']}/{r['case_id']}  —  {r['location']}  {ts}")
