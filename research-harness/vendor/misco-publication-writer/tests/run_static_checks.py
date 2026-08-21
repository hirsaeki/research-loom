#!/usr/bin/env python3
from pathlib import Path
import re, sys

ROOT = Path(__file__).resolve().parents[2]
SK = ROOT / "misco-publication-writer"
errors=[]

def req(p):
    if not p.exists():
        errors.append(f"missing: {p.relative_to(ROOT)}")

def must(text, needle, label):
    if needle not in text:
        errors.append(f"missing contract marker: {label}")

required = [
    SK/'SKILL.md',
    SK/'references/input_contract.md',
    SK/'references/rhetorical_patterns.md',
    SK/'references/quantitative_and_figures.md',
    SK/'references/qualitative_case_model.md',
    SK/'references/recommendations_and_synthesis.md',
    SK/'references/formal_rendering.md',
    SK/'references/editorial_qa.md',
    SK/'references/source_rule_index.md',
    SK/'examples/synthetic_fewshots.md',
    SK/'examples/integration_like_flow.md',
    SK/'tests/adversarial_tests.md',
    SK/'tests/integration_test.md',
]
for p in required:
    req(p)

expected = [
'PUB-FR-01','PUB-FR-02','PUB-FR-03','PUB-FR-04','PUB-FR-05','PUB-FR-06','PUB-FR-07','PUB-FR-08','PUB-FR-09','PUB-FR-10',
'PUB-AR-01','PUB-AR-02','PUB-AR-03','PUB-AR-04','PUB-AR-05','PUB-AR-06','PUB-AR-07','PUB-AR-08','PUB-AR-09','PUB-AR-10',
'PUB-EV-02','PUB-EV-03','PUB-EV-04','PUB-EV-05','PUB-EV-06','PUB-EV-07','PUB-EV-08','PUB-EV-09','PUB-EV-10',
'PUB-QT-01','PUB-QT-02','PUB-QT-03','PUB-QT-04','PUB-QT-05','PUB-QT-06',
'PUB-QL-01','PUB-QL-02','PUB-QL-03','PUB-QL-04','PUB-QL-05',
'PUB-MF-01','PUB-MF-02','PUB-MF-03','PUB-MF-04','PUB-MF-05','PUB-MF-06',
'PUB-RC-01','PUB-RC-02','PUB-RC-03','PUB-RC-04','PUB-RC-05']
idx=(SK/'references/source_rule_index.md').read_text(encoding='utf-8') if (SK/'references/source_rule_index.md').exists() else ''
ids=re.findall(r'^\| (PUB-[A-Z]{2}-\d{2}) \|', idx, flags=re.M)
missing=[x for x in expected if x not in ids]
extra=sorted(set(ids)-set(expected))
if missing:
    errors.append(f"rule index missing {missing}")
if extra:
    errors.append(f"unexpected runtime rule IDs {extra}")
if len(ids)!=51:
    errors.append(f"runtime rule row count {len(ids)} != 51")

core=(SK/'SKILL.md').read_text(encoding='utf-8') if (SK/'SKILL.md').exists() else ''
must(core, 'Publication-eligible', 'approval / eligibility semantics')
must(core, 'status: ELIGIBLE | NOT_ELIGIBLE', 'publication eligibility enum')
must(core, 'SCAFFOLD | PROVISIONAL | REVISED | INTEGRATED | STABLE | FINAL', 'INTEGRATED status enum')
must(core, 'Default publication status: `INTEGRATED`', 'FINAL_EDITORIAL default INTEGRATED')
must(core, 'stable_authorized: false', 'stable authorization field')
must(core, 'final_authorized: false', 'final authorization field')
must(core, 'Publication Feedback:', 'Publication Feedback output contract')
must(core, 'primary_exposition_map: optional', 'primary exposition input')
must(core, 'home_chapter_map: optional  # backward-compatible alias', 'home chapter alias')
must(core, '[NEEDS_INPUT:', 'NEEDS_INPUT stop tag')
must(core, '[NEEDS_ACADEMIC_QA:', 'NEEDS_ACADEMIC_QA stop tag')
must(core, 'Do not browse for “MISCO-like” writing.', 'no-browse style guard')
must(core, 'Do not retrieve historical corpus material', 'historical runtime source guard')
must(core, 'never research evidence', 'Publication State evidence separation')
must(core, 'not research evidence', 'Publication Feedback evidence separation')

