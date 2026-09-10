from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from contextlib import redirect_stdout
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import rfc8785

from core.runtime import CommitReceipt, TransitionAction, TransitionKind
from plugins.local_application import LocalApplicationFacade, LocalWorkspace
from plugins.local_application.cli import main as cli_main
from plugins.local_application.profile_advancement import _ADVANCEMENT_NOTE
from plugins.local_application.profile_resolution import _sha256, effective_profile_digest, resolve_effective_profile_set
from runtime_fixtures import make_request
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_external_desktop_research_intake as intake
from test_profile_constraint_enforcement import _source, _evidence


ROOT = Path(__file__).resolve().parents[2]
OLD_EPS = ROOT / "profiles/fixtures/valid/effective-profile-set.json"
OLD_NARRATIVE = ROOT / "profiles/fixtures/valid/narrative.profile.json"
GENERIC_NARRATIVE = ROOT / "profiles/fixtures/narrative/valid/generic-narrative.profile.json"
PUBLICATION = ROOT / "profiles/fixtures/valid/publication.profile.json"
ORGANIZATION = ROOT / "profiles/fixtures/valid/organization.profile.json"
RESEARCH_STRICT = ROOT / "profiles/fixtures/valid/research-strict.profile.json"
RESEARCH_BASE = ROOT / "profiles/fixtures/valid/research-base.profile.json"
STATE_PUBLICATION = ROOT / "profiles/fixtures/profile-generation/valid/state-incompatible-publication.profile.json"
STATE_RESEARCH = ROOT / "profiles/fixtures/profile-generation/valid/state-incompatible-research.profile.json"
WEAK_PUBLICATION = ROOT / "profiles/fixtures/profile-generation/valid/core-weak-publication.profile.json"
COLLIDING_NARRATIVE = ROOT / "profiles/fixtures/profile-generation/invalid/generic-narrative-same-version-modified.profile.json"
MODIFIED_VERSION_TARGET = ROOT / "profiles/fixtures/profile-generation/invalid/version-target-2.1.0-modified.profile.json"
INVALID_NARRATIVE = ROOT / "profiles/fixtures/profile-generation/invalid/narrative-invalid-product.profile.json"
REQUIRED_NARRATIVE_PATHS = {
    "narrative.stages.definitions",
    "narrative.dependencies.required",
    "narrative.section_purposes.definitions",
    "narrative.preservation.required_content",
    "narrative.connections.preserve",
}


def _json_digest(config: dict) -> str:
    payload = deepcopy(config)
    payload.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def _run_cli(argv, stdin_text=""):
    stream = io.StringIO()
    with patch("sys.stdin", io.StringIO(stdin_text)), redirect_stdout(stream):
        code = cli_main([str(item) for item in argv])
    return code, json.loads(stream.getvalue())


