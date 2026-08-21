#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
SK=ROOT/'misco-publication-writer'
core=(SK/'SKILL.md').read_text(encoding='utf-8')
input_ref=(SK/'references/input_contract.md').read_text(encoding='utf-8')
case_ref=(SK/'references/qualitative_case_model.md').read_text(encoding='utf-8')
formal=(SK/'references/formal_rendering.md').read_text(encoding='utf-8')
source=(SK/'references/source_rule_index.md').read_text(encoding='utf-8')
flow=(SK/'examples/integration_like_flow.md').read_text(encoding='utf-8')
adv=(SK/'tests/adversarial_tests.md').read_text(encoding='utf-8')

checks=[]
def check(name, cond):
    checks.append((name, bool(cond)))

check('CR-01 approval semantics', 'does **not** necessarily mean final, frozen, or conclusively validated' in core and '`CANDIDATE`' in core)
check('CR-02 publication eligibility', 'status: ELIGIBLE | NOT_ELIGIBLE' in core and '`NOT_ELIGIBLE`' in core)
check('CR-03 INTEGRATED / Human status ownership', 'Default publication status: `INTEGRATED`' in core and 'stable_authorized: false' in core and 'final_authorized: false' in core)
check('CR-04 Publication Feedback output', 'type: ARGUMENT_GAP | QUESTION_SCOPE_AMBIGUITY' in core and 'suggested_destination: RESEARCH | METHODS | ACADEMIC_QA | HUMAN_DECISION | PUBLICATION_OPS' in core)
check('CR-05 composition feedback boundary', 'Do not create the missing link, revise the research question, infer a model repair' in core)
check('CR-06 primary exposition alias', 'primary_exposition_map' in input_ref and 'home_chapter_map' in input_ref and 'takes precedence' in input_ref)
check('CR-07 model revision feedback', 'MODEL_REVISION_UNRESOLVED' in case_ref)
check('CR-08 profile-driven citation/footnote', 'citation placement and footnote style are controlled by `formal_spec_profile`' in formal and 'Do not infer external-source citation style from historical MISCO papers.' in formal)
check('CR-09 runtime no-import', 'Historical papers/corpora are not runtime sources' in source and 'no historical corpus or runtime RAG dependency' in source)
check('Integration status transition', '`Publication Status: INTEGRATED`' in flow and 'stable_authorized: true' in flow and '`FINAL` remains prohibited' in flow)
check('ADV-22..32 present', all(f'| ADV-{n:02d} |' in adv for n in range(22,33)))
check('Feedback never Evidence', 'Publication Feedback is not Research Evidence' in adv and 'not research evidence' in core)

failed=[n for n,ok in checks if not ok]
for n,ok in checks:
    print(f'{n}={"PASS" if ok else "FAIL"}')
if failed:
    print('CONTRACT_REGRESSION=FAIL')
    sys.exit(1)
print('CONTRACT_REGRESSION=PASS')
print(f'checks={len(checks)}')
