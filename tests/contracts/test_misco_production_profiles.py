from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import rfc8785

from plugins.local_application import LocalWorkspace
import plugins.local_application.profile_resolution as profile_resolution
from plugins.local_application.profile_resolution import resolve_effective_profile_set
from plugins.local_application.research_package_format import profile_resources
from plugins.local_application.workspace import LocalWorkspaceError

ROOT = Path(__file__).resolve().parents[2]
WRITER_MANIFEST = ROOT / "profiles/narrative/misco/profile.json"
PUBLICATION_MANIFEST = ROOT / "profiles/publication/misco/profile.json"
WRITER_ASSET = ROOT / "profiles/narrative/misco/resources/writer-clean-rules.json"
WRITER_SOURCE_ASSET = ROOT / "profiles/narrative/misco/resources/writer-clean-source-documents.json"
PUBLICATION_ASSET = ROOT / "profiles/publication/misco/resources/publication-clean-rules.json"
PUBLICATION_FORMAL_SPEC = ROOT / "profiles/publication/misco/resources/publication-formal-spec.json"
PUBLICATION_URL_DISPLAY = ROOT / "profiles/publication/misco/resources/publication-url-display.json"
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
RESEARCH_FIXTURE = ROOT / "profiles/fixtures/research-quality/valid/generic-research-quality.profile.json"


def config_for_publication() -> dict:
    return {
        "profile_requests": {
            "research": [],
            "organization": [],
            "narrative": [],
            "publication": [
                {"profile_id": "misco.publication", "profile_type": "publication", "version": "1.2.0"}
            ],
        }
    }


def workspace_config() -> dict:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["profile_requests"] = deepcopy(config_for_publication()["profile_requests"])
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config.pop("configuration_digest", None)
    config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
    return config


