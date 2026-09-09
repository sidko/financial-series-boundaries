"""Financial effective-date series and auditable annual boundaries."""
from .core import BoundaryPolicy, DateMappingPolicy, EndpointEligibility, SeriesPolicy, SourcePolicy, annual_boundary_return, build_series, evaluate_endpoint

__version__ = "0.1.0"
__all__ = ["BoundaryPolicy", "DateMappingPolicy", "EndpointEligibility", "SeriesPolicy", "SourcePolicy", "annual_boundary_return", "build_series", "evaluate_endpoint"]
