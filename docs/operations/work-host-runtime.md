# ChatGPT Work runtime, file delivery, and continuity

Issue #401 covers the host operations needed to use the existing Loom application
from ChatGPT Work. This is an operator/deployment runbook, not a human research
prompt and not evidence that Work live acceptance has passed.

## Shared application boundary

Codex and Work use the same `LocalApplicationFacade`, ActionRegistry, Profile
resolver, research/authority services, Writer and Publication paths. The existing
JSON CLI is one adapter to that facade. `local_application` names the filesystem
composition; it does not require another application API to be extracted.

| Responsibility | Shared Loom operation | Host responsibility |
| --- | --- | --- |
| Continue research | public status/resume and conversation view | translate ordinary intent and explain saved state |
| Acquire material | external attempt/capture/collect | retrieve exact originals and trustworthy text renditions |
| Draft/revise | Research Package, Composition and Writer round-trip | generate the requested prose from exported Writer input |
| Inspect output | Publication preview/show | deliver and render the already-bound output |
| Preserve a session | complete stopped Parent backup/restore | retain the backup in a durable file service |

Neither model-produced JSON nor a host attachment grants human authority. Use
the existing Confirmation and Human Decision paths. The host loads the canonical
[Research Conversation Skill](../../skills/research-conversation/SKILL.md)
explicitly for research tasks, including after a fresh-session restore. Repository
maintenance does not itself invoke that Skill.

## Runtime readiness

For a Work environment with shell access, use the existing POSIX launcher. The
runtime must match the repository root `pyproject.toml` and `uv.lock`. Do not assume
that `uv sync --frozen` can run inside the Host sandbox: `--frozen` prevents lock
updates, but missing wheels still require package-index access.

The supported no-index path is the repository `runtime-wheelhouse` workflow. For
the exact repository HEAD, that workflow exports the frozen runtime requirements,
downloads **wheel-only** Linux x86_64 / Python 3.12 artifacts in GitHub Actions,
records the exact `pyproject.toml`, `uv.lock`, requirements and wheel digests in
`manifest.json`, uploads the directory as one GitHub Actions artifact, then proves
that the uploaded/downloaded artifact can construct `.venv` with package indexes
disabled. This is runtime provisioning only; it does not grant Research authority.

After retrieving and extracting the artifact for the exact checked-out HEAD, run:

```sh
python3.12 scripts/runtime_wheelhouse.py verify --bundle <runtime-wheelhouse-dir>
python3.12 scripts/runtime_wheelhouse.py install --bundle <runtime-wheelhouse-dir>
./research-loom --help
```

`verify` and `install` fail closed when the repository HEAD, `pyproject.toml`,
`uv.lock`, target platform/Python, requirements or any wheel does not match the
manifest. `install` invokes pip with `--no-index` and `--require-hashes`; it never
falls back to PyPI. An existing `.venv` is not overwritten. There is still no
Work-specific dependency list, and a virtual environment copied from another
machine or filesystem path is not assumed to be portable.

In the repository root, before starting research:

```sh
git rev-parse HEAD
./research-loom --help
```

Record the repository HEAD and command result. Failure because `.venv/bin/python`
is absent means **runtime not provisioned**; do not substitute system Python or
direct host-native authoring and claim the research/writing stage succeeded.
Successful help only proves CLI startup, not workspace health or live acceptance.

For an existing workspace, next use the public boundary:

```sh
./research-loom doctor --workspace "$loom_workspace" --json
./research-loom status --workspace "$loom_workspace" --json
./research-loom resume --workspace "$loom_workspace" --view conversation --json
```

Set `loom_workspace` to the actual restored/initialized path. For a new case,
follow the existing production Project Config/Profile bootstrap; do not seed it
from another case or manufacture its binding/SQLite files. See the
[application boundary](../architecture/production-local-workspace-application-cli.md).

