"""
Query C: Spatio-Temporal "Flap" Detection (Wave Clustering)

Identifies sudden regional spikes where at least `min_cluster` distinct incidents
occurred within `radius_km` of each other over a `window_days` rolling window.

A "flap" is a classic UAP research term for a geographic/temporal cluster of sightings
that exceeds the background rate — originally coined by researchers tracking 1950s waves.
"""

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

CYPHER = """
MATCH (i1:Incident)-[:OCCURRED_AT]->(l1:Location)
MATCH (i2:Incident)-[:OCCURRED_AT]->(l2:Location)
WHERE i1 <> i2
  AND l1.coords IS NOT NULL AND l2.coords IS NOT NULL
  AND duration.inDays(i1.datetime_utc, i2.datetime_utc).days >= 0
  AND duration.inDays(i1.datetime_utc, i2.datetime_utc).days <= $window_days
  AND point.distance(l1.coords, l2.coords) <= $radius_m

WITH i1, l1, count(DISTINCT i2) AS nearby_count, collect(DISTINCT i2.incident_id) AS cluster_ids
WHERE nearby_count >= $min_cluster - 1

OPTIONAL MATCH (i1)-[:OCCURRED_AT]->(l1)
OPTIONAL MATCH (i1)-[:INVOLVED]->(p:Phenomenon)-[:EXHIBITED]->(t:Tag)
OPTIONAL MATCH (src:SourceRecord)-[:DESCRIBES]->(i1)

RETURN date(i1.datetime_utc)                        AS window_start,
       l1.region + ', ' + l1.country               AS region,
       nearby_count + 1                             AS cluster_size,
       i1.incident_id                               AS anchor_incident,
       cluster_ids[0..9]                            AS sample_ids,
       collect(DISTINCT t.name)                     AS behaviors,
       collect(DISTINCT src.source_name)            AS sources
ORDER BY cluster_size DESC, window_start DESC
LIMIT $limit
"""


def run(
    radius_km: float = 100.0,
    window_days: int = 7,
    min_cluster: int = 5,
    limit: int = 50,
    uri: str = NEO4J_URI,
    auth: tuple = NEO4J_AUTH,
) -> list[dict]:
    """
    Returns flap clusters — regional incident spikes exceeding the threshold.

    Args:
        radius_km:   Geographic radius for grouping incidents (default 100 km).
        window_days: Rolling time window in days (default 7).
        min_cluster: Minimum incidents to constitute a flap (default 5).
        limit:       Max rows returned.
    """
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            result = session.run(
                CYPHER,
                radius_m=radius_km * 1000.0,
                window_days=window_days,
                min_cluster=min_cluster,
                limit=limit,
            )
            return [dict(r) for r in result]
    finally:
        driver.close()


def print_report(rows: list[dict], radius_km: float = 100.0, window_days: int = 7) -> None:
    if not rows:
        print(f"No flap clusters found (≥5 incidents / {radius_km} km / {window_days} days).")
        return
    print(f"\n{'='*70}")
    print(f"  UAP FLAP CLUSTERS  ({len(rows)} results)")
    print(f"  Params: {radius_km} km radius, {window_days}-day window, ≥5 incidents")
    print(f"{'='*70}")
    for r in rows:
        print(f"\n[FLAP]  {r['window_start']}  —  {r['region']}")
        print(f"  Cluster size: {r['cluster_size']} incidents")
        print(f"  Anchor:       {r['anchor_incident']}")
        if r.get("sample_ids"):
            ids = r["sample_ids"]
            print(f"  Sample IDs:   {', '.join(ids[:5])}" + (" ..." if len(ids) > 5 else ""))
        if r["behaviors"]:
            print(f"  Behaviors:    {', '.join(r['behaviors'])}")
        if r["sources"]:
            print(f"  Sources:      {', '.join(r['sources'])}")
