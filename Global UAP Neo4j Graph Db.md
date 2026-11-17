Public UAP incident data is spread across government archives, military resolution offices, and civilian reporting networks. To unify these disparate schemas in Neo4j, you can use a modified **POLE (Persons, Objects, Locations, Events)** intelligence data model. \[[1](https://neo4j.com/docs/getting-started/appendix/example-data/), [2](https://neo4j.com/blog/government/graph-technology-pole-position-law-enforcement/)\]

---

Part 1: Public UAP Databases & Archives

**1\. Military, Defense & Intelligence**

* **U.S. AARO & PURSUE Portal.** The [All-domain Anomaly Resolution Office (AARO)](https://www.aaro.mil/UAP-Records/) publishes official military case resolutions, sensor imagery (FLIR, Gimbal, Go Fast), and information papers. Under the 2026 Presidential Unsealing and Reporting System for UAP Encounters, declassified military and intelligence files are also released on a rolling basis via [WAR.GOV/UFO](https://www.war.gov/News/Releases/Release/Article/4480582/department-of-war-releases-unidentified-anomalous-phenomena-files-in-historic-t/). \[[1](https://www.aaro.mil/uap-cases/official-uap-imagery/), [2](https://www.war.gov/News/Releases/Release/Article/4480582/department-of-war-releases-unidentified-anomalous-phenomena-files-in-historic-t/), [3](https://www.aaro.mil/UAP-Records/)\]  
* **U.S. National Archives (NARA) Record Group 615\.** Established under the 2024 NDAA, [NARA Record Group 615](https://www.archives.gov/research/topics/uaps) serves as the central U.S. federal repository for declassified UAP records across defense and intelligence agencies, alongside legacy holdings like Project Blue Book (Record Group 341/342). \[[1](https://www.archives.gov/research/topics/uaps), [2](https://www.archives.gov/research/topics/uaps/rg-collections)\]  
* **UK Ministry of Defence (MoD) Files.** Hosted by [The UK National Archives](https://www.nationalarchives.gov.uk/explore-the-collection/explore-by-time-period/postwar/ufo-reports/), this collection includes thousands of declassified military, radar, and public sighting reports from the 1960s through 2009\. \[[1](https://www.nationalarchives.gov.uk/explore-the-collection/explore-by-time-period/postwar/ufo-reports/)\]

**2\. Civil Authorities, Aviation & Law Enforcement**

* **France’s GEIPAN.** Operated by the French space agency CNES, [GEIPAN](https://www.cnes-geipan.fr/en) is one of the most structured public databases available. It combines civilian reports, Gendarmerie (police) interviews, aviation radar data, and formal scientific classifications (Categories A through D).  
* **Library and Archives Canada.** The [Canada's UFOs Collection](https://www.canada.ca/en/library-archives/collection/research-help/science-technology/ufos.html) houses roughly 9,500 digitized reports from the Royal Canadian Mounted Police (RCMP), Department of Transport, National Research Council, and Department of National Defence.  
* **FBI Vault.** The [FBI Vault UFO Collection](https://vault.fbi.gov/UFO) provides scanned historical memos and field office investigations involving local police and military coordination, primarily from 1947 to 1954\.  
* **Aviation Safety & FAA Records.** Civil aviation near-misses and pilot reports can be cross-referenced using NASA’s [Aviation Safety Reporting System (ASRS)](https://asrs.arc.nasa.gov/search/database.html) and FAA FOIA reading rooms. \[[1](https://www.canada.ca/en/library-archives/collection/research-help/science-technology/ufos.html), [2](https://science.gc.ca/site/science/en/office-chief-science-advisor/sky-canada-project/management-public-reporting-unidentified-aerial-phenomena-canada), [3](https://vault.fbi.gov/UFO), [4](https://simulationmaps.com/ufo-sightings-map)\]

**3\. Civilian & Historical Crowdsourced Databases**

* **National UFO Reporting Center (NUFORC).** The [NUFORC Databank](https://nuforc.org/databank/) contains over 200,000 searchable witness reports dating back decades. It includes structured fields for date, city/state, shape, duration, and narrative summaries, and is widely available in cleaned CSV/JSON formats on GitHub and Kaggle. \[[1](https://nuforc.org/), [2](https://nuforc.org/databank/)\]  
* **UPDB / Hatch & Vallee Historical Catalogs.** Compiled by researchers like Larry Hatch (*U* Database) and Jacques Vallée, these datasets aggregate tens of thousands of pre-2000 historical, newspaper, and academic cases with coded attributes for object behavior and physical effects.

---

Part 2: Neo4j Graph Schema Design

Because government PDFs, police reports, and civilian databases have wildly different fields, avoid rigid relational schemas. Use an **Event-Centric POLE Model** where a central Incident node connects modular evidence, entities, and source records.

**Core Node Labels**

* (:Incident) — The canonical, deduplicated real-world event (incident\_id, datetime\_utc, time\_precision, duration\_seconds, summary, classification\_status).  
* (:SourceRecord) — The raw entry from a specific database (source\_name, external\_case\_id, url, reporting\_agency, document\_type, raw\_text). Separating SourceRecord from Incident allows multiple agencies (e.g., local police, FAA, and NUFORC) to report on the same event without overwriting data.  
* (:Location) — Spatial hierarchy (latitude, longitude, point, city, region, country, environment\_type).  
* (:Phenomenon) — Observed object or anomaly (shape, apparent\_size, color, count, estimated\_speed, transmedium\_capable).  
* (:Observer) — Witness or sensor platform (type \[Civilian, Pilot, Police, Military, Radar, IR\_Camera\], role, anonymized\_id, credibility\_tier).  
* (:Evidence) — Attached media or physical trace (media\_type \[Video, Photo, Radar\_Track, Soil\_Sample, FOIA\_PDF\], file\_url, sensor\_band).  
* (:Tag) — Standardized behavioral descriptors (name \[e.g., Instantaneous\_Acceleration, No\_Visible\_Propulsion, EM\_Interference, Radar\_Visual\]).

**Key Relationships**

* (:SourceRecord)-\[:DESCRIBES\]-\>(:Incident) — Links multiple agency reports to one unified event.  
* (:Incident)-\[:OCCURRED\_AT\]-\>(:Location) — Connects the event to geospatial coordinates (enable Neo4j point indexes for spatial queries).  
* (:Location)-\[:PART\_OF\]-\>(:Location) — Enables geographic rollups (City \-\> State/Province \-\> Country).  
* (:Observer)-\[:REPORTED {distance\_est, bearing, visibility\_conditions}\]-\>(:Incident) — Captures witness-specific perspective properties on the relationship itself.  
* (:Incident)-\[:INVOLVED\]-\>(:Phenomenon) — Connects one or more distinct objects observed during the incident.  
* (:Phenomenon)-\[:EXHIBITED\]-\>(:Tag) — Normalizes flight characteristics across databases for pattern matching.  
* (:Incident)-\[:SUPPORTED\_BY\]-\>(:Evidence) — Attaches sensor logs, imagery, or archival documents.

---

Part 3: Practical Implementation Tips

* **Entity Resolution & Deduplication.** Civilian reports and military logs often describe the same event with slightly different timestamps or coordinates. Store every import as a :SourceRecord first, then run spatial-temporal matching (e.g., events within 50 km and ±2 hours) to merge them into a single :Incident node.  
* **Preserve Source Provenance.** Store agency-specific classifications (such as GEIPAN's Class D or AARO's Unresolved) on the :SourceRecord or on a \[:CLASSIFIED\_AS\] relationship from an :Organization node so conflicting official conclusions can coexist in the same graph.  
* **LLM Graph Extraction for Archival PDFs.** Collections from NARA, the FBI Vault, and Library and Archives Canada consist largely of unstructured scanned PDFs. You can use OCR paired with an LLM pipeline (such as Neo4j’s LLM Graph Builder) to extract Observer, Location, Phenomenon, and Tag nodes directly from raw document text. \[[1](https://neo4j.com/videos/turn-public-ufo-documents-from-war-gov-ufo-into-a-grounded-knowledge-graph-agent/), [2](https://www.canada.ca/en/library-archives/collection/research-help/science-technology/ufos.html), [3](https://vault.fbi.gov/UFO), [4](https://www.archives.gov/research/topics/uaps/rg-collections)\]

If you'd like, I can help you take the next step by providing:

* **Cypher DDL scripts** to create the constraints, spatial indexes, and sample nodes  
* **A Python ETL template** for ingesting and deduplicating CSVs from NUFORC and GEIPAN  
* **Entity resolution rules** to merge overlapping military and civilian reports

Let me know which part you want to build first\!

CYPHER

// 1\. Unique Constraints (Automatically create backing indexes)  
CREATE CONSTRAINT incident\_id\_unique IF NOT EXISTS FOR (i:Incident) REQUIRE i.incident\_id IS UNIQUE;  
CREATE CONSTRAINT source\_record\_unique IF NOT EXISTS FOR (s:SourceRecord) REQUIRE (s.source\_name, s.external\_case\_id) IS NODE KEY;  
CREATE CONSTRAINT tag\_name\_unique IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE;  
CREATE CONSTRAINT org\_name\_unique IF NOT EXISTS FOR (o:Organization) REQUIRE o.name IS UNIQUE;

// 2\. Geospatial & Temporal Indexes  
CREATE POINT INDEX location\_point\_idx IF NOT EXISTS FOR (l:Location) ON (l.coords);  
CREATE INDEX incident\_datetime\_idx IF NOT EXISTS FOR (i:Incident) ON (i.datetime\_utc);

// 3\. Full-Text Search Index for Narratives & OCR Archival PDFs  
CREATE FULLTEXT INDEX record\_narrative\_ft IF NOT EXISTS FOR (s:SourceRecord) ON EACH \[s.raw\_text, s.summary\];

Ingestion Query

// Create Organizations  
MERGE (aaro:Organization {name: 'AARO', type: 'Military'})  
MERGE (rcmp:Organization {name: 'RCMP', type: 'Law Enforcement'})

// Create Canonical Incident & Location  
MERGE (inc:Incident {incident\_id: 'INC-2024-0914-ON-001'})  
SET inc.datetime\_utc \= datetime('2024-09-14T03:15:00Z'),  
    inc.duration\_seconds \= 420,  
    inc.summary \= 'Multi-sensor and ground sighting of luminous sphere over Lake Ontario.'

MERGE (loc:Location {city: 'Picton', region: 'Ontario', country: 'Canada'})  
SET loc.coords \= point({latitude: 44.0072, longitude: \-77.1422})  
MERGE (inc)-\[:OCCURRED\_AT\]-\>(loc)

// Ingest Source 1: Police Report  
MERGE (src1:SourceRecord {source\_name: 'RCMP\_CAD', external\_case\_id: 'ON-24-88912'})  
SET src1.raw\_text \= 'Officer observed stationary amber sphere at approx 2000ft altitude, silent.'  
MERGE (src1)-\[:DESCRIBES\]-\>(inc)  
MERGE (rcmp)-\[:CLASSIFIED\_AS {status: 'Unexplained\_Aerial', date: date('2024-09-15')}\]-\>(src1)

// Ingest Source 2: Defense Sensor Log  
MERGE (src2:SourceRecord {source\_name: 'AARO\_PORTAL', external\_case\_id: 'CASE-8841'})  
SET src2.raw\_text \= 'AN/FPS-117 radar correlated intermittent track; no transponder.'  
MERGE (src2)-\[:DESCRIBES\]-\>(inc)  
MERGE (aaro)-\[:CLASSIFIED\_AS {status: 'Unresolved', date: date('2024-11-02')}\]-\>(src2)

// Attach Phenomenon & Behavioral Tags  
CREATE (p:Phenomenon {shape: 'Sphere', color: 'Amber', count: 1})  
MERGE (inc)-\[:INVOLVED\]-\>(p)  
FOREACH (tagName IN \['No\_Visible\_Propulsion', 'Radar\_Visual', 'Silent'\] \|  
    MERGE (t:Tag {name: tagName})  
    MERGE (p)-\[:EXHIBITED\]-\>(t)  
)

Python ETL

import hashlib  
import pandas as pd  
from neo4j import GraphDatabase

URI \= "neo4j://localhost:7687"  
AUTH \= ("neo4j", "your\_password")

def generate\_deterministic\_id(source: str, ext\_id: str) \-\> str:  
    raw \= f"{source}:{ext\_id}".encode("utf-8")  
    return f"SRC-{hashlib.sha256(raw).hexdigest()\[:12\]}"

def normalize\_nuforc(df: pd.DataFrame) \-\> list\[dict\]:  
    records \= \[\]  
    for idx, row in df.iterrows():  
        ext\_id \= str(row.get("id", idx))  
        records.append({  
            "source\_name": "NUFORC",  
            "external\_case\_id": ext\_id,  
            "temp\_incident\_id": generate\_deterministic\_id("NUFORC", ext\_id),  
            "datetime\_utc": pd.to\_datetime(row\["datetime"\], utc=True, errors="coerce").isoformat(),  
            "city": str(row.get("city", "")).strip().title(),  
            "region": str(row.get("state", "")).strip().upper(),  
            "country": str(row.get("country", "USA")).strip().upper(),  
            "lat": float(row\["latitude"\]) if pd.notnull(row.get("latitude")) else None,  
            "lon": float(row\["longitude"\]) if pd.notnull(row.get("longitude")) else None,  
            "shape": str(row.get("shape", "Unknown")).strip().title(),  
            "duration\_seconds": int(row.get("duration\_seconds", 0\) or 0),  
            "raw\_text": str(row.get("text", "")).strip(),  
            "observer\_type": "Civilian",  
            "classification": "Unverified"  
        })  
    return \[r for r in records if r\["datetime\_utc"\] \!= "NaT"\]

def normalize\_geipan(df: pd.DataFrame) \-\> list\[dict\]:  
    records \= \[\]  
    for \_, row in df.iterrows():  
        ext\_id \= str(row\["id\_cas"\])  
        records.append({  
            "source\_name": "GEIPAN",  
            "external\_case\_id": ext\_id,  
            "temp\_incident\_id": generate\_deterministic\_id("GEIPAN", ext\_id),  
            "datetime\_utc": pd.to\_datetime(row\["date\_obs"\], utc=True, errors="coerce").isoformat(),  
            "city": str(row.get("commune", "")).strip().title(),  
            "region": str(row.get("departement", "")).strip(),  
            "country": "FRANCE",  
            "lat": float(row\["lat"\]) if pd.notnull(row.get("lat")) else None,  
            "lon": float(row\["lon"\]) if pd.notnull(row.get("lon")) else None,  
            "shape": str(row.get("forme", "Unknown")).strip().title(),  
            "duration\_seconds": int(row.get("duree\_sec", 0\) or 0),  
            "raw\_text": str(row.get("resume", "")).strip(),  
            "observer\_type": "Civilian\_Gendarmerie",  
            "classification": str(row.get("classification", "D")).strip()  
        })  
    return \[r for r in records if r\["datetime\_utc"\] \!= "NaT"\]

BATCH\_UPSERT\_CYPHER \= """  
UNWIND \$batch AS row  
MERGE (src:SourceRecord {source\_name: row.source\_name, external\_case\_id: row.external\_case\_id})  
SET src.raw\_text \= row.raw\_text,  
    src.agency\_classification \= row.classification

// Initially create a 1-to-1 Incident; Entity Resolution will merge duplicates later  
MERGE (inc:Incident {incident\_id: row.temp\_incident\_id})  
SET inc.datetime\_utc \= datetime(row.datetime\_utc),  
    inc.duration\_seconds \= row.duration\_seconds

MERGE (src)-\[:DESCRIBES\]-\>(inc)

// Handle Location conditionally if coordinates exist  
FOREACH (\_ IN CASE WHEN row.lat IS NOT NULL AND row.lon IS NOT NULL THEN \[1\] ELSE \[\] END \|  
    MERGE (loc:Location {city: row.city, region: row.region, country: row.country})  
    SET loc.coords \= point({latitude: row.lat, longitude: row.lon})  
    MERGE (inc)-\[:OCCURRED\_AT\]-\>(loc)  
)

// Create Observer & Phenomenon  
CREATE (obs:Observer {type: row.observer\_type})  
MERGE (obs)-\[:REPORTED\]-\>(inc)

CREATE (p:Phenomenon {shape: row.shape})  
MERGE (inc)-\[:INVOLVED\]-\>(p)  
"""

def load\_to\_neo4j(records: list\[dict\], batch\_size: int \= 1000):  
    driver \= GraphDatabase.driver(URI, auth=AUTH)  
    with driver.session() as session:  
        for i in range(0, len(records), batch\_size):  
            batch \= records\[i : i \+ batch\_size\]  
            session.run(BATCH\_UPSERT\_CYPHER, batch=batch)  
    driver.close()

3\. Entity Resolution Rules (Merging Overlapping Reports)

When multiple witnesses, police dispatchers, and military radar operators report the same aerial event, their timestamps and coordinates rarely match identically. Use a **two-stage resolution pipeline** inside Neo4j:

**Stage 1: Candidate Pair Blocking (Spatial-Temporal Window)**

Avoid comparing every incident against every other incident (O(N²)). Instead, use Neo4j’s spatial index to block pairs within a realistic physical threshold:

* **Time Window:** ± 2 hours (duration.inSeconds(i1.datetime\_utc, i2.datetime\_utc).seconds \<= 7200)  
* **Spatial Radius:** ≤ 50 km (point.distance(l1.coords, l2.coords) \<= 50000) — wide enough to account for high-altitude objects viewed from neighboring towns.

**Stage 2: Weighted Confidence Scoring**

Score candidate pairs (i₁, i₂) on a 0.0 to 1.0 scale:

1. **Temporal Proximity (40% weight):** Linear decay from 1.0 (exact minute) to 0.0 (120 minutes apart).  
2. **Spatial Proximity (35% weight):** Linear decay from 1.0 (0 km) to 0.0 (50 km).  
3. **Attribute & Narrative Overlap (25% weight):**  
   * Exact or synonymous Phenomenon.shape match (e.g., Disc ≈ Saucer, Light ≈ Orb): \+0.15.  
   * Cosine similarity ≥ 0.75 between vector embeddings of SourceRecord.raw\_text: \+0.10.

**Cypher Execution: Linking & Merging Matched Incidents**

Run this query after ingestion. Pairs scoring **≥ 0.80** automatically merge their :SourceRecord links into the older/higher-authority :Incident node; pairs between **0.60 and 0.79** get flagged with a \[:POTENTIAL\_DUPLICATE\] relationship for human or LLM review.

cypher

```
// Requires APOC plugin for node refactoring/merging
MATCH (i1:Incident)-[:OCCURRED_AT]->(l1:Location)
MATCH (i2:Incident)-[:OCCURRED_AT]->(l2:Location)
WHERE id(i1) < id(i2)
  AND l1.coords IS NOT NULL AND l2.coords IS NOT NULL
  AND abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) <= 7200
  AND point.distance(l1.coords, l2.coords) <= 50000

WITH i1, i2,
     1.0 - (abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) / 7200.0) AS time_score,
     1.0 - (point.distance(l1.coords, l2.coords) / 50000.0) AS space_score

MATCH (i1)-[:INVOLVED]->(p1:Phenomenon)
MATCH (i2)-[:INVOLVED]->(p2:Phenomenon)
WITH i1, i2,
     (time_score * 0.40) + (space_score * 0.35) + (CASE WHEN p1.shape = p2.shape THEN 0.25 ELSE 0.0 END) AS confidence

// Auto-merge high confidence matches (>= 0.80)
FOREACH (_ IN CASE WHEN confidence >= 0.80 THEN [1] ELSE [] END |
    MERGE (i2)-[r:MERGED_INTO {confidence: confidence, resolved_at: datetime()}]->(i1)
)
// Flag medium confidence matches for review (0.60 - 0.79)
FOREACH (_ IN CASE WHEN confidence >= 0.60 AND confidence < 0.80 THEN [1] ELSE [] END |
    MERGE (i1)-[:POTENTIAL_DUPLICATE {confidence: confidence}]->(i2)
);

// Re-point SourceRecords from merged incidents to the canonical Incident
MATCH (src:SourceRecord)-[oldRel:DESCRIBES]->(dup:Incident)-[:MERGED_INTO]->(canonical:Incident)
MERGE (src)-[:DESCRIBES]->(canonical)
DELETE oldRel;
```

1\. LLM Extraction Pipeline for Unstructured Archival PDFs

Government files from NARA, the FBI Vault, and Library and Archives Canada often consist of scanned memoranda and teletype transcripts. This Python script uses structured outputs (Pydantic \+ OpenAI) to extract standardized graph entities from OCR text and write them directly into Neo4j.

python

```
from typing import List, Optional
from pydantic import BaseModel, Field
from openai import OpenAI
from neo4j import GraphDatabase

client = OpenAI()
driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "your_password"))

# 1. Define Strict Schema for Graph Extraction
class ExtractedPhenomenon(BaseModel):
    shape: str = Field(description="Standardized shape: Sphere, Disc, Triangle, Cylinder, Cigar, Light, Chevron, Other")
    color: Optional[str] = None
    count: int = 1
    behavioral_tags: List[str] = Field(
        description="Select from: Instantaneous_Acceleration, No_Visible_Propulsion, Hypersonic_Velocity, Transmedium, EM_Interference, Radar_Visual, Hovering, Silent"
    )

class ExtractedIncident(BaseModel):
    datetime_iso: Optional[str] = Field(description="ISO-8601 UTC timestamp if determinable, else null")
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    observer_types: List[str] = Field(description="Select from: Military, Pilot, Police, Radar, Civilian, Intelligence")
    summary: str = Field(description="Concise 2-sentence factual summary of the report")
    phenomena: List[ExtractedPhenomenon]

# 2. Extract Structured Entities via LLM
def parse_archival_document(ocr_text: str) -> ExtractedIncident:
    response = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an intelligence analyst extracting structured UAP incident data from historical government and police archives. "
                    "Only extract explicitly stated facts. Do not infer coordinates or dates not supported by the text."
                )
            },
            {"role": "user", "content": ocr_text}
        ],
        response_format=ExtractedIncident,
    )
    return response.choices[0].message.parsed

# 3. Ingest Extracted Entities into Neo4j
def ingest_extracted_record(source_name: str, ext_id: str, ocr_text: str, data: ExtractedIncident):
    query = """
    MERGE (src:SourceRecord {source_name: $source_name, external_case_id: $ext_id})
    SET src.raw_text = $raw_text, src.document_type = 'Archival_PDF'

    MERGE (inc:Incident {incident_id: $source_name + '-' + $ext_id})
    SET inc.summary = $summary,
        inc.datetime_utc = CASE WHEN $dt IS NOT NULL THEN datetime($dt) ELSE null END

    MERGE (src)-[:DESCRIBES]->(inc)

    FOREACH (_ IN CASE WHEN $city IS NOT NULL OR $region IS NOT NULL THEN [1] ELSE [] END |
        MERGE (loc:Location {
            city: coalesce($city, 'Unknown'),
            region: coalesce($region, 'Unknown'),
            country: coalesce($country, 'Unknown')
        })
        MERGE (inc)-[:OCCURRED_AT]->(loc)
    )

    FOREACH (obsType IN $observer_types |
        MERGE (o:Observer {type: obsType})
        MERGE (o)-[:REPORTED]->(inc)
    )

    WITH inc
    UNWIND $phenomena AS pData
    CREATE (p:Phenomenon {shape: pData.shape, color: pData.color, count: pData.count})
    MERGE (inc)-[:INVOLVED]->(p)
    FOREACH (tag IN pData.behavioral_tags |
        MERGE (t:Tag {name: tag})
        MERGE (p)-[:EXHIBITED]->(t)
    )
    """
    with driver.session() as session:
        session.run(
            query,
            source_name=source_name,
            ext_id=ext_id,
            raw_text=ocr_text,
            summary=data.summary,
            dt=data.datetime_iso,
            city=data.city,
            region=data.region,
            country=data.country,
            observer_types=data.observer_types,
            phenomena=[p.model_dump() for p in data.phenomena],
        )
```

Use code with caution.  
---

2\. Vector Similarity Pipeline for Narrative Entity Resolution

When two witnesses describe the same event using different words (e.g., *"bright orange fireball moving silently"* vs. *"amber glowing sphere with no engine noise"*), text embeddings capture semantic overlap that keyword matching misses.

**Step A: Create the Neo4j Vector Index**

Run this Cypher command once (configured for 1536-dimensional embeddings such as text-embedding-3-small):

cypher

```
CREATE VECTOR INDEX source_narrative_vec_idx IF NOT EXISTS
FOR (s:SourceRecord) ON (s.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
  }
};
```

Use code with caution.

**Step B: Generate & Store Embeddings in Python**

python

```
def embed_and_store_records(batch_size: int = 100):
    with driver.session() as session:
        records = session.run(
            "MATCH (s:SourceRecord) WHERE s.embedding IS NULL AND s.raw_text IS NOT NULL "
            "RETURN elementId(s) AS id, s.raw_text AS text LIMIT 1000"
        ).data()

        for i in range(0, len(records), batch_size):
            chunk = records[i : i + batch_size]
            texts = [r["text"][:8000] for r in chunk]
            resp = client.embeddings.create(input=texts, model="text-embedding-3-small")

            payload = [
                {"id": chunk[j]["id"], "vec": resp.data[j].embedding}
                for j in range(len(chunk))
            ]
            session.run(
                "UNWIND $payload AS row "
                "MATCH (s:SourceRecord) WHERE elementId(s) = row.id "
                "CALL db.create.setNodeVectorProperty(s, 'embedding', row.vec)",
                payload=payload
            )
```

Use code with caution.

**Step C: Enhanced Entity Resolution Query with Vector Similarity**

This upgrades your Stage 2 matching query by incorporating vector.similarity.cosine() directly into the confidence score:

cypher

```
MATCH (s1:SourceRecord)-[:DESCRIBES]->(i1:Incident)-[:OCCURRED_AT]->(l1:Location)
MATCH (s2:SourceRecord)-[:DESCRIBES]->(i2:Incident)-[:OCCURRED_AT]->(l2:Location)
WHERE id(i1) < id(i2)
  AND s1.embedding IS NOT NULL AND s2.embedding IS NOT NULL
  AND abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) <= 7200
  AND point.distance(l1.coords, l2.coords) <= 50000

WITH i1, i2,
     1.0 - (abs(duration.inSeconds(i1.datetime_utc, i2.datetime_utc).seconds) / 7200.0) AS time_score,
     1.0 - (point.distance(l1.coords, l2.coords) / 50000.0) AS space_score,
     vector.similarity.cosine(s1.embedding, s2.embedding) AS semantic_score

WITH i1, i2,
     (time_score * 0.35) + (space_score * 0.35) + (semantic_score * 0.30) AS confidence
WHERE confidence >= 0.80
MERGE (i2)-[:MERGED_INTO {confidence: confidence, method: 'SpatioTemporal_Vector'}]->(i1);
```

Use code with caution.  
---

3\. Analytical Cypher Queries

Once your graph is populated and deduplicated, use these queries to uncover cross-agency corroboration, sensitive airspace proximity, and recurring "flap" clusters.

**Query A: High-Credibility Multi-Agency Corroboration**

Finds incidents independently documented by **both** civilian observers and official military, aviation, or law enforcement channels.

cypher

```
MATCH (src1:SourceRecord)-[:DESCRIBES]->(inc:Incident)<-[:DESCRIBES]-(src2:SourceRecord)
WHERE src1.source_name <> src2.source_name
MATCH (inc)<-[:REPORTED]-(obs:Observer)
WITH inc,
     collect(DISTINCT src1.source_name) + collect(DISTINCT src2.source_name) AS sources,
     collect(DISTINCT obs.type) AS observer_types
WHERE ('Military' IN observer_types OR 'Police' IN observer_types OR 'Radar' IN observer_types)
  AND 'Civilian' IN observer_types
MATCH (inc)-[:OCCURRED_AT]->(loc:Location)
RETURN inc.incident_id AS id,
       inc.datetime_utc AS timestamp,
       loc.city + ', ' + loc.country AS location,
       sources,
       observer_types,
       inc.summary AS summary
ORDER BY timestamp DESC;
```

Use code with caution.

**Query B: Proximity to Military Bases & Nuclear Infrastructure**

Load reference coordinates as :SensitiveSite nodes (e.g., air bases, nuclear generating stations, naval ranges) and query for unresolved incidents occurring within a 25 km radius.

cypher

```
MATCH (site:SensitiveSite)
MATCH (inc:Incident)-[:OCCURRED_AT]->(loc:Location)
WHERE loc.coords IS NOT NULL
  AND point.distance(site.coords, loc.coords) <= 25000
OPTIONAL MATCH (inc)-[:INVOLVED]->(p:Phenomenon)-[:EXHIBITED]->(t:Tag)
RETURN site.name AS facility,
       site.category AS facility_type,
       count(DISTINCT inc) AS total_incidents,
       round(avg(point.distance(site.coords, loc.coords)) / 1000.0, 2) AS avg_distance_km,
       collect(DISTINCT t.name) AS observed_behaviors
ORDER BY total_incidents DESC;
```

Use code with caution.

**Query C: Spatio-Temporal "Flap" Detection (Wave Clustering)**

Identifies sudden regional spikes where at least 5 distinct incidents occurred within a 100 km radius over a 7-day window.

cypher

```
MATCH (i1:Incident)-[:OCCURRED_AT]->(l1:Location)
MATCH (i2:Incident)-[:OCCURRED_AT]->(l2:Location)
WHERE i1 <> i2
  AND l1.coords IS NOT NULL AND l2.coords IS NOT NULL
  AND duration.inDays(i1.datetime_utc, i2.datetime_utc).days BETWEEN 0 AND 7
  AND point.distance(l1.coords, l2.coords) <= 100000
WITH i1, l1, count(DISTINCT i2) AS nearby_events, collect(DISTINCT i2.incident_id) AS cluster_ids
WHERE nearby_events >= 5
RETURN date(i1.datetime_utc) AS window_start,
       l1.region + ', ' + l1.country AS region,
       nearby_events + 1 AS cluster_size,
       cluster_ids[0..5] AS sample_incidents
ORDER BY cluster_size DESC, window_start DESC;
```

