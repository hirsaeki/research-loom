# Late visual live acceptance (#409)

Status: **NOT RUN / NOT ACCEPTED**. This is an execution/evidence checklist, not a UAT transcript or a Human PASS. Keep #409 and Epic #403 open until both Hosts meet the live gate below. Backend CI and synthetic inspection attestations do not satisfy it.

## Preconditions and evidence identity

Use the same reviewed final implementation HEAD in two independently provisioned fresh environments/sessions: Codex and ChatGPT Work. Provision the locked root environment outside the Host sandbox using the existing [runtime runbook](../operations/work-host-runtime.md). Record exact HEAD, Host/model/version/configuration (use “not exposed” only where actually unavailable), launcher readiness, public doctor/status results, Project Config and selected Research/Narrative/Publication Profile pins. Do not install missing runtime dependencies inside the Host sandbox or substitute system Python, direct documents or private-store mutation.

Start a small genuine research case with explicitly qualified quantitative data and three established relations. Record source/data identities, exact bytes/digests and actual Human Decisions. Build a Composition and at least two source-bound Writer sections without figures. Retain the baseline Package, Composition and Writer revision. Avoid fixtures that silently grant human authority.

Load the repository's Host bootstrap and research-conversation instructions explicitly. Resolve identifiers through public list/show/inspect results inside the Host; never require the human to choose or copy them. Use existing operating checkpoints and the stopped complete-Parent backup/restore path for fresh-session continuation.

## Ordinary conversation sequence (run separately in both Hosts)

| Step | Human request | Evidence to retain |
| --- | --- | --- |
| U1 | この比較、文章だけより棒グラフにした方が分かりやすいです。 | Actual transcript; qualified selected data/spec validation; exact chart PNG/legend; original generation Package; new Package/Composition/Writer revision and affected section changes |
| U2 | この3つの関係は文章だけだと分かりづらいので、流れが分かる図にしてください。 | Actual model/tool generation request/output; represented refs and instruction/input digest; original Package; actual image inspection and separate exact review note; selected candidate/review in rebuilt Package |
| U3 | この研究にはない新しい分類軸で比較する図にしてください。 | Ordinary Research escalation and substantive Human Decision if issued; no invented classification or premature authoritative image |
| U4 | 見た目を確認できる文書をください。 | Canonical preview receipt and exact DOCX digest; actual delivered/openable file; rendered pages; caption placement, numbers, body refs, units/source/rights checks; no release |
| U5 | この図を差し替えてください。その後、やはり図はいらないので外してください。 | New immutable candidate/review, Package and downstream revisions/builds; old records still readable and identical; unaffected research authority unchanged |
| U6 | 続きからお願いします。どこまで進んでいますか。 | Stop and transfer complete Parent, restore in an empty fresh destination/session, public reads; ordinary-language explanation of saved visual/research/manuscript/preview status and unresolved work; no release |

Do not script Human answers or report a model self-review as actual visual inspection. If a required public operation or output delivery fails, retain the failure and stop claiming the corresponding step succeeded. Inspect actual pages for readability, correspondence, clipping, overlap, mojibake and adequate source display. Native OOXML structure checks do not prove any of these.

## Human rubric and controls

After #430, at least one actual Host must also run the non-reference chart path:
validated `research-chart/v1` data/spec -> available Host/native/Data/Python renderer
-> exact PNG candidate with renderer provenance -> actual visual inspection and
separate conformance review -> rebuilt Package/Writer/canonical preview. Record
which Host and renderer were used. Reference CI/replay cannot substitute for this
live observation. Unavailable Host rendering is NOT RUN, not reference PASS.

Retain the bounded comparison of the same Evidence/spec through reference output,
Host output with PASS review, Host output without review, and deliberate visual
mismatch with FAIL review. Only the first two may be healthy Publication figures;
all retain unchanged Research State/Evidence. Synthetic backend controls remain
separate from actual image inspection and H1–H10 Human answers.

The actual reviewer records PASS/FAIL and evidence pointers for H1–H10 from #409: natural late requests, no internal-ID burden, authority distinction, chart data/unit consistency, no added explanatory meaning, Research escalation, preserved history, natural formal references/source display, openable visually inspected output, and accurate fresh-session continuity. Until observed, each result is **UNEVALUATED**. Preserve failed observations rather than turning them into warnings or inferred PASS.

| Bounded contrast | Existing backend controls | Required live observation |
| --- | --- | --- |
| Operator vs equivalent model-proposed chart spec | `test_issue405_research_charts.py` | Both use the same qualified data validator; neither generator grants authority |
| Correct binding vs one-value mismatch | `test_issue405_research_charts.py` | Mismatch cannot become a formal chart |
| Explanation semantic refs present vs absent | `test_issue406_generated_explanations.py` | Orphan candidate cannot be formally used |
| Visual consumer present vs removed | `test_issue408_generated_publication.py` | Saved Exhibit and visible formal figure are distinct; no successful text fallback |
| Representation-only vs new-analysis request | `test_issue407_visual_need.py` | Ordinary meaning stays unchanged; new analysis follows Research authority |
| First generation vs regeneration | `test_issue406_generated_explanations.py`, `test_issue408_generated_publication.py` | New identity, unchanged old exact bytes/history |
| Visual present vs removed | `test_issue407_visual_need.py` | Downstream revision changes, represented Research State does not |
| Generic vs pinned MISCO behavior; missing source/permission | Existing `test_misco_publication_profile_application.py` plus `test_issue408_generated_publication.py` | Pinned formal rules and applicable source/rights inputs; no guessed conformance |

Backend controls use synthetic data/reviews and are reported separately. Live acceptance retains exact selected artifacts, before/after Packages and Writer revisions, preview files/digests, page QA, transcript and rubric for each Host. Avoid unrelated repeated broad testing once the current implementation CI is clean.

## Closure record

Record final implementation HEAD/tree; current-HEAD CI and reviewer result; separate Codex and Work session/environment records; U1–U6 transcripts; H1–H10 actual Human results; bounded contrasts; exact artifact/file pointers; remaining limitations. Close #409/#403 only after all required live results are complete, with no hard FAIL or fabricated/openability/approval claim. A ready runbook, passing CI, a generated PNG probe or synthetic backend review is insufficient.
