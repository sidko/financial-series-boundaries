"""Run with: python examples/synthetic_annual_return.py"""
import pandas as pd
from financial_series_boundaries import BoundaryPolicy, SeriesPolicy, SourcePolicy, annual_boundary_return, build_series

rows = [
    {"date": "2023-12-29", "effective_date": "2023-12-29", "source": "archive", "close": 100.0},
    {"date": "2024-06-28", "effective_date": "2024-06-28", "source": "archive", "close": 108.0},
    {"date": "2024-12-30", "effective_date": "2024-12-30", "source": "archive", "close": 115.0},
]
series = build_series(rows, SeriesPolicy(source=SourcePolicy(priorities={"archive": 1}), metadata={"source_policy_label": "example-v1"}))
boundary = BoundaryPolicy(rule_id="reviewed-exchange", reviewed_sessions_required=True, min_observations=2, max_interior_gap_days=200)
result = annual_boundary_return(series, 2024, boundary, reviewed_baseline_date="2023-12-29", reviewed_ending_date="2024-12-30")
print({key: result[key] for key in ("return_pct", "baseline_date", "ending_date", "coverage_status")})
