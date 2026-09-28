import hashlib, json, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/migration/misco-profile-migration-ledger"
PACK = ROOT / "research-profile/publication/authority/MISCO_Publication_Clean_Source_Pack_v1.0.2_HUMAN_APPROVED"


def load(name):
    return json.loads((LEDGER / name).read_text(encoding="utf-8"))


def items(doc, tokens=None):
    tokens = tokens or doc.get("source_tokens", {})
    out = []
    for values in doc["rules"]:
        row = dict(zip(doc["columns"], values))
        if "source" in row:
            row["source"] = tokens.get(row["source"], row["source"])
        if row.get("alias_sources"):
            row["alias_sources"] = [tokens.get(x, x) for x in row["alias_sources"]]
        out.append(row)
    return out


def source_rows(index):
    out = []
    for name in index["source_shards"]:
        doc = load(name)
        out += [dict(zip(doc["columns"], row)) for row in doc["rows"]]
    return out


class MiscoProfileMigrationLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load("index.json")
        cls.project = items(load("project.json"))
        cls.tokens = load("writer-source-tokens.json")["source_tokens"]
        cls.writer = sum((items(load(n), cls.tokens) for n in cls.index["shards"] if n.startswith("writer-") and n != "writer-source-tokens.json"), [])
        cls.publication = items(load("publication.json"))
        cls.support = items(load("support.json"))

    def test_baseline_and_shards_are_explicit(self):
        self.assertEqual(self.index["issue"], 331)
        self.assertEqual(self.index["baseline"]["commit"], "1ea6ad38fcf09eab24e44aa7e5bb4b6afec90578")
        self.assertTrue(all((LEDGER / n).is_file() for n in self.index["shards"]))

    def test_pinned_sources_match_repository_bytes(self):
        seen = set()
        for row in source_rows(self.index):
            self.assertNotIn(row["path"], seen); seen.add(row["path"])
            path = ROOT / row["path"]
            self.assertEqual("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
            self.assertEqual(path.stat().st_size, row["bytes"])

    def test_source_pack_inventory_is_complete(self):
        recorded = {x["path"] for x in source_rows(self.index)}
        actual = {p.relative_to(ROOT).as_posix() for p in PACK.rglob("*") if p.is_file()}
        self.assertTrue(actual); self.assertEqual(actual - recorded, set())

    def test_source_pack_manifest_digests_match(self):
        manifest = json.loads((PACK / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), self.index["source_pack"]["manifest_entries"])
        for row in manifest:
            p = PACK / row["path"]
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), row["sha256"])
            self.assertEqual(p.stat().st_size, row["bytes"])

    def test_all_51_runtime_rules_have_one_policy_identity(self):
        contract = json.loads((PACK / "Layer_A_CLEAN_RUNTIME_SOURCE_PACK/01_PUBLICATION_STYLE_CONTRACT.json").read_text(encoding="utf-8"))
        expected = {x["runtime_rule_id"] for x in contract}
        actual = [x["id"] for x in self.writer + self.publication if re.fullmatch(r"PUB-[A-Z]{2}-\d{2}", x["id"])]
        self.assertEqual(len(expected), 51); self.assertEqual(set(actual), expected); self.assertEqual(len(actual), len(set(actual)))
        canonical = [x for x in self.writer + self.publication if x["id"] in expected]
        self.assertTrue(all("approval" in x and "applicator" in x for x in canonical))

    def test_layer_a_named_views_are_covered(self):
        ids = {x["id"] for x in self.writer}
        self.assertEqual({f"PAT-{i:02d}" for i in range(1,19)} - ids, set())
        self.assertEqual({f"NG-{i:02d}" for i in range(1,22)} - ids, set())
        self.assertEqual({f"SF-{i:02d}" for i in range(1,15)} - ids, set())
        for prefix in ("PHASE-SPECIFIC-WRITING", "TERM-", "QA-", "ASSEMBLY-"):
            self.assertTrue(any(x == prefix or x.startswith(prefix) for x in ids))

    def test_project_sources_remain_project_scoped(self):
        classes = {x["class"] for x in self.project}
        self.assertIn("project-attention", classes); self.assertIn("project-knowledge", classes)
        feedback = [x for x in self.project if x["class"] == "project-knowledge"]
        self.assertTrue(feedback); self.assertTrue(all(x["issue"] == 336 and "non-canonical" in x.get("boundary", "") for x in feedback))

    def test_audit_review_and_synthetic_material_are_not_runtime_policy(self):
        self.assertTrue(all(not x["runtime"] for x in self.support if x["class"] in {"audit-provenance", "human-review", "legacy-consumer"}))
        self.assertTrue(all(not x["runtime_authority"] for x in self.writer if x["class"] == "synthetic-example-spec"))

    def test_unfinished_runtime_classes_have_child_issue_and_responsibility(self):
        for name, spec in self.index["migration_classes"].items():
            self.assertIn("responsibility", spec, name); self.assertIn(spec["issue"], {332,333,334,335,336,337}); self.assertIn("runtime", spec, name)

    def test_missing_formal_inputs_are_explicit_and_narrow(self):
        gaps = {x["id"]: x for x in self.index["missing_inputs"]}
        self.assertEqual(set(gaps), {"INPUT-FORMAL-SPEC","INPUT-URL-DISPLAY","INPUT-RESEARCH-GROUP-TYPE","INPUT-PERMISSION"})
        self.assertIn("must not be invented", gaps["INPUT-URL-DISPLAY"]["must_not"])
        self.assertIn("only", gaps["INPUT-FORMAL-SPEC"]["when_missing"]); self.assertIn("only", gaps["INPUT-RESEARCH-GROUP-TYPE"]["when_missing"])

    def test_bounded_ablation_detects_omission_but_not_alias_representation(self):
        ids = [x["id"] for x in self.writer + self.publication if re.fullmatch(r"PUB-[A-Z]{2}-\d{2}", x["id"])]
        expected = set(ids)
        self.assertEqual(expected - {x for x in ids if x != "PUB-FR-01"}, {"PUB-FR-01"})
        fr = next(x for x in self.publication if x["id"] == "PUB-FR-01")
        aliases = list(fr["alias_sources"]) + ["another-rendering.md"]
        self.assertGreater(len(aliases), len(fr["alias_sources"])); self.assertEqual((expected-set(ids), len(ids) != len(set(ids))), (set(), False))


if __name__ == "__main__": unittest.main()
