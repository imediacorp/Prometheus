"""
Weekly digest generator for the Prometheus UAP graph.

Queries Neo4j for a snapshot of this week's activity and writes a Markdown
report to reports/latest.md.  Designed to run as the last step of the
GitHub Actions ingest workflow, with the output committed back to the repo.

Usage:
    python -m reports.digest
    python -m reports.digest --output reports/latest.md
    python -m reports.digest --lookback-days 30
"""

from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path

from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "$Istanbul#1")

DEFAULT_OUTPUT = Path(__file__).parent / "latest.md"


# ---------------------------------------------------------------------------
# Cypher queries
# ---------------------------------------------------------------------------

_GRAPH_SUMMARY = """
MATCH (i:Incident) WITH count(i) AS total_incidents
MATCH (s:SourceRecord) WITH total_incidents, count(s) AS total_records
OPTIONAL MATCH (n:SourceRecord)
WHERE n.loaded_at >= datetime() - duration({days: $lookback_days})
WITH total_incidents, total_records, count(n) AS new_this_period
RETURN total_incidents, total_records, new_this_period
"""

_SOURCE_BREAKDOWN = """
MATCH (s:SourceRecord)
RETURN s.source_name AS source, count(s) AS count
ORDER BY count DESC
"""

_NEW_CORROBORATION = """
MATCH (s:SourceRecord)-[:DESCRIBES]->(i:Incident)
MATCH (s)-[:REPORTED_BY]->(o:Observer)
WITH i, collect(DISTINCT s.source_name) AS sources,
        collect(DISTINCT o.observer_type) AS observer_types
WHERE any(ot IN observer_types WHERE ot IN ['Civilian'])
  AND any(ot IN observer_types WHERE ot IN
      ['Military','Police','Radar','Pilot','Intelligence','Official'])
OPTIONAL MATCH (i)-[:OCCURRED_AT]->(l:Location)
WITH i, sources, observer_types, l
WHERE i.datetime_utc >= datetime() - duration({days: $lookback_days})
RETURN i.incident_id            AS incident_id,
       toString(i.datetime_utc) AS datetime_utc,
       coalesce(l.city + ', ' + l.country, l.country, l.city) AS location,
       sources,
       observer_types,
       i.summary                AS summary
ORDER BY i.datetime_utc DESC
LIMIT 10
"""

_ACTIVE_FLAPS = """
MATCH (anchor:Incident)-[:OCCURRED_AT]->(anchor_loc:Location)
WHERE anchor_loc.coords IS NOT NULL
  AND anchor.datetime_utc >= datetime() - duration({days: $lookback_days})
MATCH (other:Incident)-[:OCCURRED_AT]->(other_loc:Location)
WHERE other_loc.coords IS NOT NULL
  AND elementId(anchor) <> elementId(other)
  AND point.distance(anchor_loc.coords, other_loc.coords) <= 100000
  AND duration.inDays(anchor.datetime_utc, other.datetime_utc).days >= 0
  AND duration.inDays(anchor.datetime_utc, other.datetime_utc).days <= 30
WITH anchor, anchor_loc, count(DISTINCT other) AS cluster_size
WHERE cluster_size >= 5
RETURN coalesce(anchor_loc.region + ', ' + anchor_loc.country,
                anchor_loc.country, anchor_loc.city) AS region,
       cluster_size,
       toString(anchor.datetime_utc) AS window_start
ORDER BY cluster_size DESC
LIMIT 5
"""

_SITE_ALERTS = """
MATCH (ss:SensitiveSite)
WHERE ss.coords IS NOT NULL
MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE l.coords IS NOT NULL
  AND point.distance(ss.coords, l.coords) <= 25000
  AND i.datetime_utc >= datetime() - duration({days: $lookback_days})
RETURN ss.name AS site, ss.site_type AS site_type, count(i) AS new_incidents
ORDER BY new_incidents DESC
LIMIT 10
"""

_RESOLUTION_QUEUE = """
MATCH ()-[p:POTENTIAL_DUPLICATE]->()
RETURN count(p) AS pending_review
"""

_EMBEDDING_COVERAGE = """
MATCH (s:SourceRecord)
RETURN count(s) AS total,
       count(CASE WHEN s.embedding IS NOT NULL THEN 1 END) AS embedded
"""


# ---------------------------------------------------------------------------
# Digest builder
# ---------------------------------------------------------------------------

def _run(session, cypher: str, **params):
    return session.run(cypher, **params).data()


def _run_one(session, cypher: str, **params):
    row = session.run(cypher, **params).single()
    return dict(row) if row else {}