class MiscoProductionProfileTests(unittest.TestCase):
    def test_production_resolution_is_order_independent_and_exposes_rule_bodies(self):
        expected = None
        manifests = [WRITER_MANIFEST, PUBLICATION_MANIFEST]
        for seed in range(8):
            ordered = manifests[:]
            random.Random(seed).shuffle(ordered)
            eps = resolve_effective_profile_set(config_for_publication(), ordered)
            encoded = rfc8785.dumps(eps)
            expected = encoded if expected is None else expected
            self.assertEqual(expected, encoded)
        self.assertEqual(
            [(x["profile_type"], x["profile_id"], x["profile_version"]) for x in eps["effective_profiles"]],
            [("narrative", "misco.writer", "1.1.0"), ("publication", "misco.publication", "1.2.0")],
        )
        resources = {x["role"]: x for x in eps["effective_resources"]}
        self.assertEqual(set(resources), {"WRITER_RULES", "WRITER_SOURCE_DOCUMENTS", "PUBLICATION_RULES", "PUBLICATION_SOURCE_DOCUMENTS", "PUBLICATION_FORMAL_SPEC", "PUBLICATION_URL_DISPLAY"})
        for resource in resources.values():
            self.assertEqual(hashlib.sha256(resource["content"].encode()).hexdigest(), resource["sha256"])
            self.assertEqual(len(resource["content"].encode()), resource["byte_length"])
            self.assertTrue(resource["provenance"])

    def test_migration_assets_cover_clean_rules_without_audit_review_or_synthetic_material(self):
        writer = json.loads(WRITER_ASSET.read_text(encoding="utf-8"))
        publication = json.loads(PUBLICATION_ASSET.read_text(encoding="utf-8"))
        writer_pub = {x["id"] for x in writer["items"] if x["id"].startswith("PUB-") and len(x["id"].split("-")) == 3}
        publication_pub = {x["id"] for x in publication["items"] if x["id"].startswith("PUB-") and len(x["id"].split("-")) == 3}
        self.assertEqual((len(writer_pub), len(publication_pub), len(writer_pub | publication_pub)), (39, 12, 51))
        self.assertFalse(writer_pub & publication_pub)
        self.assertEqual(writer["canonical_pub_rule_count"], 39)
        self.assertEqual(publication["canonical_pub_rule_count"], 12)
        self.assertTrue(all(item["migration"]["issue"] == 334 for item in writer["items"]))
        self.assertTrue(all(item["migration"]["issue"] == 335 for item in publication["items"]))
        for item in writer["items"] + publication["items"]:
            self.assertTrue(item["approval"], item["id"])
            self.assertTrue(item["migration"]["responsibility"], item["id"])
            self.assertTrue((ROOT / item["source"]["path"]).is_file(), item["id"])
        self.assertTrue(all("Layer_B" not in item["source"]["path"] and "Layer_C" not in item["source"]["path"] for item in writer["items"] + publication["items"]))
        self.assertNotIn("synthetic-example-spec", {item["class"] for item in writer["items"]})
        source_asset = json.loads(WRITER_SOURCE_ASSET.read_text(encoding="utf-8"))
        source_documents = {row["path"]: row for row in source_asset["source_documents"]}
        self.assertEqual(set(source_documents), {item["source"]["path"] for item in writer["items"]})
        self.assertEqual(source_asset["document_count"], 8)
        expected_writer_ids_by_source = {}
        for item in writer["items"]:
            expected_writer_ids_by_source.setdefault(item["source"]["path"], set()).add(item["id"])
        self.assertEqual(
            {rule_id for row in source_documents.values() for rule_id in row["writer_rule_ids"]},
            {item["id"] for item in writer["items"]},
        )
        for source_path, row in source_documents.items():
            self.assertEqual(set(row["writer_rule_ids"]), expected_writer_ids_by_source[source_path])
            raw = (ROOT / source_path).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(row["content"].encode("utf-8"), raw)
            self.assertEqual(row["byte_length"], len(raw))
            self.assertEqual(row["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertNotIn("09_SYNTHETIC_FEWSHOT_SPECIFICATION", source_path)
            self.assertNotIn("Layer_B", source_path)
            self.assertNotIn("Layer_C", source_path)
        self.assertEqual(
            {x["id"] for x in publication["missing_inputs"]},
            {"INPUT-FORMAL-SPEC", "INPUT-URL-DISPLAY", "INPUT-RESEARCH-GROUP-TYPE", "INPUT-PERMISSION"},
        )

    def test_publication_formal_and_url_resources_are_pinned_to_supplied_authority(self):
        formal = json.loads(PUBLICATION_FORMAL_SPEC.read_text(encoding="utf-8"))
        profile = formal["formal_spec_profile"]
        self.assertEqual(formal["source_archive"]["sha256"], "10e91d2ba7b9fa1f2f6eeede18baf623a8428d8db45995053b9494b26efb4e6c")
        self.assertFalse(formal["source_archive"]["repository_copy"])
        self.assertEqual(len(formal["source_members"]), 7)
        self.assertEqual(profile["reference_list_placement"], "end_of_each_section")
        self.assertEqual(profile["reference_list_heading"], "＜参考文献＞")
        self.assertEqual(profile["docx_layout"]["page_width_twips"], 11906)
        self.assertEqual(profile["docx_layout"]["margin_top_twips"], 1701)
        self.assertEqual(profile["docx_layout"]["body_font"], "ＭＳ 明朝")
        self.assertEqual(profile["docx_layout"]["body_latin_font"], "Century")
        self.assertEqual(profile["docx_layout"]["heading_font"], "ＭＳ ゴシック")
        self.assertEqual(profile["docx_layout"]["doc_grid_line_pitch_twips"], 335)

        url = json.loads(PUBLICATION_URL_DISPLAY.read_text(encoding="utf-8"))
        self.assertEqual(url["decision"], "長いURLも参考文献には原則全文表示する。")
        self.assertEqual(url["url_display_profile"]["template"], "{title} {url}")
        self.assertEqual(
            url["url_display_profile"]["source"]["source_digest"],
            "sha256:3eb4934dce6273220442ef9d703187690c13dbf3e7a611728068a505a9237629",
        )

    def test_resource_digest_ablation_rejects_same_manifest_identity_with_modified_body(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "profiles/narrative") as temp:
            base = Path(temp)
            (base / "resources").mkdir()
            body = WRITER_ASSET.read_text(encoding="utf-8") + " "
            (base / "resources/writer-clean-rules.json").write_text(body, encoding="utf-8")
            (base / "resources/writer-clean-source-documents.json").write_bytes(WRITER_SOURCE_ASSET.read_bytes())
            manifest = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
            manifest["profile_id"] = "misco.writer-ablation"
            path = base / "profile.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            config = {"profile_requests": {"research": [], "organization": [], "narrative": [{"profile_id": "misco.writer-ablation", "profile_type": "narrative", "version": "1.1.0"}], "publication": []}}
            with self.assertRaises(LocalWorkspaceError) as raised:
                resolve_effective_profile_set(config, [path])
            self.assertEqual(raised.exception.code, "PROFILE-RESOURCE-DIGEST-001")

    def test_missing_resource_fails_closed_without_legacy_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "profiles/narrative") as temp:
            base = Path(temp)
            manifest = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
            manifest["profile_id"] = "misco.writer-missing-resource"
            path = base / "profile.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            config = {"profile_requests": {"research": [], "organization": [], "narrative": [{"profile_id": "misco.writer-missing-resource", "profile_type": "narrative", "version": "1.1.0"}], "publication": []}}
            with self.assertRaises(LocalWorkspaceError) as raised:
                resolve_effective_profile_set(config, [path])
            self.assertEqual(raised.exception.code, "PROFILE-RESOURCE-SOURCE-001")

    def test_production_resolver_enforces_research_quality_closed_catalog(self):
        config = {"profile_requests": {"research": [{"profile_id": "fixture.generic-research-quality", "profile_type": "research", "version": "1.0.0"}], "organization": [], "narrative": [], "publication": []}}
        self.assertTrue(resolve_effective_profile_set(config, [RESEARCH_FIXTURE])["effective_constraints"])
        with tempfile.TemporaryDirectory(dir=ROOT / "profiles/research") as temp:
            path = Path(temp) / "profile.json"
            manifest = json.loads(RESEARCH_FIXTURE.read_text(encoding="utf-8"))
            manifest["profile_id"] = "misco.invalid-research-quality"
            manifest["constraints"] = [{"id": "bad", "path": "research_quality.evidence.magic_score", "merge_strategy": "max", "value": 1}]
            path.write_text(json.dumps(manifest), encoding="utf-8")
            bad = {"profile_requests": {"research": [{"profile_id": manifest["profile_id"], "profile_type": "research", "version": "1.0.0"}], "organization": [], "narrative": [], "publication": []}}
            with self.assertRaises(LocalWorkspaceError) as raised:
                resolve_effective_profile_set(bad, [path])
            self.assertEqual(raised.exception.code, "PROFILE-RESEARCH-QUALITY-PATH-001")

    def test_research_quality_enum_set_rejects_non_string_json_without_type_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "profiles/research") as temp:
            path = Path(temp) / "profile.json"
            manifest = json.loads(RESEARCH_FIXTURE.read_text(encoding="utf-8"))
            manifest["profile_id"] = "misco.invalid-research-quality-value"
            enum_constraint = next(item for item in manifest["constraints"] if isinstance(item["value"], list))
            enum_constraint["value"] = [{}]
            path.write_text(json.dumps(manifest), encoding="utf-8")
            bad = {"profile_requests": {"research": [{"profile_id": manifest["profile_id"], "profile_type": "research", "version": "1.0.0"}], "organization": [], "narrative": [], "publication": []}}
            with self.assertRaises(LocalWorkspaceError) as raised:
                resolve_effective_profile_set(bad, [path])
            self.assertEqual(raised.exception.code, "PROFILE-RESEARCH-QUALITY-VALUE-001")

    def test_duplicate_resource_declaration_deduplicates_provenance(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "profiles/narrative") as temp:
            base = Path(temp)
            (base / "resources").mkdir()
            (base / "resources/writer-clean-rules.json").write_bytes(WRITER_ASSET.read_bytes())
            (base / "resources/writer-clean-source-documents.json").write_bytes(WRITER_SOURCE_ASSET.read_bytes())
            manifest = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
            manifest["profile_id"] = "misco.writer-duplicate-resource"
            manifest["resources"] = manifest["resources"] * 2
            path = base / "profile.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            config = {"profile_requests": {"research": [], "organization": [], "narrative": [{"profile_id": manifest["profile_id"], "profile_type": "narrative", "version": "1.1.0"}], "publication": []}}
            eps = resolve_effective_profile_set(config, [path])
            self.assertEqual(len(eps["effective_resources"]), 2)
            self.assertTrue(all(len(row["provenance"]) == 1 for row in eps["effective_resources"]))

    def test_resource_bounds_fail_before_unbounded_reads(self):
        with patch.object(profile_resolution, "MAX_PROFILE_RESOURCE_BYTES", 1):
            with self.assertRaises(LocalWorkspaceError) as raised:
                resolve_effective_profile_set(
                    {"profile_requests": {"research": [], "organization": [], "narrative": [{"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.1.0"}], "publication": []}},
                    [WRITER_MANIFEST],
                )
        self.assertEqual(raised.exception.code, "PROFILE-RESOURCE-BOUND-001")

        with tempfile.TemporaryDirectory(dir=ROOT / "profiles/narrative") as temp:
            base = Path(temp)
            (base / "resources").mkdir()
            (base / "resources/writer-clean-rules.json").write_bytes(WRITER_ASSET.read_bytes())
            (base / "resources/writer-clean-source-documents.json").write_bytes(WRITER_SOURCE_ASSET.read_bytes())
            manifest = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
            manifest["profile_id"] = "misco.writer-too-many-resources"
            manifest["resources"] = manifest["resources"] * 2
            path = base / "profile.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            config = {"profile_requests": {"research": [], "organization": [], "narrative": [{"profile_id": manifest["profile_id"], "profile_type": "narrative", "version": "1.1.0"}], "publication": []}}
            with patch.object(profile_resolution, "MAX_PROFILE_RESOURCES", 1):
                with self.assertRaises(LocalWorkspaceError) as raised:
                    resolve_effective_profile_set(config, [path])
            self.assertEqual(raised.exception.code, "PROFILE-RESOURCE-BOUND-001")

        with patch.object(profile_resolution, "MAX_EFFECTIVE_RESOURCES", 1):
            with patch.object(profile_resolution, "_normalized_resource_bytes", wraps=profile_resolution._normalized_resource_bytes) as reader:
                with self.assertRaises(LocalWorkspaceError) as raised:
                    resolve_effective_profile_set(config_for_publication(), [WRITER_MANIFEST, PUBLICATION_MANIFEST])
        self.assertEqual(raised.exception.code, "PROFILE-RESOURCE-BOUND-001")
        self.assertEqual(reader.call_count, 0)

        with patch.object(profile_resolution, "MAX_EFFECTIVE_RESOURCE_BYTES", 1):
            with patch.object(profile_resolution, "_normalized_resource_bytes", side_effect=AssertionError("resource body must not be read past the effective byte bound")):
                with self.assertRaises(LocalWorkspaceError) as raised:
                    resolve_effective_profile_set(
                        {"profile_requests": {"research": [], "organization": [], "narrative": [{"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.1.0"}], "publication": []}},
                        [WRITER_MANIFEST],
                    )
        self.assertEqual(raised.exception.code, "PROFILE-RESOURCE-BOUND-001")

    def test_research_package_handoff_projection_keeps_rule_bodies_and_pins(self):
        eps = resolve_effective_profile_set(config_for_publication(), [WRITER_MANIFEST, PUBLICATION_MANIFEST])
        projected = profile_resources(eps)
        self.assertEqual(projected, eps["effective_resources"])
        self.assertIsNot(projected, eps["effective_resources"])
        self.assertEqual({x["role"] for x in projected}, {"WRITER_RULES", "WRITER_SOURCE_DOCUMENTS", "PUBLICATION_RULES", "PUBLICATION_SOURCE_DOCUMENTS", "PUBLICATION_FORMAL_SPEC", "PUBLICATION_URL_DISPLAY"})
        self.assertTrue(all(x["content"] for x in projected))
        self.assertTrue(all(x["provenance"] for x in projected))

    def test_workspace_reopen_and_detached_json_keep_rule_text_without_profile_sources(self):
        eps = resolve_effective_profile_set(config_for_publication(), [WRITER_MANIFEST, PUBLICATION_MANIFEST])
        config = workspace_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, eps_path = root / "config.json", root / "eps.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            eps_path.write_text(json.dumps(eps, ensure_ascii=False), encoding="utf-8")
            workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config_path, eps_path)
            opened.close()
            with LocalWorkspace.open(workspace) as reopened:
                resources = reopened.effective_profile_set["effective_resources"]
                self.assertEqual({x["role"] for x in resources}, {"WRITER_RULES", "WRITER_SOURCE_DOCUMENTS", "PUBLICATION_RULES", "PUBLICATION_SOURCE_DOCUMENTS", "PUBLICATION_FORMAL_SPEC", "PUBLICATION_URL_DISPLAY"})
                self.assertTrue(all(x["content"] for x in resources))
            detached = root / "detached.json"
            detached.write_text(json.dumps(eps, ensure_ascii=False), encoding="utf-8")
            code = (
                "import json,sys; x=json.load(open(sys.argv[1],encoding='utf-8')); "
                "r={i['role']:i for i in x['effective_resources']}; "
                "assert set(r)=={'WRITER_RULES','WRITER_SOURCE_DOCUMENTS','PUBLICATION_RULES','PUBLICATION_SOURCE_DOCUMENTS','PUBLICATION_FORMAL_SPEC','PUBLICATION_URL_DISPLAY'}; "
                "assert all(i['content'] for i in r.values())"
            )
            result = subprocess.run([sys.executable, "-c", code, str(detached)], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
