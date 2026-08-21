# MVP test report

## Scope

The automated suite covers schemas and immutable persistence; Artifact Registry
and Context Pack policy; Mock and local subprocess workers; bounded failure and
schema rejection; independent Audit and State Reducer; Publication Export and
Feedback routing; Human Decision block/resume; CLI behavior; and the complete
first Discovery Cycle fixture.

Stress and regression coverage includes:

1. forbidden Seed context during independent Question Formation;
2. Publication Draft/Feedback contamination rejection;
3. REAL/VIRTUAL mode contamination rejection without a bridge;
4. exact preservation of counterevidence, unknowns, scope limits, minority
   warnings, and question-change reasons;
5. Human Decision block and automatic resume;
6. immutable failed runs and bounded retry using new run IDs;
7. malformed worker output without semantic commit;
8. orphan Publication Feedback rejection;
9. bounded compact Orchestrator run references;
10. immutable re-runs and prior artifacts;
11. referenced-input hash mismatch detection;
12. historical, superseded canonical, and simulation provenance exclusion;
13. Attention Map rejection as Research Evidence.
14. company marketing material rejected as independent effectiveness evidence;
15. mandatory source locators and resolvable Finding-to-Evidence traces;
16. mandatory Counterevidence/Unknown/Evidence Gap Handoff fields;
17. Research Worker method-selection rejection;
18. provisional Question Candidate authority rejection;
19. Desktop Research exclusion of Publication Draft and archive/provenance roles;
20. fixed-N stopping rejection with unresolved material Evidence Gaps;
21. lossless Desktop Research reduction and Method Decision routing;
22. human/interactive Work exchange using the shared Context Pack/Handoff schema.
23. detachable Attention intake, candidate Map distillation, Human adoption, and
    Map versioning;
24. verified workspace archive/freeze and independent mapless `rh new` creation.

The P1-P12 hardening regression set additionally covers Trace Store traversal
confinement, snapshot-bound Publication Eligibility and stale-head rejection,
policy-derived Desktop Research denial, shared materialization behavior,
re-entrant transition locks and explicit orphan release, CLI wait/error exit
codes, typed decision-kind migration, stable candidate identity, exclusive
immutable creation, and the production `assert` lint guard.

## Command

```powershell
uv run python -m pytest
```

The report records test scope, not a permanent pass claim. Run the command in
the current worktree before release; the final observed result belongs in the
completion audit.
