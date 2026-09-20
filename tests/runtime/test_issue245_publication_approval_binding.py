from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.publication_release_service import _digest, _json_bytes, _sha, _verify_docx_bytes
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue220_publication_release as publication_support


class PublicationApprovalBindingTests(ResearchPackageAcceptanceSupport):
    def _released(self):
        helper = publication_support.Issue220PublicationReleaseTests()
        helper.root = self.root
        helper.workspace = self.workspace
        facade, _case, composition, imported, _source = helper._prepared()
        self.addCleanup(facade.close)
        build = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])["build"]
        request = facade.request_publication_release(build["build_id"], "HUMAN-RELEASE")["decision_request"]
        response = helper._approval(request)
        released = facade.release_publication(build["build_id"], response)["release"]
        root = self.workspace / ".research-loom" / "publication" / "releases" / released["release_id"]
        return facade, build, request, response, released, root

    def test_artifact_only_and_self_consistent_unapproved_output_are_rejected(self):
        facade, build, _request, response, manifest, root = self._released()
        artifact = root / "artifact.docx"
        original = artifact.read_bytes()
        changed = original + b"\nUNAPPROVED-TRAILER\n"
        self.assertTrue(_verify_docx_bytes(changed))
        artifact.write_bytes(changed)
        # A structurally valid DOCX is not necessarily the approved output.
        with self.assertRaises(LocalApplicationError):
            facade.release_publication(build["build_id"], response)
        forged = deepcopy(manifest)
        forged["output"]["size"] = len(changed)
        forged["output"]["digest"] = _sha(changed)
        forged["content_digest"] = _digest(forged, "content_digest")
        (root / "release-manifest.json").write_bytes(_json_bytes(forged))
        with self.assertRaises(LocalApplicationError) as raised:
            facade.release_publication(build["build_id"], response)
        self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-INTEGRITY-001")
        artifact.write_bytes(original)
        (root / "release-manifest.json").write_bytes(_json_bytes(manifest))
        self.assertEqual(facade.release_publication(build["build_id"], response)["status"], "VERIFIED_REUSE")

    def test_self_consistent_manifest_cannot_change_any_approved_binding(self):
        facade, build, _request, response, manifest, root = self._released()
        mutations = [
            ("release_id", "REL-OTHER"),
            ("source_preview", {**manifest["source_preview"], "preview_id": "PUB-OTHER"}),
            ("source_manuscript", {**manifest["source_manuscript"], "revision_id": "REV-OTHER"}),
            ("research_provenance", {**manifest["research_provenance"], "research_package_id": "RP-OTHER"}),
            ("publication_profile", {**manifest["publication_profile"], "profile_version": "99.0.0"}),
            ("output", {**manifest["output"], "artifact_reference": "elsewhere/artifact.docx"}),
            ("verification", {"render_verification": "passed"}),
        ]
        decision = manifest["human_release_decision"]
        for field, value in (("request_id", "REQ-OTHER"), ("request_digest", "sha256:" + "0" * 64), ("actor", {"actor_id": "OTHER", "actor_type": "human"}), ("disposition", "decline")):
            changed = {**decision, field: value}
            changed["decision_digest"] = _digest(changed, "decision_digest")
            mutations.append(("human_release_decision", changed))
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                forged = {**manifest, field: value}
                forged["content_digest"] = _digest(forged, "content_digest")
                (root / "release-manifest.json").write_bytes(_json_bytes(forged))
                with self.assertRaises(LocalApplicationError) as raised:
                    facade.release_publication(build["build_id"], response)
                self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-INTEGRITY-001")
        (root / "release-manifest.json").write_bytes(_json_bytes(manifest))
        self.assertEqual(facade.release_publication(build["build_id"], response)["release"], manifest)

    def test_reopen_and_later_clock_preserve_exact_release(self):
        facade, build, request, response, manifest, _root = self._released()
        before = facade.status()["snapshot"]
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with patch.object(reopened._application.clock, "now", return_value="2099-01-01T00:00:00Z"):
                request_retry = reopened.request_publication_release(build["build_id"], request["human_actor_id"])
                release_retry = reopened.release_publication(build["build_id"], response)
            self.assertEqual(request_retry["status"], "VERIFIED_REUSE")
            self.assertEqual(request_retry["decision_request"], request)
            self.assertEqual(release_retry["status"], "VERIFIED_REUSE")
            self.assertEqual(release_retry["release"], manifest)
            self.assertEqual(reopened.status()["snapshot"], before)

    def test_request_reuse_checks_binding_and_record_parse_errors_are_diagnostic(self):
        facade, build, request, response, manifest, root = self._released()
        request_path = facade._publication_release_service()._release_request_path(request["request_id"])
        forged = deepcopy(request)
        forged["output_binding"]["digest"] = "sha256:" + "0" * 64
        forged["request_digest"] = _digest(forged, "request_digest")
        request_path.write_bytes(_json_bytes(forged))
        with self.assertRaises(LocalApplicationError):
            facade.request_publication_release(build["build_id"], request["human_actor_id"])
        request_path.write_bytes(_json_bytes(request))
        for path in (request_path, root / "release-manifest.json"):
            original = path.read_bytes()
            for bad in (b"{", b"null", b"[]", b"\xff"):
                with self.subTest(path=path.name, bad=bad):
                    path.write_bytes(bad)
                    with self.assertRaises(LocalApplicationError) as raised:
                        facade.release_publication(build["build_id"], response)
                    self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-INTEGRITY-001")
            path.write_bytes(original)
        self.assertEqual(facade.release_publication(build["build_id"], response)["release"], manifest)
