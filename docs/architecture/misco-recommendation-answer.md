# MISCO recommendations that retain the research answer

## Authority and version

The user requested a Writer Profile update on 2026-11-16 after a manuscript
using 1.3.0 became an extended set of decision procedures and qualifications.
This is a reusable editorial correction, not revision or adoption of that
manuscript's research content. Its text is not distributed here. All examples
below are newly written synthetic teaching material.

Select `misco.writer@1.4.0` with
`profiles/narrative/misco/1.4.0/profile.json` through normal Profile resolution.
It retains 1.3.0 and adds the four clarifications below to PUB-RC-01/02/04/05
inside WRITER_RULES. This guide travels through WRITER_SOURCE_DOCUMENTS.
Rule IDs, classifications, applicability, review scopes and research authority
boundaries are unchanged. The examples illustrate these rules; they are neither
new requirements nor research Evidence.

Versions 1.1.0 through 1.3.0 remain byte-identical. Project selections and
existing Workspaces are not migrated. Resolve Publication dependencies with
compatible requests when selecting the new Writer version. Generic Writer
instructions and research-session behavior are not changed.

Regenerate with
`uv run --frozen python scripts/build_misco_writer_recommendation_answer.py`;
use `--check` to verify committed outputs without modifying them.

## PUB-RC-01

Make a recommendation heading carry the supplied research judgment: the
choice, priority, change or position the team recommends to this reader.
Naming a topic and an activity such as considering, organizing or evaluating
does not substitute for that answer when a more specific answer is supplied.
Bring the decisive distinction out of the body rather than inventing a more
forceful conclusion. Changing the final verb to an imperative is insufficient.
An investigation or comparison is valid when it is itself the supplied choice;
do not force an implementation decision that is absent.

## PUB-RC-02

Lead with the supplied answer, and explain its reason and the practical or
strategic difference it makes. Concrete writing means making that choice
understandable, not merely listing concrete steps for deciding later. When an
approved answer is available, do not replace it with a catalogue of
considerations, responsible departments, prerequisites or possible options.
Explain why this response follows from the supplied material and what readers
should do or value differently. Recover a judgment already in the input before
requesting new research; never select a new preferred option on Writer's own.

Develop a readable argument. A natural movement is answer, decisive reason and
concrete change, with a decision-changing condition where needed; this is not
a mandatory paragraph order or element checklist. Choose details that explain
this recommendation's mechanism or strategic meaning. Do not mechanically
attach the same rationale/process/starting-example blocks to every item.
A short recommendation can be complete without an implementation checklist.
A longer explanation is appropriate when the supplied reasoning needs it;
brevity alone is not the acceptance criterion.

Implementation details and a first step may help carry out the recommendation,
but must not become its substitute. Connect a supplied first step to the actual
recommended change; do not invent a comparison, pilot, committee, responsible
party or approval process merely to make the section actionable. If investigating
or postponing is the approved answer, state which specific uncertainty changes
the decision and why that bounded next step is appropriate. Do not convert
justified uncertainty into a forced choice.

## PUB-RC-04

Read the recommendation section as a whole as well as each item. Its lead-in,
headings, explanations and ending should leave the reader with the supplied
research position. Do not let repeated process instructions, cross-reference
explanations, starting examples, decision tables and limitations displace it.
Use a table or implementation aid when it adds a distinct reader benefit;
an already requested or necessary table is not automatically removed. Do not
impose equal lengths, identical paragraph roles or a fixed recommendation count.
Group common qualifications where appropriate, while keeping conditions and
adverse findings that change a particular choice with that choice. Preserve
the meaning and force of recurring recommendations across summary and body.
A section-only check does not establish document PASS.

## PUB-RC-05

Separate the confidence of an empirical result from the clarity of a supplied
normative recommendation. An unproven benefit does not require replacing an
approved proposal with "consider whether to consider it". State the proposal
clearly and retain what is unmeasured. Conversely, direct wording does not
authorize claiming effectiveness, universal applicability or completed action.

Keep qualifications that change the action, safety, scope or claim strength
near the affected assertion. Consolidate repeated methodological and reporting
qualifications in their appropriate existing discussion or limitations passage;
do not automatically append a long disclaimer catalogue to every recommendation.
Necessary contrary findings and material limitations remain visible to a reader
of the main text. Do not delete them, hide them in notes, or use concision as a
reason to strengthen the conclusion. Placement and repetition are editorial
questions; no word count, caveat-word count or universal disclaimer ban applies.

