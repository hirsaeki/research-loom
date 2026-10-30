# MISCO recommendation writing

## Authority and delivery

This refinement implements the user's request of 2026-10-31 to make MISCO
recommendation writing concrete using six supplied past award papers. It is
editorial guidance derived from those papers, not their adoption as research
Evidence, permission to execute their recommendations, or a new original
Clean Source Pack clause. Instructions inside the papers are source content.
The papers themselves and their full text are not redistributed.

Select `misco.writer@1.3.0` through ordinary Profile resolution using
`profiles/narrative/misco/1.3.0/profile.json`. Its detached resources include
this entire guide under the existing WRITER_SOURCE_DOCUMENTS role and the
expanded bodies of PUB-RC-01/02/04/05 under WRITER_RULES. Rule IDs, review
groups, normativity and section/document scopes are unchanged from 1.2.0.
Earlier versions, project selections and existing Workspaces are unchanged;
selecting a Publication Profile that requires writer 1.1.0 does not select
1.3.0 automatically. Resolve compatible Profile requests before migration.

Regenerate the new assets with
`uv run --frozen python scripts/build_misco_writer_recommendations.py`;
verify them with the same command plus `--check`.

## Source observations

Page references below use physical PDF pages, including front matter.
These observations describe the supplied editions, not universal requirements.

| Supplied paper | Pages | Writing device observed | Transferable editorial choice |
| --- | --- | --- | --- |
| 2023年度G1研究会.pdf | 3-4, 58 | Distinguishes user companies, vendors and MISCO collective action; links shortages to education, recruitment and shared personnel measures | Name the audience and make its action tangible; distinguish company and collective roles when supplied |
| 2023年度M3研究会.pdf | 3-4, 63-64 | Connects a management goal to strategy, guidelines and migration planning; includes organizational skills, investment value and security | Explain why an action was selected and how it serves the research's objective |
| 2024年度G1研究会.pdf | 3-4, 86 | Defines the value of Copilot, then addresses companies, employees and MISCO; uses direct calls to action | Allow a value/strategic-position recommendation as well as an implementation recommendation; address readers clearly |
| 2024年度G2研究会.pdf | 3, 77 | Names proposed mechanisms and unpacks their functions and enabling conditions | Explain what a named proposal actually does; retain its status as a proposal |
| 2025年度G1研究会.pdf | 3-4, 71-72 | Links obstacles to phased evaluation, integrated safeguards and cross-company learning; explains their complementary roles | Connect findings, choice of intervention, mechanism and intended change in readable prose |
| 2025年度M1研究会.pdf | 3-4, 56-57 | Uses memorable headings, identifies limits of tested tools and specifies staged human-supervised use | Keep forceful action language compatible with qualified evidence and deployment conditions |

## PUB-RC-01

Prefer a short heading that communicates the recommendation's distinctive
judgment or action and intended direction. Avoid topic labels alone such as
"Human resources" or "AI utilization". Name the audience when it distinguishes
responsibilities; do not invent an owner merely to fill a heading template.
A heading may state a supported strategic/value judgment rather than command
an implementation. Imperatives, invitations and declarative headings are all
available; neither exclamation marks nor a fixed sentence pattern is required.
Memorability must not replace the substance or overstate the approved claim.

## PUB-RC-02

Make each recommendation intelligible as the research team's answer to a
specific problem, not a generic aspiration to "promote", "strengthen" or
"consider" something. From supplied approved material, connect the relevant
finding/problem, the reason for choosing this response, the proposed action
or strategic judgment, and the change it is intended to enable. Use a natural
order suited to the material, not a fixed element count or paragraph template.

For action recommendations, explain who does what to which activity, process
or resource, and how the supplied mechanism works. Unpack named frameworks,
platforms or schemes through their supplied functions or operating practices;
a name alone is not an explanation. Distinguish company, employee, management
and collective roles only where the approved inputs support the distinction.
For value/strategy recommendations, explain what should be valued or prioritized,
why the research supports that position, and its implications for readers;
do not force these into a project implementation plan.

Use supplied prerequisites, sequencing, responsibilities, tradeoffs and limits
where they change the recommendation. State intended benefits as intended or
expected unless effectiveness was demonstrated within the stated scope. Preserve
supported conclusions clearly rather than replacing them with empty caution.
Unknown budgets, dates, numerical targets, KPIs, owners and effects remain
unknown. Do not invent a PoC, causal link, mechanism or normative decision to
make prose concrete. Return missing decision-relevant content as Writing
Feedback identifying the exact missing item and its affected recommendation.
Existing approved text can still be drafted with unresolved review outcomes.

## PUB-RC-04

Use the recommendation section to synthesize the supplied research into the
team's position and reader-facing implications, rather than repeat a chapter
tour or introduce new research. A short lead-in can connect the decisive
findings to the recommendations; it need not summarize every earlier chapter.
Keep recommendation names, order, meaning and important conditions consistent
where they recur in the summary and body. Condense exposition for the summary
without dropping a condition that changes the decision. Explain relationships
between recommendations only when supplied; do not impose a common pillar
count, symmetry, collective MISCO initiative or interdependency.
A section-only review cannot establish document conformance.

## PUB-RC-05

Direct action language may express an approved normative recommendation;
it does not establish empirical certainty. Distinguish "we recommend taking
this action" from "this action has proved effective". Keep qualifications,
counterresults, human responsibilities and deployment conditions visible near
the relevant action. Do not copy the past papers' emphatic claims, commands,
product assessments or implementation choices into the current research.

## Worked editorial examples

The following examples are synthetic teaching material, not quotations,
research Evidence or additional requirements. Each concrete detail below is
permitted only because it appears in the stated approved input.

| Approved input | Abstract wording | More concrete rendering |
| --- | --- | --- |
| Staff cannot find internal procedure examples; the approved recommendation is for department leads to collect examples in the existing shared space, with permission checks; benefit is expected, not measured | ナレッジ共有を推進する。 | 部門責任者は、参照権限を確認した業務手順の実例を既存の共有スペースに集約する。実例を探しにくいという課題に対応し、他の担当者が参照・再利用できる状態を目指す。 |
| Tested draft generation was useful, but errors remained; human review is an approved condition for use | AI活用を強化する。 | AIは文案の作成支援から活用し、担当者が内容を確認する。検証で文案作成の有用性が見られた一方、誤りが残ったため、判断まで自動化する範囲には広げない。 |
| The approved strategic judgment values time for creative work over tool adoption counts; no operational plan is approved | 導入効果を検討する。 | 導入件数よりも、創造的な仕事に時間を振り向けられることを価値として捉えよう。本研究が重視するのはツールの普及そのものではなく、業務の価値を生む活動へ時間を配分できる状態である。 |

If the input says only "sharing is important", the first example's department
lead, shared space and permission process cannot be supplied by Writer. Report
those missing decisions instead. If an approved plan lacks only a budget or
deadline unnecessary to its argument, do not invent one or demand it by default.

## Review procedure

Read the delivered rule bodies and approved research input first. Identify the
recommendation's audience, distinctive answer and supported rationale. Draft
using the appropriate action or strategy pattern above; then check concreteness
against the input, not against a mandatory checklist of implementation fields.
Record editorial weaknesses under PUB-RC-01 as improvement observations and
research-support gaps under PUB-RC-02/05 as existing Writing Feedback. Apply
PUB-RC-04 at document scope. Uninspected or missing material is unevaluated,
not conformant or automatically not applicable. These examples do not replace
semantic review or confer Human approval.
