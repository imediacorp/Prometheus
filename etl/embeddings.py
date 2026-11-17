"""
Vector embedding pipeline for SourceRecord narrative text.

Generates 1536-dimensional embeddings via OpenAI text-embedding-3-small and
stores them on SourceRecord.embedding using Neo4j's native vector property setter.
The vector index (source_narrative_vec_idx) was created in Phase 1 DDL.

Note: Anthropic does not provide a text embeddings API. OpenAI's
text-embedding-3-small is the standard pairing for 1536-dim cosine indexes.
Requires: pip install openai

Usage:
    from etl.embeddings import embed_pending
    stats = embed_pending(batch_size=100)
"""

from __future__ import annotations

import os
import importlib
import openai
from neo4j import GraphDatabase

# Detect openai SDK generation: v1+ has openai.OpenAI class; v3 does not.
_OPENAI_V1 = hasattr(openai, "OpenAI")

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "$Istanbul#1")

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536
MAX_TEXT_CHARS = 32_000  # ~8K tokens — well inside the model's 8191-token limit

# ---------------------------------------------------------------------------
# Fetch unembedded records from Neo4j
# ---------------------------------------------------------------------------

FETCH_CYPHER = """
MATCH (s:SourceRecord)
WHERE s.embedding IS NULL
  AND s.raw_text IS NOT NULL
  AND s.raw_text <> ''
RETURN elementId(s) AS eid, s.raw_text AS text
LIMIT $batch_size
"""

# ---------------------------------------------------------------------------
# Write embeddings back using the native vector property setter
# ---------------------------------------------------------------------------

STORE_CYPHER = """
UNWIND $payload AS row
MATCH (s:SourceRecord)
WHERE elementId(s) = row.eid
CALL db.create.setNodeVectorProperty(s, 'embedding', row.vec)
"""


def embed_pending(
    batch_size: int = 100,
    uri: str = NEO4J_URI,
    auth: tuple = NEO4J_AUTH,
    openai_api_key: str | None = None,
) -> dict:
    """
    Embeds all SourceRecord nodes that have raw_text but no embedding yet.
    Processes in batches of `batch_size` until none remain.

    Returns a dict with total_embedded and total_batches counts.
    """
    api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Export it or pass openai_api_key=... explicitly."
        )

    if _OPENAI_V1:
        oa_client = openai.OpenAI(api_key=api_key)
    else:
        # openai v3 uses module-level api_key
        openai.api_key = api_key

    driver = GraphDatabase.driver(uri, auth=auth)

    total_embedded = 0
    total_batches = 0

    try:
        while True:
            with driver.session() as session:
                records = session.run(FETCH_CYPHER, batch_size=batch_size).data()

            if not records:
                break

            # Truncate texts to avoid exceeding model token limit
            texts = [r["text"][:MAX_TEXT_CHARS] for r in records]
            eids = [r["eid"] for r in records]

            # Call OpenAI embeddings API — compatible with v1+ and v3
            if _OPENAI_V1:
                resp = oa_client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
                vectors = [item.embedding for item in resp.data]
            else:
                resp = openai.Embedding.create(input=texts, model=EMBEDDING_MODEL)
                vectors = [item["embedding"] for item in resp["data"]]

            payload = [{"eid": eid, "vec": vec} for eid, vec in zip(eids, vectors)]

            with driver.session() as session:
                session.run(STORE_CYPHER, payload=payload)

            total_embedded += len(records)
            total_batches += 1
            print(f"  [embed] Batch {total_batches}: embedded {total_embedded} records so far...")

    finally:
        driver.close()

    return {"total_embedded": total_embedded, "total_batches": total_batches}


def embedding_stats(uri: str = NEO4J_URI, auth: tuple = NEO4J_AUTH) -> dict:
    """Returns counts of embedded vs pending SourceRecord nodes."""
    cypher = """
    MATCH (s:SourceRecord)
    RETURN
        count(s)                                                        AS total,
        count(CASE WHEN s.embedding IS NOT NULL THEN 1 END)            AS embedded,
        count(CASE WHEN s.embedding IS NULL AND s.raw_text IS NOT NULL
                        AND s.raw_text <> '' THEN 1 END)               AS pending
    """
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            row = session.run(cypher).single()
            return dict(row) if row else {}
    finally:
        driver.close()
