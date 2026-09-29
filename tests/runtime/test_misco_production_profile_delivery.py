from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import rfc8785

from plugins.local_application.profile_resolution import resolve_effective_profile_set
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_external_desktop_research_intake as intake

ROOT = Path(__file__).resolve().parents[2]
WRITER_MANIFEST = ROOT / "profiles/narrative/misco/profile.json"
PUBLICATION_MANIFEST = ROOT / "profiles/publication/misco/profile.json"


class MiscoProductionProfileDeliveryTests(ResearchPackageAcceptanceSupport):
    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "narrative": [],
            "publication": [
                {"profile_id": "misco.publication", "profile_type": "publication", "version": "1.2.0"}
            ],
        }
        config.pop("configuration_digest", None)
        config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
        eps = resolve_effective_profile_set(config, [WRITER_MANIFEST, PUBLICATION_MANIFEST])
        cfg = self.root / "project-config-input.json"
        eps_path = self.root / "profiles-input.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps_path.write_text(json.dumps(eps, ensure_ascii=False), encoding="utf-8")
        return cfg, eps_path

    def test_research_package_keeps_profile_rule_bodies_for_detached_writer_publication(self):
        facade, case = self._build()
        package = facade._research_package_service().show(case["package_id"])["package"]
        resources = package["effective_profile_set"]["effective_resources"]
        self.assertEqual({x["role"] for x in resources}, {"WRITER_RULES", "WRITER_SOURCE_DOCUMENTS", "PUBLICATION_RULES", "PUBLICATION_SOURCE_DOCUMENTS", "PUBLICATION_FORMAL_SPEC", "PUBLICATION_URL_DISPLAY"})
        self.assertTrue(all(x["content"] and x["provenance"] for x in resources))

        export_dir = self.root / "detached-package"
        facade._research_package_service().export(case["package_id"], export_dir)
        facade.close()
        shutil.rmtree(self.workspace)
        package_path = export_dir / "research-package.json"
        code = (
            "import json,sys; p=json.load(open(sys.argv[1],encoding='utf-8')); "
            "r={x['role']:x for x in p['effective_profile_set']['effective_resources']}; "
            "assert set(r)=={'WRITER_RULES','WRITER_SOURCE_DOCUMENTS','PUBLICATION_RULES','PUBLICATION_SOURCE_DOCUMENTS','PUBLICATION_FORMAL_SPEC','PUBLICATION_URL_DISPLAY'}; "
            "assert all(x['content'] for x in r.values())"
        )
        result = subprocess.run([sys.executable, "-c", code, str(package_path)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    import unittest
    unittest.main()
