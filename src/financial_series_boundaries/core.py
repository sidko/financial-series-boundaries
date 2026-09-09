"""Explicit, fail-closed construction of financial time-series boundaries."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import math
from numbers import Real
from typing import Any, Callable, Iterable, Mapping, Optional

import pandas as pd


__version__ = "0.1.0"


@dataclass(frozen=True)
class SourcePolicy:
    """Application-owned source ordering and transition evidence requirements."""
    priorities: Mapping[str, int] = field(default_factory=dict)
    default_priority: int = 100
    review_threshold_bps: Optional[float] = None
    reject_threshold_bps: Optional[float] = None
    threshold_epsilon_bps: float = 1e-9
    required_approval_fields: tuple[str, ...] = ()
    transition_exception: Optional[Callable[[Mapping[str, Any]], Optional[Mapping[str, Any]]]] = None

    def priority_for(self, source: Any) -> int:
        return self.priorities.get(str(source or "").strip().lower(), self.default_priority)


@dataclass(frozen=True)
class DateMappingPolicy:
    """Rules for converting observations to effective calendar dates.

    Sources in ``require_stored_effective_date_for`` must carry an explicit,
    precomputed effective date. This prevents a reader from guessing provider
    timestamp semantics. ``raw_end_cushion_days`` is a query-planning aid only.
    """
    require_stored_effective_date_for: frozenset[str] = frozenset()
    raw_end_cushion_days: Mapping[str, int] = field(default_factory=dict)
    default_raw_end_cushion_days: int = 0
    row_mapper: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None
    provenance_validator: Optional[Callable[[pd.DataFrame], bool]] = None

    def raw_retrieval_bounds(
        self,
        effective_start: Optional[str],
        effective_end: Optional[str],
        sources: Iterable[str] = (),
    ) -> tuple[Optional[str], Optional[str]]:
        normalized = [str(source or "").strip().lower() for source in sources]
        cushion = max([self.default_raw_end_cushion_days, *(self.raw_end_cushion_days.get(source, self.default_raw_end_cushion_days) for source in normalized)], default=0)
        if not effective_end or cushion == 0:
            return effective_start, effective_end
        return effective_start, (pd.Timestamp(effective_end).normalize() + timedelta(days=cushion)).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class BoundaryPolicy:
    """Evidence rules for nominal annual boundaries and path qualification."""
    rule_id: str = "unknown"
    exact_dates: bool = False
    reviewed_sessions_required: bool = True
    fallback_grace_days: Optional[int] = None
    min_observations: int = 0
    max_interior_gap_days: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeriesPolicy:
    source: SourcePolicy = field(default_factory=SourcePolicy)
    date_mapping: DateMappingPolicy = field(default_factory=DateMappingPolicy)
    price_column: str = "close"
    adjusted_price_column: Optional[str] = None
    require_positive_prices: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EndpointEligibility:
    available: bool
    status: str
    expected_date: str
    actual_date: Optional[str]
    rule_id: str


def _date(value: Any) -> Optional[pd.Timestamp]:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_localize(None).normalize()


def _date_text(value: Any) -> Optional[str]:
    parsed = _date(value)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else None


def _valid_number(value: Any, positive: bool = True) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value)) and (float(value) > 0 if positive else True)


def at_or_above_threshold(value: float, threshold: float, *, epsilon: float = 1e-9) -> bool:
    """Compare a computed basis-point value with an explicit numerical tolerance."""
    if epsilon < 0:
        raise ValueError("epsilon must be non-negative")
    return value + epsilon >= threshold


def evaluate_endpoint(expected_date: str, actual_date: Optional[str], policy: BoundaryPolicy, *, reviewed_session_date: Optional[str] = None) -> EndpointEligibility:
    """Classify an endpoint without inferring a trading calendar."""
    expected, actual = _date(expected_date), _date(actual_date)
    if expected is None:
        raise ValueError("expected_date must be a valid date")
    if actual is None:
        return EndpointEligibility(False, "missing_boundary_observation", expected.strftime("%Y-%m-%d"), None, policy.rule_id)
    if policy.exact_dates:
        ok = actual == expected
        return EndpointEligibility(ok, "exact_boundary" if ok else "missing_exact_boundary", expected.strftime("%Y-%m-%d"), actual.strftime("%Y-%m-%d"), policy.rule_id)
    if reviewed_session_date is not None:
        reviewed = _date(reviewed_session_date)
        if reviewed is None:
            return EndpointEligibility(False, "invalid_reviewed_session", expected.strftime("%Y-%m-%d"), actual.strftime("%Y-%m-%d"), policy.rule_id)
        ok = actual == reviewed
        return EndpointEligibility(ok, "reviewed_session_close" if ok else "provider_gap_missing_reviewed_session_close", expected.strftime("%Y-%m-%d"), actual.strftime("%Y-%m-%d"), policy.rule_id)
    if policy.reviewed_sessions_required:
        return EndpointEligibility(False, "reviewed_session_required", expected.strftime("%Y-%m-%d"), actual.strftime("%Y-%m-%d"), policy.rule_id)
    if policy.fallback_grace_days is None:
        return EndpointEligibility(False, "no_boundary_rule", expected.strftime("%Y-%m-%d"), actual.strftime("%Y-%m-%d"), policy.rule_id)
    delta = (expected - actual).days
    if delta < 0:
        return EndpointEligibility(False, "boundary_observation_after_nominal_boundary", expected.strftime("%Y-%m-%d"), actual.strftime("%Y-%m-%d"), policy.rule_id)
    ok = delta <= policy.fallback_grace_days
    return EndpointEligibility(ok, "fallback_boundary_within_grace" if ok else "boundary_outside_fallback_grace", expected.strftime("%Y-%m-%d"), actual.strftime("%Y-%m-%d"), policy.rule_id)


def _empty(policy: SeriesPolicy, reason: Optional[str] = None, **metadata: Any) -> pd.Series:
    result = pd.Series(dtype="float64")
    result.attrs.update({"contract_version": "financial-series-boundaries-v1", **dict(policy.metadata), **metadata})
    if reason:
        result.attrs["unavailable_reason"] = reason
    return result


def _select_candidate(group: pd.DataFrame) -> tuple[Optional[pd.Series], bool]:
    """Choose one candidate, returning conflict=True for an unresolved tie."""
    selected: Optional[pd.Series] = None
    for priority in sorted(group["_priority"].unique()):
        tier = group[group["_priority"] == priority]
        for _source, source_rows in tier.groupby("_source", sort=True):
            newest = source_rows["_revision_at"].max()
            rows = source_rows[source_rows["_revision_at"] == newest]
            stable = rows["_revision_id"].max()
            if not pd.isna(stable):
                rows = rows[rows["_revision_id"] == stable]
            if rows["_price"].nunique() != 1:
                return None, True
            candidate = rows.sort_values("_price", kind="mergesort").iloc[0]
            if selected is None:
                selected = candidate
            elif float(selected["_price"]) != float(candidate["_price"]):
                return None, True
        if selected is not None:
            return selected, False
    return None, True


def _source_values(candidates: pd.DataFrame, source: str) -> pd.Series:
    values: dict[pd.Timestamp, float] = {}
    for date, group in candidates[candidates["_source"] == source].groupby("_effective_date", sort=True):
        selected, conflict = _select_candidate(group.assign(_priority=0))
        if not conflict and selected is not None:
            values[pd.Timestamp(date)] = float(selected["_price"])
    return pd.Series(values, dtype="float64")


def _row_context(row: pd.Series) -> dict[str, Any]:
    """Return a callback-safe snapshot of one validated selected candidate."""
    return {
        key: value
        for key, value in row.to_dict().items()
        if not key.startswith("_")
    }


def _transitions(candidates: pd.DataFrame, retained: pd.DataFrame, policy: SourcePolicy, approvals: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    if retained.empty or retained["_source"].nunique() < 2:
        return [], True
    diagnostics: list[dict[str, Any]] = []
    available = True
    chosen = retained.sort_values("_effective_date", kind="mergesort")
    switches = chosen[chosen["_source"].ne(chosen["_source"].shift())].iloc[1:]
    for _, switched in switches.iterrows():
        previous = chosen[chosen["_effective_date"] < switched["_effective_date"]].iloc[-1]
        old, new = previous["_source"], switched["_source"]
        old_values, new_values = _source_values(candidates, old), _source_values(candidates, new)
        overlap = old_values.index.intersection(new_values.index)
        item: dict[str, Any] = {"previous_source": old, "retained_source": new, "switch_date": _date_text(switched["_effective_date"]), "previous_effective_date": _date_text(previous["_effective_date"]), "previous_price": float(previous["_price"]), "switch_price": float(switched["_price"]), "adjacent_return_jump": float(switched["_price"]) / float(previous["_price"]) - 1}
        overlap_absolute_difference: Optional[float] = None
        overlap_relative_bps: Optional[float] = None
        overlap_date: Optional[str] = None
        overlap_observation_count = 0
        if overlap.empty:
            evidence = approvals.get(f"{old}->{new}", {})
            if policy.required_approval_fields and all(str(evidence.get(key) or "").strip() for key in policy.required_approval_fields):
                item.update({"status": "approved_external_reconciliation", "approval": {key: evidence[key] for key in policy.required_approval_fields}})
            else:
                item.update({"status": "unavailable_pending_external_reconciliation", "reason": "no_overlap_requires_approval"})
        else:
            comparisons = [(abs(float(old_values.loc[d]) - float(new_values.loc[d])) / abs(float(old_values.loc[d])) * 10000, d) for d in overlap if float(old_values.loc[d]) != 0]
            if not comparisons:
                item.update({"status": "unavailable_unusable_overlap", "reason": "zero_overlap_reference"})
            else:
                bps, date = max(comparisons, key=lambda pair: (pair[0], pair[1]))
                overlap_absolute_difference = abs(float(old_values.loc[date]) - float(new_values.loc[date]))
                overlap_relative_bps = bps
                overlap_date = _date_text(date)
                overlap_observation_count = len(comparisons)
                item.update({"overlap_date": overlap_date, "overlap_absolute_difference": overlap_absolute_difference, "overlap_relative_bps": overlap_relative_bps, "overlap_observation_count": overlap_observation_count, "review_required": policy.review_threshold_bps is not None and at_or_above_threshold(bps, policy.review_threshold_bps, epsilon=policy.threshold_epsilon_bps)})
                if policy.reject_threshold_bps is not None and at_or_above_threshold(bps, policy.reject_threshold_bps, epsilon=policy.threshold_epsilon_bps):
                    item.update({"status": "unavailable_pending_manual_review", "reason": "overlap_difference_at_or_above_rejection_threshold"})
                else:
                    item["status"] = "accepted_overlap"
        exception: Optional[Mapping[str, Any]] = None
        if policy.transition_exception is not None:
            context = {
                "previous_source": old,
                "retained_source": new,
                "switch_date": item["switch_date"],
                "previous_effective_date": item["previous_effective_date"],
                "previous_candidate": _row_context(previous),
                "retained_candidate": _row_context(switched),
                "overlap_date": overlap_date,
                "overlap_absolute_difference": overlap_absolute_difference,
                "overlap_relative_bps": overlap_relative_bps,
                "overlap_observation_count": overlap_observation_count,
            }
            try:
                candidate_exception = policy.transition_exception(context)
            except (KeyError, TypeError, ValueError):
                candidate_exception = None
            if isinstance(candidate_exception, Mapping):
                exception = dict(candidate_exception)
        if exception is not None:
            item.update({"status": "accepted_policy_exception", "policy_exception": dict(exception)})
        elif item["status"].startswith("unavailable_"):
            available = False
        diagnostics.append(item)
    return diagnostics, available


def build_series(rows: Any, policy: SeriesPolicy, *, effective_start: Optional[str] = None, effective_end: Optional[str] = None, days: Optional[int] = None, transition_approvals: Optional[Mapping[str, Mapping[str, Any]]] = None) -> pd.Series:
    """Build a deterministic effective-date series from records or a DataFrame.

    Expected fields are ``date``, ``source``, the configured price field, and
    optionally ``effective_date``, ``revision_at`` and ``revision_id``. No
    database access, provider registry, or implicit date shift is performed.
    """
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if policy.date_mapping.row_mapper is not None:
        try:
            frame = policy.date_mapping.row_mapper(frame.copy())
        except (KeyError, TypeError, ValueError):
            return _empty(policy, "row_mapping_failed")
        if not isinstance(frame, pd.DataFrame):
            return _empty(policy, "row_mapping_failed")
    if frame.empty or "date" not in frame:
        return _empty(policy, "missing_price_rows")
    if effective_start and effective_end and _date(effective_start) > _date(effective_end):
        return _empty(policy, "reversed_effective_range")
    frame["_source"] = frame.get("source", pd.Series("", index=frame.index)).fillna("").astype(str).str.strip().str.lower()
    raw = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    supplied = pd.to_datetime(frame["effective_date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize() if "effective_date" in frame else pd.Series(pd.NaT, index=frame.index)
    required = frame["_source"].isin(policy.date_mapping.require_stored_effective_date_for)
    if (required & supplied.isna()).any():
        return _empty(policy, "required_effective_date_missing")
    frame["_effective_date"] = supplied.where(supplied.notna(), raw)
    if policy.date_mapping.provenance_validator is not None:
        try:
            valid_provenance = bool(policy.date_mapping.provenance_validator(frame.copy()))
        except (KeyError, TypeError, ValueError):
            valid_provenance = False
        if not valid_provenance:
            return _empty(policy, "invalid_observation_provenance")
    if policy.price_column not in frame:
        if not policy.adjusted_price_column or policy.adjusted_price_column not in frame:
            return _empty(policy, "missing_price_column")
        close_prices = pd.Series(float("nan"), index=frame.index)
    else:
        close_prices = pd.to_numeric(frame[policy.price_column], errors="coerce")
    if policy.adjusted_price_column and policy.adjusted_price_column in frame:
        adjusted_prices = pd.to_numeric(frame[policy.adjusted_price_column], errors="coerce")
        frame["_price"] = adjusted_prices.where(adjusted_prices.notna(), close_prices)
    else:
        frame["_price"] = close_prices
    valid = frame["_price"].map(lambda v: _valid_number(v, policy.require_positive_prices))
    frame = frame[raw.notna() & frame["_effective_date"].notna() & valid].copy()
    if frame.empty:
        return _empty(policy, "no_valid_price_candidates")
    frame["_priority"] = frame["_source"].map(policy.source.priority_for)
    revisions = pd.to_datetime(frame.get("revision_at", pd.Series(pd.NaT, index=frame.index)), errors="coerce", utc=True)
    frame["_revision_at"] = revisions.fillna(pd.Timestamp("1970-01-01", tz="UTC"))
    frame["_revision_id"] = pd.to_numeric(frame.get("revision_id", pd.Series(float("nan"), index=frame.index)), errors="coerce")
    retained: list[pd.Series] = []
    conflicts: list[dict[str, Any]] = []
    if frame["_effective_date"].is_unique:
        retained = [row for _, row in frame.sort_values("_effective_date", kind="mergesort").iterrows()]
    else:
        for date, group in frame.groupby("_effective_date", sort=True):
            chosen, conflict = _select_candidate(group)
            if conflict or chosen is None:
                conflicts.append({"effective_date": _date_text(date), "reason": "unresolved_same_priority_revision"})
            else:
                retained.append(chosen)
    if not retained:
        return _empty(policy, "unresolved_price_candidates", dedupe_conflicts=conflicts)
    kept = pd.DataFrame(retained).sort_values("_effective_date", kind="mergesort")
    if days is not None:
        if days <= 0:
            return _empty(policy, "invalid_trailing_days")
        effective_end = _date_text(kept["_effective_date"].max())
        effective_start = _date_text(kept["_effective_date"].max() - timedelta(days=days - 1))
    if effective_start:
        kept = kept[kept["_effective_date"] >= _date(effective_start)]
    if effective_end:
        kept = kept[kept["_effective_date"] <= _date(effective_end)]
    if kept.empty:
        return _empty(policy, "no_effective_rows_in_requested_window", requested_effective_start=effective_start, requested_effective_end=effective_end, dedupe_conflicts=conflicts)
    candidates = frame
    if effective_start:
        candidates = candidates[candidates["_effective_date"] >= _date(effective_start)]
    if effective_end:
        candidates = candidates[candidates["_effective_date"] <= _date(effective_end)]
    diagnostics, transition_available = _transitions(candidates, kept, policy.source, transition_approvals or {})
    result = pd.Series(kept["_price"].to_numpy(), index=pd.DatetimeIndex(kept["_effective_date"]), dtype="float64").sort_index()
    sources = kept["_source"].value_counts().to_dict()
    result.attrs.update({"contract_version": "financial-series-boundaries-v1", **dict(policy.metadata), "sources_count": sources, "provider_by_effective_date": {_date_text(row["_effective_date"]): row["_source"] for _, row in kept.iterrows()}, "effective_start": _date_text(result.index.min()), "effective_end": _date_text(result.index.max()), "requested_effective_start": effective_start, "requested_effective_end": effective_end, "dedupe_conflicts": conflicts, "transition_diagnostics": diagnostics, "transition_available": transition_available})
    if not transition_available:
        return _empty(policy, "source_transition_pending_review", **result.attrs)
    return result


def annual_boundary_return(prices: pd.Series, year: int, policy: BoundaryPolicy, *, reviewed_baseline_date: Optional[str] = None, reviewed_ending_date: Optional[str] = None, expected_sessions: Optional[Iterable[str]] = None, provider_missing_dates: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Calculate a calendar-year endpoint return, preserving missing data."""
    expected_base, expected_end = f"{year - 1}-12-31", f"{year}-12-31"
    base = {
        "year": int(year),
        "calendar_rule": policy.rule_id,
        **dict(policy.metadata),
        "expected_baseline_date": expected_base,
        "expected_ending_date": expected_end,
    }

    def unavailable(reason: str, **extra: Any) -> dict[str, Any]:
        stable = {
            "return_fraction": None,
            "return_pct": None,
            "display_return_pct": None,
            "baseline_date": None,
            "ending_date": None,
            "baseline_price": None,
            "ending_price": None,
            "in_year_observations": 0,
            "interior_gap_days": None,
            "endpoint_return_available": False,
            "path_metrics_available": False,
            "full_year_coverage": False,
            "coverage_status": "unavailable",
            "status": "unavailable",
            "unavailable_reason": reason,
            "baseline_endpoint_status": None,
            "ending_endpoint_status": None,
            "path_prices": None,
        }
        return {**base, **stable, **extra}

    if prices is None or prices.empty:
        return unavailable("missing_price_series")

    original_attrs = dict(getattr(prices, "attrs", {}))
    series = pd.Series(prices).copy()
    series.index = pd.to_datetime(series.index, errors="coerce", utc=True).tz_localize(None).normalize()
    series = series[series.index.notna()].sort_index()
    if series.index.has_duplicates:
        return unavailable("duplicate_effective_date")

    in_year = series[(series.index >= pd.Timestamp(f"{year}-01-01")) & (series.index <= pd.Timestamp(expected_end))]
    prior = series[series.index < pd.Timestamp(f"{year}-01-01")]
    if prior.empty:
        return unavailable("missing_prior_boundary", in_year_observations=len(in_year))
    if in_year.empty:
        return unavailable("missing_ending_boundary")

    baseline_ts, ending_ts = prior.index.max(), in_year.index.max()
    baseline, ending = prior.loc[baseline_ts], in_year.loc[ending_ts]
    shared = {
        "baseline_date": _date_text(baseline_ts),
        "ending_date": _date_text(ending_ts),
        "baseline_price": float(baseline) if _valid_number(baseline, False) else None,
        "ending_price": float(ending) if _valid_number(ending, False) else None,
        "in_year_observations": len(in_year),
    }
    if not _valid_number(baseline):
        return unavailable("invalid_baseline_price", **shared)
    if not _valid_number(ending):
        return unavailable("invalid_ending_price", **shared)

    baseline_endpoint = evaluate_endpoint(expected_base, shared["baseline_date"], policy, reviewed_session_date=reviewed_baseline_date)
    ending_endpoint = evaluate_endpoint(expected_end, shared["ending_date"], policy, reviewed_session_date=reviewed_ending_date)
    if not baseline_endpoint.available:
        return unavailable(f"baseline_{baseline_endpoint.status}", **shared, baseline_endpoint_status=baseline_endpoint.status)
    if not ending_endpoint.available:
        return unavailable(f"ending_{ending_endpoint.status}", **shared, baseline_endpoint_status=baseline_endpoint.status, ending_endpoint_status=ending_endpoint.status)
    if not all(_valid_number(value) for value in in_year):
        return unavailable("invalid_in_year_price", **shared, baseline_endpoint_status=baseline_endpoint.status, ending_endpoint_status=ending_endpoint.status)

    path = pd.concat([pd.Series([float(baseline)], index=[baseline_ts]), in_year.astype(float)])
    path.attrs.update(original_attrs)
    path.attrs["effective_start"] = _date_text(path.index.min())
    path.attrs["effective_end"] = _date_text(path.index.max())
    gaps = path.index.to_series().diff().dt.days.dropna()
    gap = int(gaps.max()) if not gaps.empty else 0
    path_available = len(in_year) >= policy.min_observations and (policy.max_interior_gap_days is None or gap <= policy.max_interior_gap_days)
    expected = {_date_text(d) for d in expected_sessions or []}
    actual = {_date_text(d) for d in in_year.index}
    missing = {_date_text(d) for d in provider_missing_dates or []}
    full = bool(expected) and expected.issubset(actual | missing)
    fraction = float(ending) / float(baseline) - 1
    return {
        **base,
        **shared,
        "return_fraction": fraction,
        "return_pct": fraction * 100,
        "display_return_pct": round(fraction * 100, 1),
        "interior_gap_days": gap,
        "endpoint_return_available": True,
        "path_metrics_available": path_available,
        "full_year_coverage": full,
        "coverage_status": "full_year_coverage" if full else ("coverage_qualified" if path_available else "endpoint_only"),
        "status": "available",
        "unavailable_reason": None,
        "baseline_endpoint_status": baseline_endpoint.status,
        "ending_endpoint_status": ending_endpoint.status,
        "path_prices": path,
    }