def build_digest(lookback_days: int = 7) -> str:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    now = datetime.datetime.utcnow()

    try:
        with driver.session() as session:
            summary    = _run_one(session, _GRAPH_SUMMARY,     lookback_days=lookback_days)
            sources    = _run(session,     _SOURCE_BREAKDOWN)
            corr       = _run(session,     _NEW_CORROBORATION, lookback_days=lookback_days)
            flaps      = _run(session,     _ACTIVE_FLAPS,      lookback_days=lookback_days)
            site_alerts= _run(session,     _SITE_ALERTS,       lookback_days=lookback_days)
            res_queue  = _run_one(session, _RESOLUTION_QUEUE)
            emb        = _run_one(session, _EMBEDDING_COVERAGE)
    finally:
        driver.close()

    total_incidents  = summary.get("total_incidents", 0)
    total_records    = summary.get("total_records", 0)
    new_this_period  = summary.get("new_this_period", 0)
    pending_review   = res_queue.get("pending_review", 0)
    total_emb        = emb.get("total", 0)
    embedded         = emb.get("embedded", 0)
    emb_pct          = round(100 * embedded / total_emb, 1) if total_emb else 0

    lines: list[str] = []
    a = lines.append

    a(f"# Prometheus UAP Graph — Weekly Digest")
    a(f"")
    a(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}  ")
    a(f"**Lookback window:** {lookback_days} days")
    a(f"")

    # ---  1. Graph summary  ---
    a("## 1. Graph Summary")
    a("")
    a(f"| Metric | Count |")
    a(f"|--------|-------|")
    a(f"| Total incidents | {total_incidents:,} |")
    a(f"| Total source records | {total_records:,} |")
    a(f"| New source records (past {lookback_days}d) | {new_this_period:,} |")
    a(f"| Resolution queue (POTENTIAL_DUPLICATE) | {pending_review:,} |")
    a(f"| Embedding coverage | {embedded:,} / {total_emb:,} ({emb_pct}%) |")
    a("")

    # ---  2. Source breakdown  ---
    a("## 2. Source Breakdown")
    a("")
    a("| Source | Records |")
    a("|--------|---------|")
    for row in sources:
        a(f"| {row['source']} | {row['count']:,} |")
    a("")

    # ---  3. Corroborated incidents  ---
    a(f"## 3. New Corroborated Incidents (past {lookback_days}d)")
    a("")
    if corr:
        for r in corr:
            ts = (r.get("datetime_utc") or "")[:19]
            loc = r.get("location") or "Unknown location"
            srcs = ", ".join(r.get("sources") or [])
            obs = ", ".join(r.get("observer_types") or [])
            summary_text = r.get("summary") or ""
            a(f"### `{r['incident_id']}`")
            a(f"- **Date:** {ts}")
            a(f"- **Location:** {loc}")
            a(f"- **Sources:** {srcs}")
            a(f"- **Observer types:** {obs}")
            if summary_text:
                a(f"- **Summary:** {summary_text[:200]}")
            a("")
    else:
        a(f"_No new corroborated incidents in the past {lookback_days} days._")
        a("")

    # ---  4. Active flap regions  ---
    a(f"## 4. Active Flap Regions (past {lookback_days}d, 100 km / ≥5 incidents)")
    a("")
    if flaps:
        a("| Region | Cluster size | Window start |")
        a("|--------|--------------|--------------|")
        for r in flaps:
            region = r.get("region") or "Unknown"
            ws = (r.get("window_start") or "")[:10]
            a(f"| {region} | {r['cluster_size']} | {ws} |")
        a("")
    else:
        a(f"_No active flap clusters in the past {lookback_days} days._")
        a("")

    # ---  5. Sensitive site proximity alerts  ---
    a(f"## 5. Sensitive Site Proximity Alerts (25 km, past {lookback_days}d)")
    a("")
    if site_alerts:
        a("| Site | Type | New incidents |")
        a("|------|------|---------------|")
        for r in site_alerts:
            a(f"| {r['site']} | {r.get('site_type', 'N/A')} | {r['new_incidents']} |")
        a("")
    else:
        a(f"_No proximity alerts in the past {lookback_days} days._")
        a("")

    # ---  6. Resolution queue  ---
    a("## 6. Resolution Queue")
    a("")
    a(
        f"**{pending_review:,}** incident pairs are flagged as `POTENTIAL_DUPLICATE` "
        "and await human review.  "
    )
    a("Run `python -m queries.run_queries corroboration` to inspect candidates.")
    a("")

    # ---  7. Embedding coverage  ---
    a("## 7. Embedding Coverage")
    a("")
    a(f"**{embedded:,} / {total_emb:,}** source records have vector embeddings ({emb_pct}%).  ")
    pending_emb = total_emb - embedded
    if pending_emb > 0:
        a(f"**{pending_emb:,}** records are pending.  Run `python -m etl.ingest embed` to catch up.")
    else:
        a("All source records are fully embedded. ✓")
    a("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Prometheus weekly digest generator")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output Markdown file path")
    parser.add_argument("--lookback-days", type=int, default=7, help="Days to look back (default 7)")
    args = parser.parse_args()

    print(f"[digest] Building digest (lookback={args.lookback_days}d) ...")
    report = build_digest(lookback_days=args.lookback_days)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[digest] Written to {out.resolve()}")


if __name__ == "__main__":
    main()
