# financial-series-boundaries

Fail-closed construction of effective-date financial price series and auditable
annual return boundaries. It is for pipelines that need missing observations,
source switches, revisions, and exchange-calendar evidence to remain visible
instead of being silently repaired.

![Synthetic boundary timeline](https://raw.githubusercontent.com/sidko/financial-series-boundaries/main/docs/assets/synthetic-boundary-timeline.svg)

```bash
pip install financial-series-boundaries
```

```python
from financial_series_boundaries import BoundaryPolicy, SeriesPolicy, SourcePolicy, annual_boundary_return, build_series

series = build_series(
    [{"date": "2023-12-29", "effective_date": "2023-12-29", "source": "archive", "close": 100},
     {"date": "2024-12-30", "effective_date": "2024-12-30", "source": "archive", "close": 115}],
    SeriesPolicy(source=SourcePolicy(priorities={"archive": 1})),
)
result = annual_boundary_return(
    series, 2024,
    BoundaryPolicy(rule_id="reviewed-exchange", reviewed_sessions_required=True),
    reviewed_baseline_date="2023-12-29", reviewed_ending_date="2024-12-30",
)
assert result["return_pct"] == 15.0
```

The package accepts records or a pandas DataFrame. A record normally has
`date`, `source`, and `close`; it may also have `effective_date`, `revision_at`,
and `revision_id`. Dates are normalized as UTC calendar dates. `DateMappingPolicy`
can require stored effective dates for sources whose raw timestamps need an
application-specific interpretation. Its `raw_retrieval_bounds` helper makes a
closed query envelope; it never reads a database or contacts a provider.

## Design

- `build_series` chooses the newest source revision deterministically and applies
  configured source priority. An unresolved equal-priority tie removes that
  effective date and records a conflict; the series is unavailable only when no
  eligible date remains.
- Supplied effective-date bounds are validated before filtering. Malformed
  bounds return `invalid_effective_range`, while valid but reversed bounds
  return `reversed_effective_range`.
- Source changes must have usable overlap below a configured rejection threshold
  or explicit, application-supplied approval evidence. The evidence remains in
  result metadata.
- `annual_boundary_return` never fills gaps or replaces a missing prior boundary
  with the first price in the year. Exact, reviewed-session, and bounded-fallback
  endpoint rules are explicit `BoundaryPolicy` settings.
- Version labels and extra metadata are application-owned. This lets consumers
  retain their own audit vocabulary without coupling this package to it.

The initial release supports Python 3.11–3.13 and pandas 2.2–3.x. CI tests
Python 3.11 and 3.12 against the current compatible pandas release. It does not
ship a trading calendar, provider adapter, data store, asset registry, market
data, or a recommendation about which source should win. A consumer must supply
those decisions and should treat an unavailable result as a signal to review
evidence, rather than a value to impute.

For source-specific timestamp and provenance rules, provide a narrow
`DateMappingPolicy.row_mapper` that returns standardized records and/or a
`provenance_validator` that returns `True` only when the complete candidate
frame meets the consumer’s evidence rules. Either hook failing makes the whole
requested series unavailable; they cannot select prices, deduplicate revisions,
or decide transitions.

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python examples/synthetic_annual_return.py
python -m build
```

The synthetic tests cover missing, exact, and reviewed boundaries; UTC date
semantics; revisions and equal-priority ties; transition approval; and the fact
that a long interior gap is never filled. CI installs the built wheel before
running the example.

## Origin and history

This package was extracted from financial data-pipeline work for
[Gale Finance](https://gale.finance/). Gale-specific provider integrations,
asset and calendar registries, production data, transition policy, and storage
remain private. Until Gale’s cutover is complete, this repository describes the
package as “extracted from Gale”; it does not claim that Gale already uses the
published package.

The public history begins with the 2026 extraction work. The private source
mapping is retained outside this repository because it names Gale-only paths
and operational context. Some early development used Claude as a coding
assistant; Sid Kalla selected, reviewed and maintains this code.

Apache-2.0 covers this code and does not grant rights to Gale Finance’s logos or
visual identity. Maintenance is best effort; the latest release is supported
unless its release notes say otherwise.

See [CONTRIBUTING.md](https://github.com/sidko/financial-series-boundaries/blob/main/CONTRIBUTING.md),
[SECURITY.md](https://github.com/sidko/financial-series-boundaries/blob/main/SECURITY.md), and
[AGENT_INTEGRATION.md](https://github.com/sidko/financial-series-boundaries/blob/main/AGENT_INTEGRATION.md).
