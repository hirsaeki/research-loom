from __future__ import annotations

from copy import deepcopy
import json
import os
import subprocess
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_service import verify_export_root
import research_package_acceptance_baseline as baseline
import test_external_desktop_research_intake as intake


class ResearchPackageAcceptanceTests(baseline.ResearchPackageAcceptanceTests):
    def test_rp1_public_cli_round_trip_is_detached_from_workspace(self):
        facade, case = self._prepare_case()
        facade.close()
        build_input = self.root / "rp-build.json"
        build_input.write_text(json.dumps(case["build_input"]), encoding="utf-8")
        launcher = [str(intake.ROOT / "research-loom")] if os.name != "nt" else [
            "cmd.exe", "/d", "/s", "/c", str(intake.ROOT / "research-loom.cmd")
        ]

        def run(*args):
            completed = subprocess.run(
                [*launcher, *map(str, args)], cwd=intake.ROOT, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
            return json.loads(completed.stdout)

        built = run("research-package", "build", "--workspace", self.workspace, "--json-input", build_input)
        package_id = built["package"]["package_id"]
        shown = run("research-package", "show", "--workspace", self.workspace, "--package-id", package_id, "--json")
        self.assertEqual(
            shown["package"]["resolved_content"]["working_material"]["project_inputs"][0]["content"]["value"],
            case["project_input_text"],
        )
        output = self.root / "cli-detached"
        run("research-package", "export", "--workspace", self.workspace, "--package-id", package_id, "--output", output, "--json")
        unavailable = self.root / "workspace-unavailable"
        self.workspace.rename(unavailable)
        verified = run("research-package", "verify", "--input", output, "--json")
        self.assertEqual(verified["status"], "VERIFIED")
        package = json.loads((output / "research-package.json").read_text(encoding="utf-8"))
        material = package["resolved_content"]["materials"][0]
        project_input = package["resolved_content"]["working_material"]["project_inputs"][0]
        self.assertEqual((output / material["text_rendition"]["attachment_path"]).read_text(encoding="utf-8"), case["source_text"])
        self.assertEqual((output / project_input["content"]["attachment_path"]).read_text(encoding="utf-8"), case["project_input_text"])

    def test_ablation_body_resolution_is_required_for_detached_use(self):
        facade, case = self._build()
        try:
            normal = self.root / "ablation-real"
            facade.export_research_package(case["package_id"], normal)
            package = json.loads((normal / "research-package.json").read_text(encoding="utf-8"))
        finally:
            facade.close()

        def detached_material_text(value, root):
            rel = value["resolved_content"]["materials"][0]["text_rendition"]["attachment_path"]
            return (root / rel).read_text(encoding="utf-8")

        self.assertEqual(detached_material_text(package, normal), case["source_text"])
        legacy = {k: deepcopy(v) for k, v in package.items() if k not in {"resolved_profiles", "resolved_content", "attachments", "projections"}}
        legacy["schema_version"] = "0.1.0"
        legacy["package_digest"] = "sha256:" + "0" * 64
        from plugins.local_application.research_package_format import validate_schema
        validate_schema(legacy)
        with self.assertRaises(KeyError):
            detached_material_text(legacy, self.root)

    def test_ablation_package_digest_rejects_inline_tamper(self):
        facade, case = self._build()
        try:
            output = self.root / "digest-ablation"
            facade.export_research_package(case["package_id"], output)
        finally:
            facade.close()
        package_path = output / "research-package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["resolved_content"]["research_objects"][0]["text"] = "same-shape tamper"
        package_path.write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(LocalApplicationError):
            verify_export_root(output)
        with patch(
            "plugins.local_application.research_package_format.digest_json",
            return_value=package["package_digest"],
        ):
            self.assertEqual(verify_export_root(output)["status"], "VERIFIED")


if __name__ == "__main__":
    import unittest
    unittest.main()
