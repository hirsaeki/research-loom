# Publication application input

The optional third argument to the public Publication preview operation follows `core/packages/writer-publication/publication-application.schema.json`.

When the selected Publication Profile delivers its formal specification and reader-facing URL policy as pinned resources, a normal production run does not invent or re-enter those values as loose runtime defaults.

An explicit `formal_spec_profile` or `url_display_profile` is accepted only when it exactly matches the selected Profile resource. A different value is an authority conflict; change the authoritative Profile/resource under a new version instead of overriding it at runtime.

Application inputs remain the carrier for information that is genuinely project/material/review specific, including:

- `research_group_type` when an outer-structure rule requires it;
- `permissions` for affected non-public/interview/internal material;
- `editorial_review` for the explicit Human/Host editorial QA result.

Missing conditional inputs block only the formal/release operation that needs them. They do not make renderer defaults authoritative and do not stop unrelated Research or Writer work.

Tests may use explicitly synthetic inputs where a non-production path needs to prove contract mechanics, but synthetic values are never promoted to production Profile authority.