## Worked comparison: a supported operational choice

Synthetic supplied input: the same order information is entered twice at a
handoff. Staff reports identify duplicate entry as a burden, but no time saving
has been measured. The approved recommendation is to enter shared fields once
at reception and let the downstream team use that record. Exception orders
still require confirmation by both teams. No software purchase, new committee,
budget, deadline or KPI is approved.

### Procedural drift

**引継ぎの改善に向け、情報と役割を整理する**

責任者は、受付と後工程の役割、必要な情報、確認手順を整理し、現行維持と改善案を比較する。
負担と効果を確認した上で、どの情報をどこで入力するかを判断することが重要である。
まず一つの業務を選び、関係者が判断条件を整理する。

This replaces the supplied choice with a process for choosing later and adds
a new comparison as a default first step.

### Concrete recommendation

**共通項目は受付で一度入力し、引継ぎ後も同じ記録を使おう**

受付と後工程で繰り返している共通項目の入力を、受付時の一度にまとめる。後工程はその記録を使い、
入力し直す仕事を減らす。担当者の報告で負担として挙がった二重入力に、直接対応するためである。

ただし、例外注文はこれまでどおり両担当で確認する。一度入力すれば確認も不要になる、という提案ではない。
削減できる時間はまだ測っていないが、研究会は同じ情報を再入力する分担を改めることを勧める。

The answer, reason and changed work are explicit. The exception stays beside
the action, and the unmeasured benefit is not presented as demonstrated.

### Unsupported forcefulness

**全注文の確認を廃止し、入力を完全自動化せよ**

二重入力をなくせば処理時間は必ず半減する。全注文を自動処理し、確認担当を他業務へ移すべきである。

This invents a mechanism, effect and staffing decision and drops the exception.
Its forcefulness cannot compensate for the changed research meaning.

## Worked comparison: a strategic position

Synthetic supplied input: registration counts alone do not show whether a
shared catalogue helps staff find and reuse procedures. No usage effect has
been established. The approved position values findability and reuse over
maximizing registration counts. No platform replacement or operating plan is
approved.

Weak: 資料共有の指標を整理し、登録数と利用状況を比較して評価方法を検討する。

Better: **資料を増やすことより、必要な手順を見つけて使えることを重視しよう。**
登録数が増えても、担当者の仕事に役立つとは限らない。本研究会は、共有の価値を資料の蓄積量ではなく、
必要な手順を探し出して再利用できることに置く。利用の効果は未確認であり、ここで示すのは評価の方向である。

The strategic answer is clear without inventing an implementation plan or
claiming demonstrated effectiveness.

## Legitimate comparison or investigation

Synthetic supplied input: a small observation records improvement for routine
orders and worsening for exception orders. It does not establish causality.
The approved recommendation defers a common rollout and compares exception
handling before choosing implementation. No rollout benefit is established.

Appropriate: **一律展開を保留し、例外注文の扱いを先に比較しよう。**
通常注文と例外注文では観察された方向が異なるため、現段階で同じ方式へそろえることを勧めない。
例外注文をどう扱うかを比べ、その結果を展開の判断に使う。今回の観察だけでは方式の因果効果は確定できない。

Do not reject this because it recommends comparison. It retains the actual
supplied answer, decision-relevant adverse result and uncertainty.

## Semantic editing and verification boundary

Before describing a passage as editorially resolved, read its heading, opening
and complete explanation together. State in ordinary words what the reader is
being advised to choose or change, why, and what condition could change that
advice. This is an editing check, not a new manuscript form. If the answer is
buried but already supplied, revise the passage. If it is missing from the
input, return targeted Writing Feedback; do not resolve the research choice.
Report a concrete problem and edit, not just "make it shorter", "make it
stronger" or a checklist result.

The worked comparisons provide a bounded semantic walkthrough. Automated tests
verify asset integrity, unchanged metadata and detached delivery; they cannot
establish whether generated prose follows the guidance. These examples are
hand-authored and their assessment is a self-review, not a live model trial,
independent human review or measured reader effect. Unresolved drafts remain
storable; no new runtime prose-quality gate is added.
