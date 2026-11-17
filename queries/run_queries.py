"""
Analytical query runner for the Prometheus UAP graph.

Usage:
    python -m queries.run_queries corroboration
    python -m queries.run_queries sensitive-sites
    python -m queries.run_queries sensitive-sites --aggregate
    python -m queries.run_queries sensitive-sites --load-sites      # seed starter sites first
    python -m queries.run_queries flap --radius 100 --window 7 --min-cluster 5
    python -m queries.run_queries nearest --source NUFORC --id 12345 --top-k 10
    python -m queries.run_queries all
"""

import argparse
from . import corroboration, sensitive_sites, flap_detection, vector_resolution


def main():
    parser = argparse.ArgumentParser(description="Prometheus UAP analytical queries")
    sub = parser.add_subparsers(dest="query", required=True)

    # corroboration
    p_corr = sub.add_parser("corroboration", help="Multi-agency corroborated incidents")
    p_corr.add_argument("--limit", type=int, default=50)

    # sensitive-sites
    p_sites = sub.add_parser("sensitive-sites", help="Incidents near military/nuclear sites")
    p_sites.add_argument("--radius", type=float, default=25.0, help="Search radius in km (default 25)")
    p_sites.add_argument("--aggregate", action="store_true", help="Show per-facility summary")
    p_sites.add_argument("--load-sites", action="store_true", help="Seed the starter site list first")

    # flap
    p_flap = sub.add_parser("flap", help="Spatio-temporal flap / wave cluster detection")
    p_flap.add_argument("--radius",      type=float, default=100.0, help="Cluster radius in km (default 100)")
    p_flap.add_argument("--window",      type=int,   default=7,     help="Rolling window in days (default 7)")
    p_flap.add_argument("--min-cluster", type=int,   default=5,     help="Min incidents for a flap (default 5)")
    p_flap.add_argument("--limit",       type=int,   default=50)

    # nearest neighbours
    p_nn = sub.add_parser("nearest", help="Find semantically similar incidents via ANN vector search")
    p_nn.add_argument("--source", required=True, help="Source name of the anchor record (e.g. NUFORC)")
    p_nn.add_argument("--id",     required=True, help="External case ID of the anchor record")
    p_nn.add_argument("--top-k",  type=int, default=10, help="Number of neighbours to return (default 10)")

    # all
    sub.add_parser("all", help="Run all three analytical queries with defaults")

    args = parser.parse_args()

    if args.query == "corroboration":
        rows = corroboration.run(limit=args.limit)
        corroboration.print_report(rows)

    elif args.query == "sensitive-sites":
        if args.load_sites:
            n = sensitive_sites.load_sites()
            print(f"[sites] Loaded {n} sensitive sites into Neo4j")
        rows = sensitive_sites.run(radius_km=args.radius, aggregate=args.aggregate)
        sensitive_sites.print_report(rows, aggregate=args.aggregate)

    elif args.query == "flap":
        rows = flap_detection.run(
            radius_km=args.radius,
            window_days=args.window,
            min_cluster=args.min_cluster,
            limit=args.limit,
        )
        flap_detection.print_report(rows, radius_km=args.radius, window_days=args.window)

    elif args.query == "nearest":
        rows = vector_resolution.nearest_neighbours(
            source_name=args.source,
            ext_id=args.id,
            top_k=args.top_k,
        )
        vector_resolution.print_neighbours(rows, args.source, args.id)

    elif args.query == "all":
        print("\n>>> Query A: Multi-Agency Corroboration")
        corroboration.print_report(corroboration.run())

        print("\n>>> Query B: Sensitive Site Proximity (25 km, aggregate)")
        sensitive_sites.print_report(sensitive_sites.run(aggregate=True), aggregate=True)

        print("\n>>> Query C: Flap Detection (100 km / 7 days / ≥5 incidents)")
        flap_detection.print_report(flap_detection.run())


if __name__ == "__main__":
    main()
