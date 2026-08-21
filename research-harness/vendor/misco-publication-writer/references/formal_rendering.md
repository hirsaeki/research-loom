# Formal Rendering Reference

Formal rendering applies content supplied by Publication/Research State to the current human-approved formal specification/profile. Formal rules do not authorize research changes.

## Source priority

1. Current MISCO-specific formal document specification / supplied `formal_spec_profile`.
2. Mitsui Interbusiness Research Institute general manual where the current formal specification delegates to it.
3. Observed historical writing never overrides formal specification and is not a runtime source for this Skill.

## Required formal behavior

- Page setup, body/heading font, indentation, and related concrete values: use `formal_spec_profile`; never infer them.
- Use the official heading hierarchy; do not add a parallel permanent heading system.
- Body prose is normally である調, with function-specific exceptions allowed by the formal spec.
- Executive summary follows the current MISCO-specific specification and includes approved management recommendations when formally required. Never invent recommendations.
- Full body length: 50–60 pages is an editing target; roughly 70 pages may be acceptable when research content requires it. If over target, first inspect redundancy and appendix transfer; never delete necessary approved evidence merely to hit a page count.
- Figure title below; table title above; unique formal numbering and number-based cross-reference.
- External source citation placement and footnote style are controlled by `formal_spec_profile` and/or the supplied approved citation profile. If the current profile specifies Word footnotes for body citations, render source calls accordingly. **Do not infer external-source citation style from historical MISCO papers.**
- External figures/tables: source placement remains profile-driven and uses supplied approved source metadata.
- Long raw URLs: use the supplied human-approved URL display profile. If absent when needed → `[NEEDS_INPUT]` (internal `HUMAN_DECISION_REQUIRED`).
- Supplementary explanations/term notes: Word footnotes in principle under PUB-FR-08 unless the current formal specification says otherwise. This does not by itself define the citation style for external sources.
- TOC, pagination, attachments, and outer wrapper follow group-specific current formal requirements.
- Interviews/internal information: respect publication permission, company-name disclosure, anonymization, and manuscript-confirmation state.
- Color QA is conditional: only when color figures/tables are used, and only against supplied approved conditions plus grayscale distinguishability.

## Formal-rendering stop cases

Return `[NEEDS_INPUT]` rather than guessing when required formal values are missing, especially `formal_spec_profile`, applicable group type, figure/table metadata, citation metadata/profile, permission state, or approved URL profile. A corresponding `FORMAL_METADATA_MISSING` Publication Feedback item may be returned separately.

Rule anchors: PUB-FR-01–10, PUB-EV-09, PUB-QL-05.
