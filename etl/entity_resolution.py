"""
Two-stage entity resolution pipeline.

Stage 1 — Candidate blocking: spatial-temporal window (±2h, ≤50 km).
Stage 2 — Confidence scoring:
    time_score  * 0.40  (linear decay over 7200s)
    space_score * 0.35  (linear decay over 50 km)
    shape_match * 0.25  (exact shape equality on Phenomenon nodes)

Outcomes:
    confidence >= 0.80  → MERGED_INTO   (auto-merge)
    0.60 <= conf < 0.80 → POTENTIAL_DUPLICATE (flagged for review)

Run repoint_sources() afterward to re-link SourceRecords from merged
duplicates to their canonical Incident.
"""

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

# ---------------------------------------------------------------------------
# Stage 1 + 2: block, score, and write relationship in a single Cypher pass
# ---------------------------------------------------------------------------

RESOLVE_CYPHER = """
MATCH (i1:Incident)-[:OCCURRED_AT]->(l1:Location)
MATCH (i2:Incident)-[:OCCURRED_AT]->(l2:Location)
WHERE elementId(i1) < elementId(i2)
  AND l1.coords IS NOT NULL AND l2.coords IS NOT NULL
  AND abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) <= 7200
  AND point.distance(l1.coords, l2.coords) <= 50000

WITH i1, i2,
     1.0 - (abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) / 7200.0) AS time_score,
     1.0 - (point.distance(l1.coords, l2.coords) / 50000.0) AS space_score

OPTIONAL MATCH (i1)-[:INVOLVED]->(p1:Phenomenon)
OPTIONAL MATCH (i2)-[:INVOLVED]->(p2:Phenomenon)

WITH i1, i2,
     (time_score * 0.40) + (space_score * 0.35) +
     (CASE WHEN p1 IS NOT NULL AND p2 IS NOT NULL AND p1.shape = p2.shape THEN 0.25 ELSE 0.0 END)
     AS confidence

FOREACH (_ IN CASE WHEN confidence >= 0.80 THEN [1] ELSE [] END |
    MERGE (i2)-[:MERGED_INTO {confidence: confidence, resolved_at: datetime()}]->(i1)
)
FOREACH (_ IN CASE WHEN confidence >= 0.60 AND confidence < 0.80 THEN [1] ELSE [] END |
    MERGE (i1)-[:POTENTIAL_DUPLICATE {confidence: confidence, flagged_at: datetime()}]->(i2)
)
"""

# ---------------------------------------------------------------------------
# Re-point SourceRecords away from merged duplicates to canonical Incident
# ---------------------------------------------------------------------------

REPOINT_CYPHER = """
MATCH (src:SourceRecord)-[oldRel:DESCRIBES]->(dup:Incident)-[:MERGED_INTO]->(canonical:Incident)
WHERE NOT (src)-[:DESCRIBES]->(canonical)
MERGE (src)-[:DESCRIBES]->(canonical)
DELETE oldRel
RETURN count(src) AS repointed
"""

# ---------------------------------------------------------------------------
# Stats queries for reporting
# ---------------------------------------------------------------------------

STATS_CYPHER = """
MATCH (i:Incident)
WITH count(i) AS total_incidents
OPTIONAL MATCH ()-[:MERGED_INTO]->()
WITH total_incidents, count(*) AS auto_merged
OPTIONAL MATCH ()-[:POTENTIAL_DUPLICATE]->()
RETURN total_incidents, auto_merged, count(*) AS flagged_for_review
"""


def run(uri: str = NEO4J_URI, auth: tuple = NEO4J_AUTH) -> dict:
    """
    Runs the full entity resolution pipeline.
    Returns a dict with counts: auto_merged, flagged_for_review, repointed.
    """
    driver = GraphDatabase.driver(uri, auth=auth)
    result = {}
    try:
        with driver.session() as session:
            print("[resolve] Stage 1+2: blocking, scoring, writing relationships...")
            session.run(RESOLVE_CYPHER)

            print("[resolve] Repointing SourceRecords to canonical incidents...")
            repoint_result = session.run(REPOINT_CYPHER).single()
            result["repointed"] = repoint_result["repointed"] if repoint_result else 0

            print("[resolve] Collecting stats...")
            stats = session.run(STATS_CYPHER).single()
            if stats:
                result["total_incidents"] = stats["total_incidents"]
                result["auto_merged"] = stats["auto_merged"]
                result["flagged_for_review"] = stats["flagged_for_review"]

    finally:
        driver.close()

    return result


def stats(uri: str = NEO4J_URI, auth: tuple = NEO4J_AUTH) -> dict:
    """Returns current resolution stats without running the pipeline."""
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            row = session.run(STATS_CYPHER).single()
            return dict(row) if row else {}
    finally:
        driver.close()
