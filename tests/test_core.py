import pandas as pd

from financial_series_boundaries import BoundaryPolicy, DateMappingPolicy, SeriesPolicy, SourcePolicy, annual_boundary_return, build_series, evaluate_endpoint


def policy(**kwargs):
    return SeriesPolicy(source=SourcePolicy(priorities={"primary": 1, "secondary": 2}, reject_threshold_bps=100, required_approval_fields=("review",)), **kwargs)


def test_missing_required_effective_date_fails_closed():
    series = build_series([{"date": "2024-01-02", "source": "daily", "close": 10}], policy(date_mapping=DateMappingPolicy(require_stored_effective_date_for=frozenset({"daily"}))))
    assert series.empty
    assert series.attrs["unavailable_reason"] == "required_effective_date_missing"


def test_newest_revision_wins_but_equal_revision_conflict_does_not():
    rows = [
        {"date": "2024-01-02", "source": "primary", "close": 10, "revision_at": "2024-01-02T00:00:00Z", "revision_id": 1},
        {"date": "2024-01-02", "source": "primary", "close": 12, "revision_at": "2024-01-03T00:00:00Z", "revision_id": 2},
    ]
    assert build_series(rows, policy()).iloc[0] == 12
    rows.append({"date": "2024-01-02", "source": "primary", "close": 13, "revision_at": "2024-01-03T00:00:00Z", "revision_id": 2})
    result = build_series(rows, policy())
    assert result.empty and result.attrs["unavailable_reason"] == "unresolved_price_candidates"


def test_equal_priority_sources_with_different_prices_fail_closed():
    rows = [{"date": "2024-01-02", "source": "a", "close": 10}, {"date": "2024-01-02", "source": "b", "close": 11}]
    result = build_series(rows, SeriesPolicy(source=SourcePolicy(priorities={"a": 1, "b": 1})))
    assert result.empty


def test_transition_requires_overlap_or_explicit_approval():
    rows = [{"date": "2024-01-02", "source": "primary", "close": 10}, {"date": "2024-01-03", "source": "secondary", "close": 11}]
    result = build_series(rows, policy())
    assert result.empty and result.attrs["unavailable_reason"] == "source_transition_pending_review"
    result = build_series(rows, policy(), transition_approvals={"primary->secondary": {"review": "synthetic-1"}})
    assert list(result) == [10, 11]


def test_transition_at_threshold_is_unavailable():
    rows = [
        {"date": "2024-01-01", "source": "primary", "close": 100},
        {"date": "2024-01-02", "source": "primary", "close": 100},
        {"date": "2024-01-02", "source": "secondary", "close": 101},
        {"date": "2024-01-03", "source": "secondary", "close": 101},
    ]
    result = build_series(rows, policy())
    assert result.empty and result.attrs["transition_diagnostics"][0]["status"] == "unavailable_pending_manual_review"


def test_utc_timestamp_maps_to_utc_calendar_date_and_bounds_are_closed():
    result = build_series([{"date": "2024-01-02T00:30:00+02:00", "source": "primary", "close": 10}], policy(), effective_start="2024-01-01", effective_end="2024-01-01")
    assert result.index[0].strftime("%Y-%m-%d") == "2024-01-01"
    assert DateMappingPolicy(raw_end_cushion_days={"daily": 1}).raw_retrieval_bounds("2024-01-01", "2024-01-31", ["daily"]) == ("2024-01-01", "2024-02-01")


def test_reviewed_and_exact_boundaries_and_no_implicit_gap_fill():
    reviewed = BoundaryPolicy(rule_id="reviewed", reviewed_sessions_required=True, min_observations=2, max_interior_gap_days=10)
    assert evaluate_endpoint("2024-12-31", "2024-12-30", reviewed, reviewed_session_date="2024-12-30").available
    assert not evaluate_endpoint("2024-12-31", "2024-12-30", BoundaryPolicy(rule_id="exact", exact_dates=True)).available
    prices = pd.Series([100, 120], index=pd.to_datetime(["2023-12-29", "2024-12-30"]))
    outcome = annual_boundary_return(prices, 2024, reviewed, reviewed_baseline_date="2023-12-29", reviewed_ending_date="2024-12-30")
    assert outcome["endpoint_return_available"] is True
    assert outcome["path_metrics_available"] is False
    assert outcome["interior_gap_days"] > 10


def test_unknown_calendar_requires_explicit_policy_evidence():
    prices = pd.Series([100, 110], index=pd.to_datetime(["2023-12-29", "2024-12-30"]))
    outcome = annual_boundary_return(prices, 2024, BoundaryPolicy())
    assert outcome["status"] == "unavailable"
    assert outcome["unavailable_reason"] == "baseline_reviewed_session_required"
