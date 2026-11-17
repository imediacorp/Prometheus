"""
Query B: Proximity to Military Bases & Nuclear Infrastructure

Finds unresolved incidents occurring within a configurable radius (default 25 km)
of a :SensitiveSite node. Sites must be loaded separately via load_sites().

SensitiveSite node properties:
    name       — facility name
    category   — e.g. "Air_Base", "Nuclear_Plant", "Naval_Range", "Research_Facility"
    coords     — point({latitude, longitude})

Includes a helper to seed a starter set of well-known sites for testing.
"""

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

CYPHER = """
MATCH (site:SensitiveSite)
MATCH (inc:Incident)-[:OCCURRED_AT]->(loc:Location)
WHERE loc.coords IS NOT NULL
  AND point.distance(site.coords, loc.coords) <= $radius_m
OPTIONAL MATCH (inc)-[:INVOLVED]->(p:Phenomenon)-[:EXHIBITED]->(t:Tag)
OPTIONAL MATCH (src:SourceRecord)-[:DESCRIBES]->(inc)
WITH site,
     inc,
     loc,
     round(point.distance(site.coords, loc.coords) / 1000.0, 2) AS distance_km,
     collect(DISTINCT t.name)       AS behaviors,
     collect(DISTINCT src.agency_classification) AS classifications
RETURN site.name                    AS facility,
       site.category                AS facility_type,
       inc.incident_id              AS incident_id,
       inc.datetime_utc             AS timestamp,
       loc.city + ', ' + loc.country AS location,
       distance_km,
       behaviors,
       classifications
ORDER BY facility, distance_km ASC
"""

AGGREGATE_CYPHER = """
MATCH (site:SensitiveSite)
MATCH (inc:Incident)-[:OCCURRED_AT]->(loc:Location)
WHERE loc.coords IS NOT NULL
  AND point.distance(site.coords, loc.coords) <= $radius_m
OPTIONAL MATCH (inc)-[:INVOLVED]->(p:Phenomenon)-[:EXHIBITED]->(t:Tag)
RETURN site.name                                                 AS facility,
       site.category                                             AS facility_type,
       count(DISTINCT inc)                                       AS total_incidents,
       round(avg(point.distance(site.coords, loc.coords)) / 1000.0, 2) AS avg_distance_km,
       collect(DISTINCT t.name)                                  AS observed_behaviors
ORDER BY total_incidents DESC
"""

SEED_SITES_CYPHER = """
UNWIND $sites AS s
MERGE (site:SensitiveSite {name: s.name})
SET site.category = s.category,
    site.coords   = point({latitude: s.lat, longitude: s.lon})
"""

# A starter set of publicly known sensitive sites for seeding/testing
STARTER_SITES = [
    {"name": "Area 51 / Groom Lake",         "category": "Air_Base",          "lat": 37.2350,  "lon": -115.8111},
    {"name": "Wright-Patterson AFB",          "category": "Air_Base",          "lat": 39.8261,  "lon": -84.0484},
    {"name": "Malmstrom AFB",                 "category": "Air_Base",          "lat": 47.5091,  "lon": -111.1869},
    {"name": "Minot AFB",                     "category": "Air_Base",          "lat": 48.4156,  "lon": -101.3580},
    {"name": "Nellis AFB",                    "category": "Air_Base",          "lat": 36.2358,  "lon": -115.0342},
    {"name": "Indian Point Nuclear Plant",    "category": "Nuclear_Plant",     "lat": 41.2698,  "lon": -73.9524},
    {"name": "Pickering Nuclear Station",     "category": "Nuclear_Plant",     "lat": 43.8102,  "lon": -79.0671},
    {"name": "NAS Fallon",                    "category": "Naval_Range",       "lat": 39.4166,  "lon": -118.7005},
    {"name": "RAAF Exmouth (North West Cape)","category": "Naval_Range",       "lat": -21.8197, "lon": 114.1659},
    {"name": "Porton Down",                   "category": "Research_Facility", "lat": 51.1297,  "lon": -1.7139},
]


def load_sites(
    sites: list[dict] | None = None,
    uri: str = NEO4J_URI,
    auth: tuple = NEO4J_AUTH,
) -> int:
    """
    Upserts SensitiveSite nodes. Uses STARTER_SITES if no list is provided.
    Returns count of sites loaded.
    """
    payload = sites if sites is not None else STARTER_SITES
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            session.run(SEED_SITES_CYPHER, sites=payload)
        return len(payload)
    finally:
        driver.close()


def run(
    radius_km: float = 25.0,
    aggregate: bool = False,
    uri: str = NEO4J_URI,
    auth: tuple = NEO4J_AUTH,
) -> list[dict]:
    """
    Returns incidents within radius_km of any SensitiveSite.
    Set aggregate=True for a per-facility summary instead of individual incidents.
    """
    driver = GraphDatabase.driver(uri, auth=auth)
    radius_m = radius_km * 1000.0
    cypher = AGGREGATE_CYPHER if aggregate else CYPHER
    try:
        with driver.session() as session:
            result = session.run(cypher, radius_m=radius_m)
            return [dict(r) for r in result]
    finally:
        driver.close()


def print_report(rows: list[dict], aggregate: bool = False) -> None:
    if not rows:
        print("No incidents found near sensitive sites.")
        return
    label = "FACILITY SUMMARY" if aggregate else "INCIDENTS NEAR SENSITIVE SITES"
    print(f"\n{'='*70}")
    print(f"  {label}  ({len(rows)} results)")
    print(f"{'='*70}")
    if aggregate:
        for r in rows:
            print(f"\n{r['facility']}  [{r['facility_type']}]")
            print(f"  Incidents:    {r['total_incidents']}")
            print(f"  Avg distance: {r['avg_distance_km']} km")
            if r["observed_behaviors"]:
                print(f"  Behaviors:    {', '.join(r['observed_behaviors'])}")
    else:
        for r in rows:
            ts = str(r.get("timestamp", ""))[:19]
            print(f"\n[{r['incident_id']}]  {ts}  —  {r['location']}  ({r['distance_km']} km)")
            print(f"  Facility: {r['facility']}  [{r['facility_type']}]")
            if r["behaviors"]:
                print(f"  Behaviors: {', '.join(r['behaviors'])}")
