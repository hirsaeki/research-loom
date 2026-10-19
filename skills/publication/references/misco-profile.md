# Example: the MISCO Publication Profile

This is an example for one organization's Profile (`misco.publication`), not part of the generic Publication procedure. Use it only when the selected Publication Profile is that Profile; the delivered resources remain the authority.

- It delivers `PUBLICATION_RULES`, `PUBLICATION_SOURCE_DOCUMENTS`, `PUBLICATION_FORMAL_SPEC` and `PUBLICATION_URL_DISPLAY`. Some versions add further `PUBLICATION_*` resources; read every one that is delivered.
- `PUBLICATION_FORMAL_SPEC` pins `formal_spec_profile` (the formal specification values and their source/approval pin), and `PUBLICATION_URL_DISPLAY` pins `url_display_profile` (long URLs are displayed in full in references). Do not re-enter either at runtime.
- Its required overall editorial check is `misco-editorial-qa`: `editorial_review` must contain a result for that check ID, and `unevaluated` or `warning` is not release approval.
- `research_group_type` is needed only when its outer formal structure branches on it, and `permissions` only for affected non-public, interview or internal material.
