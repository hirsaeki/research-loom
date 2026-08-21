# Harness Distribution and Upgrade Contract v0.1

The Harness distribution is separate from a Research workspace. A Harness
source contains the executable control plane, declared core contracts, tests,
and the Publication Writer integration contract. A Profile is a separately
versioned declarative pack of static, explicitly classified inputs.

## Sources and provenance

`harness.manifest.json` and `profile.manifest.json` declare the allowed source
paths and target paths. A source may be a local checkout, a local archive, or
an HTTP(S) archive. Archive extraction rejects path traversal, symlinks,
special files, and `.git` content. The source ref and content hashes are
recorded in the generated workspace `harness.lock.json`.

The lock is workspace provenance, not Research Evidence. It must remain
outside `.rh/` so a separate research Git repository can track it.

## New workspace

`rh new` copies only manifest-declared Harness and Profile files. It never
copies `.git`, `.rh`, prior state, decisions, runs, or old Map versions. A
Profile Map is inert input during `rh new`; the new workspace remains Map-less
unless a later explicit Harness operation changes that state.

`--init-git` only initializes a new Git repository. It does not stage, commit,
configure a remote, or push.

## Upgrade

`rh upgrade` is an explicit Human operation. It stages and validates the new
source before replacing managed files. Core and Profile paths are independently
owned and their file sets must remain stable; path additions/removals require a
separate migration.

The operation refuses to mutate an archived workspace or a workspace with
pending Work, pending Human Decisions, pending Attention drops, or transition
locks. It also refuses when a managed file differs from the hash in the prior
lock. No `git reset --hard`, `git clean`, Research State rewind, or research
artifact deletion is allowed.

When core contract or policy files change, the Artifact Registry refresh is
part of the same transaction. A refresh failure restores the prior managed
files, lock, and `.rh` runtime. Successful upgrades write an immutable upgrade
receipt under `.rh/lifecycle/upgrades/`.

## Remote publication boundary

The Harness core and each Profile are separate repositories. Remote
publication is an explicit operator action after local validation and commit.
On the Windows Codex path, the approved `codex-safe-push.ps1` wrapper should be
run outside the Sandbox so Git can use the real user's Credential Manager
context. The wrapper must remain non-force and same-branch; it must not push
tags implicitly. A trusted checkout with a different filesystem owner may be
added as one exact `safe.directory` path, but a wildcard exception is not
permitted.
