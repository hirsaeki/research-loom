# Publication application input

The optional third argument to the public Publication preview operation follows `core/packages/writer-publication/publication-application.schema.json`.

For `misco.publication@1.2.0`, the current formal specification and reader-facing full-URL policy are already delivered as pinned Profile resources. A normal production MISCO run therefore does not invent or re-enter those values as loose runtime defaults.

An explicit `formal_spec_profile` or `url_display_profile` is accepted only when it exactly matches the selected Profile resource. A different value is an authority conflict; change the authoritative Profile/resource under a new version instead of overriding it at runtime.

Application inputs remain the carrier for information that is genuinely project/material/review specific, including:

- `research_group_type` when an outer-structure rule requires it;
- `permissions` for affected non-public/interview/internal material;
- `editorial_review` for the explicit Human/Host editorial QA result.

Missing conditional inputs block only the formal/release operation that needs them. They do not make renderer defaults authoritative and do not stop unrelated Research or Writer work.

Tests may use explicitly synthetic inputs where a non-production path needs to prove contract mechanics, but synthetic values are never promoted to MISCO production authority.
