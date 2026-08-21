# First Discovery Cycle fixture

The executable integration fixture is
`tests/integration/test_discovery_cycle.py`. It creates isolated Theme,
Expectations, and quarantined Seed inputs, then proves:

- Seed exclusion during independent Question Formation;
- explicit Seed inclusion only during comparison;
- immutable candidate and comparison history;
- Human Question Baseline block/resume;
- automatic Desktop Research preparation;
- Human method/protocol block and terminal resume;
- no manual Context Pack or result transport.

Run it with:

```powershell
uv run python -m pytest tests/integration/test_discovery_cycle.py
```
