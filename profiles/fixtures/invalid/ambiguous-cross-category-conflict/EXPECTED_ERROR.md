# Expected composition error

Both manifests are individually schema-valid. Composing them must fail with `PROFILE-COMP-REPLACE-001` (or the umbrella `PROFILE-COMP-CONFLICT-001`) because:

- they declare different values at the same semantic path;
- both use `replace`;
- the declarations come from different Profile categories;
- `requires` or input order cannot create replacement precedence across categories.

A resolver must not choose whichever file was loaded last.
