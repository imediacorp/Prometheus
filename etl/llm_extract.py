"""
LLM extraction pipeline for unstructured archival UAP documents.

Sends OCR'd or raw PDF text to Claude claude-opus-5-5 and extracts structured
Incident/Phenomenon/Observer/Location entities via structured outputs (Pydantic).
Writes the result directly into Neo4j using the same schema as the CSV ETL path.

Usage:
    from etl.llm_extract import extract_and_ingest
    extract_and_ingest(source_name="FBI_VAULT", ext_id="memo-1947-04", text=ocr_text)
"""

from __future__ import annotations

import anthropic
from pydantic import BaseModel, Field
from typing import Optional
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Pydantic schemas — strict subset of what Claude can reliably extract
# ---------------------------------------------------------------------------

BEHAVIORAL_TAGS = [
    "Instantaneous_Acceleration",
    "No_Visible_Propulsion",
    "Hypersonic_Velocity",
    "Transmedium",
    "EM_Interference",
    "Radar_Visual",
    "Hovering",
    "Silent",
]

OBSERVER_TYPES = ["Military", "Pilot", "Police", "Radar", "Civilian", "Intelligence"]

SHAPE_TYPES = ["Sphere", "Disc", "Triangle", "Cylinder", "Cigar", "Light", "Chevron", "Other"]


class ExtractedPhenomenon(BaseModel):
    shape: str = Field(description=f"Standardized shape. One of: {', '.join(SHAPE_TYPES)}")
    color: Optional[str] = Field(default=None, description="Observed color if stated")
    count: int = Field(default=1, description="Number of objects observed")
    behavioral_tags: list[str] = Field(
        default_factory=list,
        description=f"Observed flight/physical behaviors. Select from: {', '.join(BEHAVIORAL_TAGS)}",
    )


class ExtractedIncident(BaseModel):
    datetime_iso: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp (e.g. 1952-07-19T23:00:00Z) if determinable, else null",
    )
    city: Optional[str] = Field(default=None)
    region: Optional[str] = Field(default=None, description="State, province, or department")
    country: Optional[str] = Field(default=None)
    observer_types: list[str] = Field(
        default_factory=list,
        description=f"Select from: {', '.join(OBSERVER_TYPES)}",
    )
    summary: str = Field(description="Concise 2-sentence factual summary of the report")
    phenomena: list[ExtractedPhenomenon] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction — Claude claude-opus-5-5 with structured outputs
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an intelligence analyst extracting structured UAP incident data from "
    "historical government, police, and military archives. "
    "Only extract facts explicitly stated in the document. "
    "Do not infer coordinates, dates, or witness counts not supported by the text. "
    "When a field is absent from the document, return null or an empty list."
)


def extract(text: str) -> ExtractedIncident:
    """
    Sends document text to Claude and returns a validated ExtractedIncident.
    Uses streaming + get_final_message() to handle long archival documents safely.
    """
    client = anthropic.Anthropic()

    with client.messages.stream(
        model="claude-opus-5-5",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text[:50_000]}],  # hard cap: ~40K tokens
        output_format=ExtractedIncident,
    ) as stream:
        response = stream.get_final_message()

    return response.parsed_output


# ---------------------------------------------------------------------------
# Neo4j ingest — same pattern as load_neo4j.py
# ---------------------------------------------------------------------------

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

INGEST_CYPHER = """
MERGE (src:SourceRecord {source_name: $source_name, external_case_id: $ext_id})
SET src.raw_text = $raw_text, src.document_type = 'Archival_PDF'

MERGE (inc:Incident {incident_id: $source_name + '-' + $ext_id})
SET inc.summary = $summary,
    inc.datetime_utc = CASE WHEN $dt IS NOT NULL THEN datetime($dt) ELSE null END

MERGE (src)-[:DESCRIBES]->(inc)

FOREACH (_ IN CASE WHEN $city IS NOT NULL OR $region IS NOT NULL THEN [1] ELSE [] END |
    MERGE (loc:Location {
        city:    coalesce($city, 'Unknown'),
        region:  coalesce($region, 'Unknown'),
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


def ingest(
    source_name: str,
    ext_id: str,
    raw_text: str,
    data: ExtractedIncident,
    uri: str = NEO4J_URI,
    auth: tuple = NEO4J_AUTH,
) -> None:
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            session.run(
                INGEST_CYPHER,
                source_name=source_name,
                ext_id=ext_id,
                raw_text=raw_text,
                summary=data.summary,
                dt=data.datetime_iso,
                city=data.city,
                region=data.region,
                country=data.country,
                observer_types=data.observer_types,
                phenomena=[
                    {
                        "shape": p.shape,
                        "color": p.color,
                        "count": p.count,
                        "behavioral_tags": p.behavioral_tags,
                    }
                    for p in data.phenomena
                ],
            )
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_and_ingest(source_name: str, ext_id: str, text: str) -> ExtractedIncident:
    """
    Full pipeline: extract entities from raw text, write to Neo4j, return result.
    """
    print(f"[llm_extract] Extracting: {source_name} / {ext_id} ({len(text)} chars)")
    data = extract(text)
    print(f"[llm_extract] Extracted: {data.summary[:80]}...")
    ingest(source_name, ext_id, text, data)
    print(f"[llm_extract] Ingested to Neo4j")
    return data