class ProfileGenerationAdvancementTests(ResearchPackageAcceptanceSupport):
    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        cfg = self.root / "project-config-input.json"
        eps = self.root / "profiles-input.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps.write_text(OLD_EPS.read_text(encoding="utf-8"), encoding="utf-8")
        return cfg, eps

    def _normal_manifest_files(self):
        return [str(PUBLICATION), str(ORGANIZATION), str(RESEARCH_STRICT), str(RESEARCH_BASE), str(GENERIC_NARRATIVE)]

    def _resolve_request(self, *, extra_replacements=None, manifests=None):
        replacements = [
            {
                "from": {"profile_id":"fixture.narrative","profile_type":"narrative","version":"1.0.0"},
                "to": {"profile_id":"fixture.generic-narrative","profile_type":"narrative","version":"1.0.0"},
            }
        ]
        replacements.extend(extra_replacements or [])
        return {"profile_manifest_files": manifests or self._normal_manifest_files(), "request_replacements": replacements}

    def _resolve(self, request=None, name="resolved"):
        request = request or self._resolve_request()
        request_path = self.root / f"{name}-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        output = self.root / name
        code, result = _run_cli(["profile","resolve","--workspace",self.workspace,"--output",output,"--json",request_path])
        self.assertEqual(code, 0, result)
        return request, output, result

    def _advance(self, request, output):
        payload = {
            "project_config_file": str(output / "project-config.json"),
            "effective_profile_set_file": str(output / "effective-profile-set.json"),
            "profile_manifest_files": request["profile_manifest_files"],
            "origin": "issue-128-acceptance",
        }
        path = self.root / "advance.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return _run_cli(["profile","advance","--workspace",self.workspace,"--json",path])

    def _history(self):
        code, result = _run_cli(["profile","history","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0, result)
        return result


    def test_manifest_pin_is_checkout_line_ending_independent(self):
        manifest = PUBLICATION.read_bytes().replace(b"\r\n", b"\n")
        lf_path = self.root / "manifest-lf.json"
        crlf_path = self.root / "manifest-crlf.json"
        lf_path.write_bytes(manifest)
        crlf_path.write_bytes(manifest.replace(b"\n", b"\r\n"))
        self.assertEqual(_sha256(lf_path), _sha256(crlf_path))
        self.assertEqual(_sha256(lf_path), json.loads(OLD_EPS.read_text(encoding="utf-8"))["effective_profiles"][-1]["manifest_sha256"])



    def test_kody_concurrent_advancement_is_serialized_across_the_full_rebind(self):
        request, output, _ = self._resolve()
        payload = {
            "project_config_file": str(output / "project-config.json"),
            "effective_profile_set_file": str(output / "effective-profile-set.json"),
            "profile_manifest_files": request["profile_manifest_files"],
            "origin": "kody-concurrency-regression",
        }
        from plugins.local_application import profile_advancement as advancement

        real_rebind = advancement._state_rebind
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        call_guard = threading.Lock()
        calls = 0
        results = []
        errors = []

        def blocking_rebind(*args, **kwargs):
            nonlocal calls
            with call_guard:
                calls += 1
                call_number = calls
            if call_number == 1:
                first_entered.set()
                if not release_first.wait(5):
                    raise AssertionError("first advancement was not released")
            else:
                second_entered.set()
            return real_rebind(*args, **kwargs)

        def run_advance():
            try:
                results.append(advancement.advance_profile_generation(self.workspace, payload))
            except Exception as exc:  # surfaced below with the original exception
                errors.append(exc)

        with patch.object(advancement, "_state_rebind", side_effect=blocking_rebind):
            first = threading.Thread(target=run_advance)
            second = threading.Thread(target=run_advance)
            first.start()
            self.assertTrue(first_entered.wait(5))
            second.start()
            time.sleep(0.2)
            self.assertFalse(second_entered.is_set(), "second advancement entered the rebind while the first held the workspace lock")
            release_first.set()
            first.join(5)
            second.join(5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())

        self.assertEqual(errors, [])
        self.assertCountEqual([item["result"] for item in results], ["ADVANCED", "NOOP"])
        history = self._history()
        self.assertEqual(len(history["events"]), 1)

    def test_kody_recovery_rejects_workspace_escape_locators_before_deletion(self):
        marker_path = Path(self.workspace) / ".research-loom" / "profile-advancement.pending.json"
        binding = json.loads((Path(self.workspace) / ".research-loom" / "workspace-binding.json").read_text(encoding="utf-8"))
        config_text = (Path(self.workspace) / "project-config.json").read_text(encoding="utf-8")
        eps_text = (Path(self.workspace) / "effective-profile-set.json").read_text(encoding="utf-8")
        config = json.loads(config_text)
        eps = json.loads(eps_text)
        base_marker = {
            "schema_version": "0.1.0",
            "old_binding": binding,
            "new_binding": binding,
            "old_project_config": config,
            "old_effective_profile_set": eps,
            "old_project_config_text": config_text,
            "old_effective_profile_set_text": eps_text,
            "new_project_config": config,
            "new_effective_profile_set": eps,
        }

        outside_file = self.root / "outside-event.json"
        outside_file.write_text("keep\n", encoding="utf-8")
        marker = {**base_marker, "event_locator": "../outside-event.json", "created_history_paths": []}
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        code, rejected = _run_cli(["resume", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 2, rejected)
        self.assertEqual(rejected["issues"][0]["code"], "WORKSPACE-PATH-001")
        self.assertEqual(outside_file.read_text(encoding="utf-8"), "keep\n")
        marker_path.unlink()

        outside_dir = self.root / "outside-history"
        outside_dir.mkdir()
        sentinel = outside_dir / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        marker = {**base_marker, "event_locator": None, "created_history_paths": ["../outside-history"]}
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        code, rejected = _run_cli(["resume", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 2, rejected)
        self.assertEqual(rejected["issues"][0]["code"], "WORKSPACE-PATH-001")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")
        marker_path.unlink()

    def test_kody_profile_resolver_bounds_inputs_and_prunes_incompatible_branches(self):
        from plugins.local_application import profile_resolution as resolution

        over_limit = self._resolve_request(manifests=[str(PUBLICATION)] * (resolution.MAX_PROFILE_MANIFESTS + 1))
        over_limit_path = self.root / "over-limit.json"
        over_limit_path.write_text(json.dumps(over_limit), encoding="utf-8")
        code, rejected = _run_cli([
            "profile", "resolve", "--workspace", self.workspace, "--output", self.root / "over-limit-out", "--json", over_limit_path
        ])
        self.assertEqual(code, 2, rejected)
        self.assertEqual(rejected["issues"][0]["code"], "PROFILE-CANDIDATE-LIMIT-001")

        def candidate(profile_id, version, *, requires=None):
            return {
                "manifest": {
                    "profile_id": profile_id,
                    "profile_type": "research",
                    "profile_version": version,
                    "core_compatibility": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
                    "requires": requires or [],
                },
                "manifest_sha256": hashlib.sha256(f"{profile_id}@{version}".encode()).hexdigest(),
                "path": f"/{profile_id}-{version}.json",
            }

        candidates = [
            candidate("fixture.requested", "2.0.0", requires=[{"profile_id":"fixture.dep","profile_type":"research","version":">=2.0.0 <3.0.0"}]),
            candidate("fixture.requested", "1.0.0", requires=[{"profile_id":"fixture.dep","profile_type":"research","version":"1.0.0"}]),
            candidate("fixture.dep", "1.0.0"),
        ]
        for index in range(40):
            candidates.extend([candidate(f"fixture.unrelated-{index:02d}", "1.0.0"), candidate(f"fixture.unrelated-{index:02d}", "2.0.0")])
        requests = [{"profile_id":"fixture.requested","profile_type":"research","version":">=1.0.0 <3.0.0"}]
        effective, selected = resolution._resolve_selected(candidates, requests)
        self.assertEqual({key for key in selected}, {("research", "fixture.requested"), ("research", "fixture.dep")})
        self.assertEqual(selected[("research", "fixture.requested")]["manifest"]["profile_version"], "1.0.0")
        self.assertEqual([item["profile_id"] for item in effective], ["fixture.dep", "fixture.requested"])

    def test_pa0_production_resolution_rejects_semantically_invalid_narrative_target(self):
        request = {
            "profile_manifest_files": [
                str(PUBLICATION), str(ORGANIZATION), str(RESEARCH_STRICT), str(RESEARCH_BASE), str(INVALID_NARRATIVE)
            ],
            "request_replacements": [
                {
                    "from": {"profile_id": "fixture.narrative", "profile_type": "narrative", "version": "1.0.0"},
                    "to": {"profile_id": "fixture.generation-invalid-narrative", "profile_type": "narrative", "version": "1.0.0"},
                }
            ],
        }
        path = self.root / "invalid-narrative-resolve.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        code, rejected = _run_cli([
            "profile", "resolve", "--workspace", self.workspace, "--output", self.root / "invalid-narrative-out", "--json", path
        ])
        self.assertEqual(code, 2, rejected)
        self.assertEqual(rejected["issues"][0]["code"], "PROFILE-NARRATIVE-VALUE-001")
        self.assertFalse((self.root / "invalid-narrative-out").exists())

    def test_pa0_pa1_pa2_pa3_pa4_same_workspace_recovery_and_detached_round_trip(self):
        # PA0: current main's canonical generic Narrative Profile is a new identity,
        # so this legacy generation needs a mechanical Project Config request update.
        legacy = json.loads(OLD_NARRATIVE.read_text(encoding="utf-8"))
        generic = json.loads(GENERIC_NARRATIVE.read_text(encoding="utf-8"))
        self.assertEqual(legacy["profile_version"], generic["profile_version"])
        self.assertNotEqual(legacy["profile_id"], generic["profile_id"])

        facade, case = self._prepare_case()
        before_state = facade.resume_context()
        before_run = facade.show_run(case["run_id"])
        before_exhibit = facade.show_exhibit(case["exhibit_id"])
        facade.close()

        # PA1: same A2-like inputs fail under the old generation and do not mutate state.
        build_input = self.root / "same-package-build.json"
        build_input.write_text(json.dumps(case["build_input"]), encoding="utf-8")
        code, failed = _run_cli(["research-package","build","--workspace",self.workspace,"--json",build_input])
        self.assertEqual(code, 2, failed)
        self.assertEqual(failed["issues"][0]["code"], "APPLICATION-RESEARCH-PACKAGE-PROFILE-001")
        code, after_failed = _run_cli(["resume","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0)
        self.assertEqual(after_failed["research_state"], before_state["research_state"])
        self.assertEqual(after_failed["research_questions"]["authoritative"], before_state["research_questions"]["authoritative"])

        request, output, resolved = self._resolve()
        self.assertTrue(resolved["profile_request_changed"])
        target_config = json.loads((output / "project-config.json").read_text(encoding="utf-8"))
        target_eps = json.loads((output / "effective-profile-set.json").read_text(encoding="utf-8"))
        self.assertEqual(target_config["profile_requests"]["narrative"][0]["profile_id"], "fixture.generic-narrative")
        self.assertTrue(REQUIRED_NARRATIVE_PATHS <= {item["path"] for item in target_eps["effective_constraints"]})
        self.assertIn(json.loads((self.root / "project-config-input.json").read_text(encoding="utf-8"))["configuration_digest"], target_config["provenance"]["derived_from_configuration_digests"])
        self.assertIn(_ADVANCEMENT_NOTE, target_config["provenance"]["notes"])

        # PA2: advance both Project Config request and EPS atomically.
        code, advanced = self._advance(request, output)
        self.assertEqual(code, 0, advanced)
        self.assertEqual(advanced["result"], "ADVANCED")
        history = self._history()
        self.assertEqual(len(history["events"]), 1)
        self.assertEqual(len(history["generations"]), 2)
        generation_pairs = {
            (item["project_config_digest"], item["effective_profile_set_digest"])
            for item in history["generations"]
        }
        self.assertIn((advanced["old_project_config_digest"], advanced["old_effective_profile_set_digest"]), generation_pairs)
        self.assertIn((advanced["new_project_config_digest"], advanced["new_effective_profile_set_digest"]), generation_pairs)
        history_by_pair = {
            (item["project_config_digest"], item["effective_profile_set_digest"]): item
            for item in history["generations"]
        }
        old_generation = history_by_pair[(advanced["old_project_config_digest"], advanced["old_effective_profile_set_digest"])]
        new_generation = history_by_pair[(advanced["new_project_config_digest"], advanced["new_effective_profile_set_digest"])]
        self.assertEqual(old_generation["project_config"], json.loads((self.root / "project-config-input.json").read_text(encoding="utf-8")))
        self.assertEqual(old_generation["effective_profile_set"], json.loads(OLD_EPS.read_text(encoding="utf-8")))
        self.assertEqual(new_generation["project_config"], target_config)
        self.assertEqual(new_generation["effective_profile_set"], target_eps)

        # PA3: historical run/exhibit/RQ/snapshot remain exact historical provenance.
        code, after_advance = _run_cli(["resume","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0)
        self.assertEqual(after_advance["research_state"]["snapshot"], before_state["research_state"]["snapshot"])
        self.assertEqual(after_advance["research_questions"]["authoritative"], before_state["research_questions"]["authoritative"])
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            self.assertEqual(reopened.show_run(case["run_id"]), before_run)
            self.assertEqual(reopened.show_exhibit(case["exhibit_id"]), before_exhibit)

        # PA4: exact same Workspace/RQ/material/Exhibit selection now builds and round-trips.
        code, built = _run_cli(["research-package","build","--workspace",self.workspace,"--json",build_input])
        self.assertEqual(code, 0, built)
        package_id = built["package"]["package_id"]
        code, shown = _run_cli(["research-package","show","--workspace",self.workspace,"--package-id",package_id,"--json"])
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["package"]["project_config_digest"], advanced["new_project_config_digest"])
        self.assertEqual(shown["package"]["effective_profile_set"]["content_digest"], advanced["new_effective_profile_set_digest"])
        export = self.root / "detached"
        code, exported = _run_cli(["research-package","export","--workspace",self.workspace,"--package-id",package_id,"--output",export,"--json"])
        self.assertEqual(code, 0, exported)

        launcher = [sys.executable, "-m", "plugins.local_application.cli"]
        verified = subprocess.run([*launcher,"research-package","verify","--input",str(export),"--json"], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(verified.returncode, 0, verified.stderr or verified.stdout)
        self.assertEqual(json.loads(verified.stdout)["status"], "VERIFIED")
        probe = subprocess.run(
            [
                sys.executable, "-c",
                "import json,sys,pathlib; p=json.loads((pathlib.Path(sys.argv[1])/'research-package.json').read_text(encoding='utf-8')); "
                "paths={x['path'] for x in p['resolved_profiles']['effective_constraints']}; "
                "need=set(sys.argv[4].split(',')); assert need<=paths; "
                "assert p['effective_profile_set']['content_digest']==sys.argv[2]; assert p['project_config_digest']==sys.argv[3]; "
                "m=p['resolved_content']['materials'][0]; assert (pathlib.Path(sys.argv[1])/m['text_rendition']['attachment_path']).read_text(encoding='utf-8')==sys.argv[5]; "
                "e=p['resolved_content']['working_material']['research_exhibits'][0]; assert e['content']['value']==sys.argv[6]",
                str(export),
                advanced["new_effective_profile_set_digest"],
                advanced["new_project_config_digest"],
                ",".join(sorted(REQUIRED_NARRATIVE_PATHS)),
                case["source_text"],
                before_exhibit["exhibit"]["content"]["value"],
            ],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr or probe.stdout)

        package = json.loads((export / "research-package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["resolved_content"]["working_material"]["project_inputs"][0]["content"]["value"], case["project_input_text"])



    def test_eps_only_advancement_keeps_project_config_exact_when_request_range_is_unchanged(self):
        version_root = ROOT / "profiles/fixtures/semantic/version-resolution/candidates"
        initial_manifests = [
            version_root / "publication.profile.json",
            version_root / "organization.profile.json",
            version_root / "target-1.5.0.profile.json",
            version_root / "target-2.1.0.profile.json",
        ]
        advanced_manifests = [*initial_manifests, version_root / "target-2.4.0.profile.json"]
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "narrative": [],
            "publication": [
                {"profile_id": "fixture.version-root", "profile_type": "publication", "version": "1.0.0"}
            ],
        }
        config["configuration_digest"] = _json_digest(config)
        initial_eps = resolve_effective_profile_set(config, initial_manifests)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / "config.json"
            eps = root / "effective.json"
            cfg.write_text(json.dumps(config), encoding="utf-8")
            eps.write_text(json.dumps(initial_eps), encoding="utf-8")
            opened = LocalWorkspace.init(root / "workspace", project_config_file=cfg, effective_profile_set_file=eps)
            workspace = opened.root
            opened.close()

            request = {"profile_manifest_files": [str(path) for path in advanced_manifests], "request_replacements": []}
            request_path = root / "resolve.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output = root / "resolved"
            code, resolved = _run_cli(["profile", "resolve", "--workspace", workspace, "--output", output, "--json", request_path])
            self.assertEqual(code, 0, resolved)
            self.assertFalse(resolved["profile_request_changed"])
            self.assertEqual(resolved["source_project_config_digest"], resolved["target_project_config_digest"])
            target_eps = json.loads((output / "effective-profile-set.json").read_text(encoding="utf-8"))
            selected = {(item["profile_id"], item["profile_version"]) for item in target_eps["effective_profiles"]}
            self.assertIn(("fixture.version-target", "2.4.0"), selected)

            advance_payload = {
                "project_config_file": str(output / "project-config.json"),
                "effective_profile_set_file": str(output / "effective-profile-set.json"),
                "profile_manifest_files": request["profile_manifest_files"],
                "origin": "eps-only-route",
            }
            advance_path = root / "advance.json"
            advance_path.write_text(json.dumps(advance_payload), encoding="utf-8")
            code, advanced = _run_cli(["profile", "advance", "--workspace", workspace, "--json", advance_path])
            self.assertEqual(code, 0, advanced)
            self.assertEqual(advanced["result"], "ADVANCED")
            self.assertEqual(advanced["old_project_config_digest"], advanced["new_project_config_digest"])
            self.assertNotEqual(advanced["old_effective_profile_set_digest"], advanced["new_effective_profile_set_digest"])
            with LocalApplicationFacade.open_workspace(workspace) as reopened:
                state = reopened.resume_context()["research_state"]
                self.assertEqual(state["bindings"]["project_config"]["digest"], config["configuration_digest"])
                self.assertEqual(state["bindings"]["effective_profile_set"]["digest"], advanced["new_effective_profile_set_digest"])


    def test_pa5_rejects_same_profile_identity_version_content_substitution(self):
        version_root = ROOT / "profiles/fixtures/semantic/version-resolution/candidates"
        old_manifests = [
            version_root / "publication.profile.json",
            version_root / "organization.profile.json",
            version_root / "target-1.5.0.profile.json",
            version_root / "target-2.1.0.profile.json",
        ]
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "narrative": [],
            "publication": [
                {"profile_id": "fixture.version-root", "profile_type": "publication", "version": "1.0.0"}
            ],
        }
        config["configuration_digest"] = _json_digest(config)
        initial_eps = resolve_effective_profile_set(config, old_manifests)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / "config.json"
            eps = root / "effective.json"
            cfg.write_text(json.dumps(config), encoding="utf-8")
            eps.write_text(json.dumps(initial_eps), encoding="utf-8")
            opened = LocalWorkspace.init(root / "workspace", project_config_file=cfg, effective_profile_set_file=eps)
            workspace = opened.root
            opened.close()

            target_manifests = [
                version_root / "publication.profile.json",
                version_root / "organization.profile.json",
                version_root / "target-1.5.0.profile.json",
                MODIFIED_VERSION_TARGET,
            ]
            request = {"profile_manifest_files": [str(path) for path in target_manifests], "request_replacements": []}
            request_path = root / "resolve.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output = root / "resolved"
            code, resolved = _run_cli(["profile", "resolve", "--workspace", workspace, "--output", output, "--json", request_path])
            self.assertEqual(code, 0, resolved)
            self.assertFalse(resolved["profile_request_changed"])

            payload = {
                "project_config_file": str(output / "project-config.json"),
                "effective_profile_set_file": str(output / "effective-profile-set.json"),
                "profile_manifest_files": request["profile_manifest_files"],
                "origin": "same-identity-substitution",
            }
            advance_path = root / "advance.json"
            advance_path.write_text(json.dumps(payload), encoding="utf-8")
            code, rejected = _run_cli(["profile", "advance", "--workspace", workspace, "--json", advance_path])
            self.assertEqual(code, 2, rejected)
            self.assertEqual(rejected["issues"][0]["code"], "PROFILE-ADVANCE-IDENTITY-001")
            code, history = _run_cli(["profile", "history", "--workspace", workspace, "--json"])
            self.assertEqual(code, 0, history)
            self.assertEqual(history["events"], [])
            self.assertEqual(history["generations"], [])
            code, resumed = _run_cli(["resume", "--workspace", workspace, "--json"])
            self.assertEqual(code, 0, resumed)
            self.assertEqual(resumed["research_state"]["bindings"]["effective_profile_set"]["digest"], effective_profile_digest(initial_eps))

    def test_pa5_rejects_bad_schema_digest_request_mismatch_identity_swap_core_weakening_and_project_semantics(self):
        request, output, _ = self._resolve()
        before = self._history()
        code, resume_before = _run_cli(["resume","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0)

        def attempt(config, eps, manifests=None):
            cfg = self.root / ("bad-config-" + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8] + ".json")
            ep = self.root / ("bad-eps-" + hashlib.sha256(json.dumps(eps, sort_keys=True).encode()).hexdigest()[:8] + ".json")
            cfg.write_text(json.dumps(config), encoding="utf-8")
            ep.write_text(json.dumps(eps), encoding="utf-8")
            payload = {"project_config_file":str(cfg),"effective_profile_set_file":str(ep),"profile_manifest_files":manifests or request["profile_manifest_files"],"origin":"pa5"}
            path = self.root / "bad-advance.json"; path.write_text(json.dumps(payload), encoding="utf-8")
            return _run_cli(["profile","advance","--workspace",self.workspace,"--json",path])

        target_config = json.loads((output / "project-config.json").read_text(encoding="utf-8"))
        target_eps = json.loads((output / "effective-profile-set.json").read_text(encoding="utf-8"))

        bad_schema = deepcopy(target_eps); bad_schema.pop("schema_version")
        self.assertNotEqual(attempt(target_config, bad_schema)[0], 0)

        bad_digest = deepcopy(target_config); bad_digest["communication_brief"]["core_message"] += " changed"
        self.assertNotEqual(attempt(bad_digest, target_eps)[0], 0)

        mismatched = json.loads(OLD_EPS.read_text(encoding="utf-8"))
        self.assertNotEqual(attempt(target_config, mismatched)[0], 0)

        swapped = deepcopy(target_eps)
        generic_profile = next(item for item in swapped["effective_profiles"] if item["profile_id"] == "fixture.generic-narrative")
        generic_profile["manifest_sha256"] = "0" * 64
        self.assertNotEqual(attempt(target_config, swapped)[0], 0)

        weakened = deepcopy(target_eps)
        strengthened = next(item for item in weakened["core_invariants"] if item["status"] == "strengthened")
        strengthened["status"] = "preserved"; strengthened["provenance"] = []
        self.assertNotEqual(attempt(target_config, weakened)[0], 0)

        out_of_scope = deepcopy(target_config)
        out_of_scope["communication_brief"]["core_message"] += " semantically changed"
        out_of_scope["configuration_digest"] = _json_digest(out_of_scope)
        self.assertNotEqual(attempt(out_of_scope, target_eps)[0], 0)

        collision_request = self._resolve_request(manifests=[*self._normal_manifest_files(), str(COLLIDING_NARRATIVE)])
        collision_path = self.root / "collision.json"; collision_path.write_text(json.dumps(collision_request), encoding="utf-8")
        code, collision = _run_cli(["profile","resolve","--workspace",self.workspace,"--output",self.root/"collision-out","--json",collision_path])
        self.assertEqual(code, 2, collision)
        self.assertEqual(collision["issues"][0]["code"], "PROFILE-CANDIDATE-IDENTITY-001")

        self.assertEqual(self._history(), before)
        code, resume_after = _run_cli(["resume","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0)
        self.assertEqual(resume_after["research_state"], resume_before["research_state"])

    def test_pa5_rejects_authoritative_state_incompatible_target_and_core_weak_target(self):
        # Add authoritative Source/Evidence that satisfies the old generation.
        with LocalWorkspace.open(self.workspace) as opened:
            state = opened.application.state_repository.load_state_view(opened.project_id, opened.application.state_repository.load_active_lineage_ref(opened.project_id))
            result = opened.application.state_transition_service.apply(make_request(
                state,
                [
                    TransitionAction(TransitionKind.CREATE_OBJECT, {"object": _source(opened.project_id)}),
                    TransitionAction(TransitionKind.CREATE_OBJECT, {"object": _evidence(opened.project_id, with_capture_digest=True)}),
                ],
                suffix="128-state",
            ))
            self.assertIsInstance(result, CommitReceipt)

        state_manifests = [str(STATE_PUBLICATION),str(STATE_RESEARCH),str(ORGANIZATION),str(RESEARCH_STRICT),str(RESEARCH_BASE),str(GENERIC_NARRATIVE)]
        state_request = self._resolve_request(
            manifests=state_manifests,
            extra_replacements=[{
                "from":{"profile_id":"fixture.publication","profile_type":"publication","version":"1.0.0"},
                "to":{"profile_id":"fixture.generation-state-publication","profile_type":"publication","version":"1.0.0"},
            }],
        )
        state_request, state_out, _ = self._resolve(state_request, name="state-incompatible")
        before = self._history()
        code, rejected = self._advance(state_request, state_out)
        self.assertEqual(code, 2, rejected)
        self.assertEqual(rejected["issues"][0]["code"], "PROFILE-ADVANCE-STATE-COMPAT-001")
        self.assertEqual(self._history(), before)

        weak_manifests = [str(WEAK_PUBLICATION), str(GENERIC_NARRATIVE)]
        weak_request = self._resolve_request(
            manifests=weak_manifests,
            extra_replacements=[{
                "from":{"profile_id":"fixture.publication","profile_type":"publication","version":"1.0.0"},
                "to":{"profile_id":"fixture.generation-core-weak-publication","profile_type":"publication","version":"1.0.0"},
            }],
        )
        weak_request, weak_out, _ = self._resolve(weak_request, name="core-weak")
        code, rejected = self._advance(weak_request, weak_out)
        self.assertEqual(code, 2, rejected)
        self.assertEqual(rejected["issues"][0]["code"], "PROFILE-ADVANCE-CORE-WEAKENING-001")
        self.assertEqual(self._history(), before)

    def test_pa6_write_failure_recovers_old_binding_and_exact_reapply_is_noop(self):
        request, output, _ = self._resolve()
        code, before_resume = _run_cli(["resume","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0)
        before_history = self._history()

        from plugins.local_application import profile_advancement as advancement
        real_rebind = advancement._state_rebind
        with patch.object(advancement, "_state_rebind", side_effect=RuntimeError("injected write failure")):
            code, failed = self._advance(request, output)
        self.assertEqual(code, 3, failed)
        code, after_reopen = _run_cli(["resume","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0, after_reopen)
        self.assertEqual(after_reopen["research_state"], before_resume["research_state"])
        self.assertEqual(self._history(), before_history)

        # Baseline after restoring the guard succeeds.
        with patch.object(advancement, "_state_rebind", wraps=real_rebind):
            code, advanced = self._advance(request, output)
        self.assertEqual(code, 0, advanced)
        self.assertEqual(advanced["result"], "ADVANCED")
        history = self._history()
        event_count = len(history["events"])
        code, noop = self._advance(request, output)
        self.assertEqual(code, 0, noop)
        self.assertEqual(noop["result"], "NOOP")
        self.assertEqual(len(self._history()["events"]), event_count)
        code, final_resume = _run_cli(["resume","--workspace",self.workspace,"--json"])
        self.assertEqual(code, 0)
        self.assertEqual(final_resume["research_state"]["snapshot"], before_resume["research_state"]["snapshot"])

    def test_ablation_old_new_history_guard_is_detected_then_baseline_restored(self):
        request, output, _ = self._resolve()
        from plugins.local_application import profile_advancement as advancement
        real_archive = advancement._archive_generation

        def ablated_archive(root, *, config_text, effective_text, config_digest, profile_digest):
            # Remove only the old-generation history write; keep the target generation.
            current = json.loads((Path(root) / ".research-loom" / "workspace-binding.json").read_text(encoding="utf-8"))
            if config_digest == current["project_config"]["digest"]:
                return []
            return real_archive(root, config_text=config_text, effective_text=effective_text, config_digest=config_digest, profile_digest=profile_digest)

        with patch.object(advancement, "_archive_generation", side_effect=ablated_archive):
            code, advanced = self._advance(request, output)
        self.assertEqual(code, 0, advanced)
        history = self._history()
        old_pair = (advanced["old_project_config_digest"], advanced["old_effective_profile_set_digest"])
        pairs = {(item["project_config_digest"], item["effective_profile_set_digest"]) for item in history["generations"]}
        self.assertNotIn(old_pair, pairs, "ablation must expose loss of the historical generation")

        # A fresh identical fixture with the guard restored is the baseline.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = intake.bootstrap_config()
            cfg = root / "config.json"; eps = root / "eps.json"
            cfg.write_text(json.dumps(config), encoding="utf-8"); eps.write_text(OLD_EPS.read_text(encoding="utf-8"), encoding="utf-8")
            opened = LocalWorkspace.init(root / "workspace", cfg, eps); opened.close()
            resolve_in = root / "resolve.json"; resolve_in.write_text(json.dumps(self._resolve_request()), encoding="utf-8")
            code, _ = _run_cli(["profile","resolve","--workspace",root/"workspace","--output",root/"resolved","--json",resolve_in]); self.assertEqual(code, 0)
            advance_in = root / "advance.json"; advance_in.write_text(json.dumps({"project_config_file":str(root/"resolved/project-config.json"),"effective_profile_set_file":str(root/"resolved/effective-profile-set.json"),"profile_manifest_files":self._normal_manifest_files(),"origin":"ablation-baseline"}), encoding="utf-8")
            code, baseline = _run_cli(["profile","advance","--workspace",root/"workspace","--json",advance_in]); self.assertEqual(code, 0, baseline)
            code, baseline_history = _run_cli(["profile","history","--workspace",root/"workspace","--json"]); self.assertEqual(code, 0)
            baseline_pairs = {(item["project_config_digest"], item["effective_profile_set_digest"]) for item in baseline_history["generations"]}
            self.assertIn((baseline["old_project_config_digest"], baseline["old_effective_profile_set_digest"]), baseline_pairs)


if __name__ == "__main__":
    unittest.main()