If Work has no shell and no connected Loom service, this local route is unavailable.
Report that deployment gap. A remote adapter requires an actual service deployment,
workspace ownership, authentication and artifact transfer; it is not created merely
because the host is called Work.

## Durable continuation across scratch replacement

Scratch is an execution location, not the sole durable research record. Use the
existing [stopped Parent backup and restore procedure](../architecture/parent-backup-restore.md).
There is no second Work research store and no live SQLite file synchronization.

1. Stop all users/writers of the workspace and close every application handle.
2. Keep it stopped, run public `doctor`, and record the result and repository HEAD.
3. Copy the **complete** `.research-loom` Parent tree to a new backup-set directory
   outside the source workspace, preserving any SQLite sidecars. Never combine
   files from separate generations. Verify the copied set using the existing
   procedure before resuming the source.
4. Package that stopped set as one archive, including its identity, repository
   HEAD and verification record. Compute a SHA-256 digest of the archive. A digest
   verifies transfer bytes; it does not prove that the source was stopped or that
   all research material is healthy.
5. Save the archive to the host's durable file service (ChatGPT Library when
   available) and retain the returned file identity and archive digest. A local
   download link alone does not establish durable storage. If saving fails, report
   the failure and do not promise continuity after scratch replacement.
6. To resume in another session, retrieve that exact archive, verify its digest,
   and restore the entire set into a **new empty isolated destination**. Treat the
   archive as trusted only according to its source; reject unsafe archive paths
   and links. Follow the Parent restore procedure, then public doctor/status/resume.
   Do not hand-edit pins or replay decisions to make a broken restore pass.

The durable archive remains an immutable backup. Only one restored/source copy is
designated active; do not write to both. Host staging files outside the Parent are
not automatically captured research material. Persist needed attachments through
the existing intake before promising research continuity. Human-delivered copies
of output can be retained separately, but do not substitute them for manuscript
and provenance in the Parent.

## Deliver a real appearance-check document

Use canonical Writer output and `publication preview`, then `publication show`.
The latter returns `output_root` and the build's `outputs`, including each output's
`relative_path`, digest and size. Resolve the requested output from those public
values; do not guess a private store path.

Before reporting the document ready, confirm that the file exists and matches the
recorded bytes, open/render it with the host's document/PDF tools, and save/deliver
that actual file through the host file service. Provide a working file link. A
derived PDF/render is a presentation copy with its own identity; it does not replace
the canonical output. Retain the canonical build binding and distinguish rendering
from human visual approval. Preview, file saving and rendering do not authorize
submission or publication.

If generation, verification, rendering or delivery fails, report the specific
failure. Do not substitute an independently authored document and count it as a
successful Loom stage.

## Acceptance and current deployment observation

On 2026-10-05 JST, repository HEAD
`e05d0fbdf7f40006b1294e8c6bdb14a99c0b0708` was inspected in a Work scratch environment.
Python 3.12 was present, but the repository `.venv` and system `jsonschema` were
absent. Invoking the POSIX launcher exited 127 with `.venv/bin/python: not found`.
This is a negative readiness observation, not a failed research result and not a
Work live PASS. A later fresh environment reproduced the same missing-root-runtime
condition and also confirmed that relying on `uv sync --frozen` inside a DNS-blocked
Host is not sufficient. The wheelhouse path above exists specifically so package
resolution/download happens outside the Host and the Host performs only verified,
no-index installation.

After provisioning, #401 requires actual public execution, whole-set transfer and
reopen, and delivery of an openable canonical preview. #337 additionally requires
the fresh UAT-02R4 Work transcript and human rubric at the same relevant HEAD as
Codex. CI/documentation success does not satisfy those live gates.

Use the smallest relevant controls: omit runtime provisioning and retain the
startup failure; restore the same stopped set and compare public saved identities;
retain interrupted/failed transfer without treating it as restored; verify that a
missing preview file cannot be reported ready. Do not add a bypass or duplicate
research engine solely for these controls.
