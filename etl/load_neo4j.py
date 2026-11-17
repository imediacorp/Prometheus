"""
Batched upsert loader for normalized UAP records into Neo4j.
Each record dict is the common format produced by normalize_nuforc / normalize_geipan.
"""

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

# Creates SourceRecord, Incident, Location, Observer, Phenomenon in one pass.
# Observer is CREATE (not MERGE) so each report gets its own node; dedup runs later.
BATCH_UPSERT_CYPHER = """
UNWIND $batch AS row

MERGE (src:SourceRecord {source_name: row.source_name, external_case_id: row.external_case_id})
SET src.raw_text             = row.raw_text,
    src.agency_classification = row.classification

MERGE (inc:Incident {incident_id: row.temp_incident_id})
SET inc.datetime_utc      = datetime(row.datetime_utc),
    inc.duration_seconds  = row.duration_seconds

MERGE (src)-[:DESCRIBES]->(inc)

FOREACH (_ IN CASE WHEN row.lat IS NOT NULL AND row.lon IS NOT NULL THEN [1] ELSE [] END |
    MERGE (loc:Location {city: row.city, region: row.region, country: row.country})
    SET loc.coords = point({latitude: row.lat, longitude: row.lon})
    MERGE (inc)-[:OCCURRED_AT]->(loc)
)

CREATE (obs:Observer {type: row.observer_type})
MERGE (obs)-[:REPORTED]->(inc)

CREATE (p:Phenomenon {shape: row.shape})
MERGE (inc)-[:INVOLVED]->(p)
"""


def load(records: list[dict], batch_size: int = 1000, uri: str = NEO4J_URI, auth: tuple = NEO4J_AUTH) -> int:
    """
    Loads records into Neo4j in batches.
    Returns total number of records processed.
    """
    driver = GraphDatabase.driver(uri, auth=auth)
    total = 0
    try:
        with driver.session() as session:
            for i in range(0, len(records), batch_size):
                batch = records[i: i + batch_size]
                session.run(BATCH_UPSERT_CYPHER, batch=batch)
                total += len(batch)
                print(f"  Loaded {total}/{len(records)} records...")
    finally:
        driver.close()
    return total