# Generic historical-dependency scan: dated historical fixture markers and retrieval hooks are forbidden.
for p in SK.rglob('*'):
    if p.name == 'run_static_checks.py':
        continue
    if p.is_file() and p.suffix in {'.md','.py','.json','.yaml','.yml'}:
        t=p.read_text(encoding='utf-8', errors='ignore')
        if re.search(r'\b20(?:1\d|2[0-5])\b', t):
            errors.append(f"dated historical fixture marker found in {p.relative_to(ROOT)}")
        if 'web.run' in t or 'runtime RAG search' in t:
            errors.append(f"runtime external retrieval hook found in {p.relative_to(ROOT)}")

few=(SK/'examples/synthetic_fewshots.md').read_text(encoding='utf-8') if (SK/'examples/synthetic_fewshots.md').exists() else ''
count=len(re.findall(r'^## SF-', few, flags=re.M))
if count < 14:
    errors.append(f"few-shot count {count} < 14")
for label in ['Synthetic Research State','Writer Task','MISCO Reader-facing Prose','QA Notes']:
    if few.count(label) < 14:
        errors.append(f"few-shot section {label} appears only {few.count(label)} times")

reader_chunks=re.findall(r'### 3\. MISCO Reader-facing Prose\n\n(.*?)(?=\n### 4\.)', few, flags=re.S)
leak_patterns=[r'\bRQ\d+',r'\bG\d+',r'FND-\w+',r'PROP-[A-Z0-9-]+',r'MODEL-\d+',r'CLM-\d+',r'PARTIALLY_REFUTED',r'CONDITION_ADDED']
for i,ch in enumerate(reader_chunks,1):
    for pat in leak_patterns:
        if re.search(pat,ch):
            errors.append(f"internal terminology leak in reader-facing few-shot {i}: {pat}")

adv=(SK/'tests/adversarial_tests.md').read_text(encoding='utf-8') if (SK/'tests/adversarial_tests.md').exists() else ''
for n in range(1,34):
    if f'| ADV-{n:02d} |' not in adv:
        errors.append(f'missing ADV-{n:02d}')
if '| FAIL |' in adv:
    errors.append('adversarial suite contains FAIL')

flow=(SK/'examples/integration_like_flow.md').read_text(encoding='utf-8') if (SK/'examples/integration_like_flow.md').exists() else ''
must(flow, '`Publication Status: INTEGRATED`', 'integration final editorial INTEGRATED')
must(flow, 'stable_authorized: true', 'integration explicit stable authorization')
must(flow, 'Research state status: `CANDIDATE`', 'integration candidate early writing')

formal=(SK/'references/formal_rendering.md').read_text(encoding='utf-8') if (SK/'references/formal_rendering.md').exists() else ''
must(formal, 'citation placement and footnote style are controlled by `formal_spec_profile`', 'profile-driven external citation/footnote style')
must(formal, 'Do not infer external-source citation style from historical MISCO papers.', 'no historical citation inference')

qcm=(SK/'references/qualitative_case_model.md').read_text(encoding='utf-8') if (SK/'references/qualitative_case_model.md').exists() else ''
must(qcm, 'MODEL_REVISION_UNRESOLVED', 'case/model feedback boundary')

if errors:
    print('STATIC_CHECKS=FAIL')
    for e in errors:
        print('-',e)
    sys.exit(1)
print('STATIC_CHECKS=PASS')
print('runtime_rule_ids=51')
print(f'synthetic_fewshots={count}')
print('adversarial_tests=33')
print('approval_eligibility_contract=PASS')
print('publication_status_cap=PASS')
print('publication_feedback_contract=PASS')
print('primary_exposition_alias=PASS')
print('formal_profile_citation_boundary=PASS')
print('historical_no_import_scan=PASS')
print('internal_reader_facing_id_scan=PASS')
print('integration_contract_markers=PASS')
