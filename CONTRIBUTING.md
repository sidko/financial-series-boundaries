# Contributing

Create a focused pull request with tests for changed behavior. By submitting a
contribution, you confirm that you have the right to submit it under Apache-2.0.

Use Python 3.10–3.12 and run:

```bash
python -m pip install -e '.[test]'
python -m pytest
python examples/synthetic_annual_return.py
```

Keep provider adapters, production observations, asset registries, and business
policy outside this package. New public behavior needs synthetic tests that
demonstrate availability and fail-closed behavior.
