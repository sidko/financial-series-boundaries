# Agent integration

Install a released package, keep provider and calendar policy in the consuming
application, and map its rows into `build_series`. Compare old and new results
on synthetic and private representative data without copying private inputs into
this repository. Treat `unavailable_reason` as a review signal. For a rollout,
pin the package version, retain the previous consumer revision as rollback, and
verify that the consumer invokes this package rather than a duplicate algorithm.
