"""
Query A: High-Credibility Multi-Agency Corroboration

Finds incidents independently documented by both a civilian source AND
at least one official channel (Military, Police, or Radar observer).
Returns results ranked by most recent first.
"""

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

CYPHER = """
MATCH (src1:SourceRecord)-[:DESCRIBES]->(inc:Incident)<-[:DESCRIBES]-(src2:SourceRecord)
WHERE src1.source_name <> src2.source_name
MATCH (inc)<-[:REPORTED]-(obs:Observer)
WITH inc,
     collect(DISTINCT src1.source_name) + collect(DISTINCT src2.source_name) AS sources,
     collect(DISTINCT obs.type) AS observer_types
WHERE ('Military'  IN observer_types
    OR 'Police'    IN observer_types
    OR 'Radar'     IN observer_types
    OR 'Pilot'     IN observer_types
    OR 'Intelligence' IN observer_types)
  AND 'Civilian' IN observer_types
OPTIONAL MATCH (inc)-[:OCCURRED_AT]->(loc:Location)
OPTIONAL MATCH (inc)-[:INVOLVED]->(p:Phenomenon)-[:EXHIBITED]->(t:Tag)
RETURN inc.incident_id                               AS id,
       inc.datetime_utc                              AS timestamp,
       coalesce(loc.city + ', ' + loc.country, 'Unknown') AS location,
       [s IN sources WHERE s IS NOT NULL | s]        AS sources,
       observer_types,
       collect(DISTINCT t.name)                      AS behaviors,
       inc.summary                                   AS summary
ORDER BY timestamp DESC
LIMIT $limit
"""


def run(limit: int = 50, uri: str = NEO4J_URI, auth: tuple = NEO4J_AUTH) -> list[dict]:
    """
    Returns incidents corroborated by both civilian and official observers
    from at least two distinct source agencies.
    """
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            result = session.run(CYPHER, limit=limit)
            return [dict(r) for r in result]
    finally:
        driver.close()


def print_report(rows: list[dict]) -> None:
    if not rows:
        print("No corroborated incidents found.")
        return
    print(f"\n{'='*70}")
    print(f"  MULTI-AGENCY CORROBORATED INCIDENTS  ({len(rows)} results)")
    print(f"{'='*70}")
    for r in rows:
        ts = str(r.get("timestamp", "Unknown date"))[:19]
        print(f"\n[{r['id']}]  {ts}  —  {r['location']}")
        print(f"  Sources:   {', '.join(r['sources'])}")
        print(f"  Observers: {', '.join(r['observer_types'])}")
        if r["behaviors"]:
            print(f"  Behaviors: {', '.join(r['behaviors'])}")
        if r.get("summary"):
            print(f"  Summary:   {r['summary'][:120]}")
