# Expected composition error

Both manifests are individually schema-valid. Composing them must fail with exactly `PROFILE-COMP-REPLACE-001` because:

- they declare different values at the same semantic path;
- both use `replace`;
- the declarations come from different Profile categories;
- no same-type `extends` ancestry can produce a unique descendant winner;
- `requires` or input order cannot create replacement precedence across categories.

`PROFILE-COMP-CONFLICT-001` is the generic same-strategy fallback only when no more specific conflict classification applies. A resolver must not choose whichever file was loaded last.
