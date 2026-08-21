from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
PROFILE_SCHEMA_PATH = ROOT / "profiles/contracts/profile-manifest.schema.json"
EFFECTIVE_SCHEMA_PATH = ROOT / "profiles/contracts/effective-profile-set.schema.json"
SEMANTICS_PATH = ROOT / "profiles/contracts/composition-semantics.yaml"
REGISTRY_PATH = ROOT / "profiles/contracts/invariant-strengthening-validators.yaml"
TYPE_RANK = {name: i for i, name in enumerate(["research", "organization", "narrative", "publication"])}
COMPARATOR = re.compile(r"^(>=|>|<=|<|=)(\d+\.\d+\.\d+)$")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semver(text: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in text.split("."))  # type: ignore[return-value]


def satisfies(version: str, requirement: str) -> bool:
    v = semver(version)
    if re.fullmatch(r"\d+\.\d+\.\d+", requirement):
        return v == semver(requirement)
    for token in requirement.split():
        m = COMPARATOR.fullmatch(token)
        if not m:
            raise ValueError(f"unsupported range token: {token}")
        op, rhs_text = m.groups()
        rhs = semver(rhs_text)
        if op == ">=" and not (v >= rhs):
            return False
        if op == ">" and not (v > rhs):
            return False
        if op == "<=" and not (v <= rhs):
            return False
        if op == "<" and not (v < rhs):
            return False
        if op == "=" and not (v == rhs):
            return False
    return True


def key_of(obj) -> tuple[str, str]:
    return obj["profile_type"], obj["profile_id"]


def keyver_of(obj) -> tuple[str, str, str]:
    return obj["profile_type"], obj["profile_id"], obj["profile_version"]


def pinned_ref(candidate):
    return {
        "profile_id": candidate["manifest"]["profile_id"],
        "profile_type": candidate["manifest"]["profile_type"],
        "profile_version": candidate["manifest"]["profile_version"],
        "manifest_sha256": candidate["manifest_sha256"],
    }


def canonical_profile_key(key: tuple[str, str]):
    return TYPE_RANK[key[0]], key[1]


def canonical_selection_key(src):
    relation_rank = {"requested": 0, "extends": 1, "requires": 2}
    intro = src.get("introduced_by") or {
        "profile_type": "research",
        "profile_id": "",
        "profile_version": "0.0.0",
        "manifest_sha256": "",
    }
    return (
        relation_rank[src["relation"]],
        TYPE_RANK[intro["profile_type"]],
        intro["profile_id"],
        semver(intro["profile_version"]),
        intro["manifest_sha256"],
        src["required_version"],
    )


def canonical_constraint_source_key(src):
    return (
        TYPE_RANK[src["profile_type"]],
        src["profile_id"],
        semver(src["profile_version"]),
        src["manifest_sha256"],
        src["constraint_id"],
    )


def core_compatibility_error(manifest, core_contracts):
    compat = manifest["core_compatibility"]
    if not satisfies(core_contracts["research_contract"], compat["research_contract"]):
        return "PROFILE-CORE-COMPAT-001"
    if not satisfies(core_contracts["invariant_contract"], compat["invariant_contract"]):
        return "PROFILE-CORE-COMPAT-001"
    return None


def effective_identity_error(eps):
    candidate_seen = {}
    for ref in eps["candidate_universe"]:
        k = keyver_of(ref)
        h = ref["manifest_sha256"]
        if k in candidate_seen and candidate_seen[k] != h:
            return "PROFILE-CANDIDATE-IDENTITY-001"
        candidate_seen[k] = h
    for field, identity in [
        ("requested_profiles", lambda x: key_of(x)),
        ("effective_profiles", lambda x: key_of(x)),
        ("effective_constraints", lambda x: x["path"]),
        ("core_invariants", lambda x: x["invariant_id"]),
    ]:
        seen = set()
        for item in eps[field]:
            k = identity(item)
            if k in seen:
                return "PROFILE-EFFECTIVE-IDENTITY-001"
            seen.add(k)
    return None


def effective_provenance_error(eps):
    selected = {
        (p["profile_type"], p["profile_id"], p["profile_version"], p["manifest_sha256"])
        for p in eps["effective_profiles"]
    }
    universe = {
        (p["profile_type"], p["profile_id"], p["profile_version"], p["manifest_sha256"])
        for p in eps["candidate_universe"]
    }
    if not selected <= universe:
        return "PROFILE-EFFECTIVE-PROVENANCE-001"

    def pin_tuple(src):
        return src["profile_type"], src["profile_id"], src["profile_version"], src["manifest_sha256"]

    for p in eps["effective_profiles"]:
        for source in p["selection_provenance"]:
            if source["relation"] != "requested" and pin_tuple(source["introduced_by"]) not in selected:
                return "PROFILE-EFFECTIVE-PROVENANCE-001"
    for c in eps["effective_constraints"]:
        for source in c["provenance"]:
            if pin_tuple(source) not in selected:
                return "PROFILE-EFFECTIVE-PROVENANCE-001"
    for inv in eps["core_invariants"]:
        for source in inv["provenance"]:
            if pin_tuple(source) not in selected:
                return "PROFILE-EFFECTIVE-PROVENANCE-001"
    return None


def find_registry_form(registry, strengthening):
    inv = registry["invariants"].get(strengthening["invariant_id"])
    if not inv or inv.get("strengthening_policy") != "registered_forms":
        return None
    binding = strengthening["validator_binding"]
    for validator in inv.get("validators", []):
        if validator["validator_id"] != binding["validator_id"] or validator["validator_version"] != binding["validator_version"]:
            continue
        for form in validator.get("approved_forms", []):
            if form["form_id"] == binding["form_id"]:
                return form
    return None


def strengthening_error(manifest, registry):
    constraints = {c["id"]: c for c in manifest.get("constraints", [])}
    for strengthening in manifest.get("core_invariant_strengthenings", []):
        form = find_registry_form(registry, strengthening)
        if form is None:
            return "PROFILE-CORE-STRENGTHENING-001"
        referenced = []
        for cid in strengthening["constraint_ids"]:
            c = constraints.get(cid)
            if c is None:
                return "PROFILE-MANIFEST-REF-001"
            referenced.append(c)
        for required in form.get("required_constraints", []):
            match = next(
                (c for c in referenced if c["path"] == required["path"] and c["merge_strategy"] == required["merge_strategy"]),
                None,
            )
            if match is None:
                return "PROFILE-CORE-STRENGTHENING-001"
            value_schema = required.get("value_schema", {})
            if "const" in value_schema and match["value"] != value_schema["const"]:
                return "PROFILE-CORE-STRENGTHENING-001"
    return None


def constraint_composition_error(manifests):
    by_path = {}
    for m in manifests:
        for c in m.get("constraints", []):
            by_path.setdefault(c["path"], []).append((m, c))
    for declarations in by_path.values():
        strategies = {c["merge_strategy"] for _, c in declarations}
        if len(strategies) > 1:
            return "PROFILE-COMP-STRATEGY-001"
        strategy = next(iter(strategies))
        values = [c["value"] for _, c in declarations]
        if strategy == "replace" and any(v != values[0] for v in values[1:]):
            if len({m["profile_type"] for m, _ in declarations}) > 1:
                return "PROFILE-COMP-REPLACE-001"
        if strategy == "must_equal" and any(v != values[0] for v in values[1:]):
            return "PROFILE-COMP-CONFLICT-001"
    return None


def load_candidate(path: Path):
    return {"manifest": load_json(path), "manifest_sha256": sha256_bytes(path), "path": path}


def assignment_valid(assignment, requests, core_contracts):
    selected = {k: c for k, c in assignment.items() if c is not None}
    requested_keys = {key_of(r) for r in requests}
    for req in requests:
        cand = selected.get(key_of(req))
        if cand is None or not satisfies(cand["manifest"]["profile_version"], req["version"]):
            return False
    reachable = set(requested_keys)
    frontier = list(requested_keys)
    while frontier:
        k = frontier.pop()
        cand = selected.get(k)
        if cand is None:
            return False
        m = cand["manifest"]
        if core_compatibility_error(m, core_contracts):
            return False
        for relation in ("extends", "requires"):
            for dep in m.get(relation, []):
                dk = key_of(dep)
                if relation == "extends" and dep["profile_type"] != m["profile_type"]:
                    return False
                target = selected.get(dk)
                if target is None or not satisfies(target["manifest"]["profile_version"], dep["version"]):
                    return False
                if dk not in reachable:
                    reachable.add(dk)
                    frontier.append(dk)
    if set(selected) != reachable:
        return False
    graph = {k: [] for k in selected}
    for k, cand in selected.items():
        for relation in ("extends", "requires"):
            for dep in cand["manifest"].get(relation, []):
                graph[k].append(key_of(dep))
    visiting, done = set(), set()

    def dfs(k):
        if k in visiting:
            return False
        if k in done:
            return True
        visiting.add(k)
        for nxt in graph[k]:
            if not dfs(nxt):
                return False
        visiting.remove(k)
        done.add(k)
        return True

    return all(dfs(k) for k in graph)


def resolve_candidates(candidates, requests, core_contracts):
    by_key = {}
    identities = {}
    for c in candidates:
        kv = keyver_of(c["manifest"])
        prev = identities.get(kv)
        if prev is not None and prev != c["manifest_sha256"]:
            return None, "PROFILE-CANDIDATE-IDENTITY-001"
        identities[kv] = c["manifest_sha256"]
        by_key.setdefault(key_of(c["manifest"]), []).append(c)
    keys = sorted(by_key, key=canonical_profile_key)
    choices = [[None] + sorted(by_key[k], key=lambda c: semver(c["manifest"]["profile_version"])) for k in keys]
    solutions = []
    for combo in itertools.product(*choices):
        assignment = dict(zip(keys, combo))
        if assignment_valid(assignment, requests, core_contracts):
            solutions.append(assignment)
    if not solutions:
        return None, "PROFILE-VERSION-001"
    absent = (-1, -1, -1)

    def vector(a):
        return tuple(absent if a[k] is None else semver(a[k]["manifest"]["profile_version"]) for k in keys)

    winner = max(solutions, key=vector)
    selected = {k: c for k, c in winner.items() if c is not None}
    output = []
    for k in sorted(selected, key=canonical_profile_key):
        c = selected[k]
        sources = []
        for req in requests:
            if key_of(req) == k:
                sources.append({"relation": "requested", "required_version": req["version"]})
        for intro_c in selected.values():
            for relation in ("extends", "requires"):
                for dep in intro_c["manifest"].get(relation, []):
                    if key_of(dep) == k:
                        sources.append({"relation": relation, "introduced_by": pinned_ref(intro_c), "required_version": dep["version"]})
        sources.sort(key=canonical_selection_key)
        output.append({**pinned_ref(c), "selection_provenance": sources})
    return output, None


def canonical_compose_constraints(candidates):
    groups = {}
    for c in candidates:
        for decl in c["manifest"].get("constraints", []):
            groups.setdefault(decl["path"], []).append((c, decl))
    result = []
    for path in sorted(groups):
        declarations = groups[path]
        strategy = declarations[0][1]["merge_strategy"]
        if any(d[1]["merge_strategy"] != strategy for d in declarations):
            raise ValueError("PROFILE-COMP-STRATEGY-001")
        values = [d[1]["value"] for d in declarations]
        if strategy == "union":
            members = []
            for value in values:
                members.extend(value)
            value = [x for _, x in sorted({json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False): x for x in members}.items())]
            resolution = "single" if len(declarations) == 1 else "union"
        elif strategy == "must_equal":
            if any(v != values[0] for v in values[1:]):
                raise ValueError("PROFILE-COMP-CONFLICT-001")
            value = values[0]
            resolution = "single" if len(declarations) == 1 else "identical"
        else:
            value = values[0]
            resolution = "single"
        provenance = [{**pinned_ref(c), "constraint_id": decl["id"]} for c, decl in declarations]
        provenance.sort(key=canonical_constraint_source_key)
        result.append({"path": path, "merge_strategy": strategy, "value": value, "resolution": resolution, "provenance": provenance})
    return result


class ProfileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_schema = load_json(PROFILE_SCHEMA_PATH)
        cls.effective_schema = load_json(EFFECTIVE_SCHEMA_PATH)
        cls.profile_validator = Draft202012Validator(cls.profile_schema)
        cls.effective_validator = Draft202012Validator(cls.effective_schema)
        cls.registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.semantics = yaml.safe_load(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_schemas_are_valid_draft_2020_12(self):
        Draft202012Validator.check_schema(self.profile_schema)
        Draft202012Validator.check_schema(self.effective_schema)

    def test_contract_yaml_parses_and_registry_covers_all_core_invariants(self):
        self.assertEqual(self.semantics["status"], "CANONICAL")
        core_ids = [x["id"] for x in yaml.safe_load((ROOT / "core/validators/non-overridable-invariants.yaml").read_text(encoding="utf-8"))["invariants"]]
        self.assertEqual(set(core_ids), set(self.registry["invariants"]))

    def test_valid_profile_fixtures_validate(self):
        for path in sorted((ROOT / "profiles/fixtures/valid").glob("*.profile.json")):
            self.assertFalse(list(self.profile_validator.iter_errors(load_json(path))), str(path))

    def test_valid_effective_fixture_validates_and_pins_manifest_bytes(self):
        eps = load_json(ROOT / "profiles/fixtures/valid/effective-profile-set.json")
        self.assertFalse(list(self.effective_validator.iter_errors(eps)))
        self.assertIsNone(effective_identity_error(eps))
        self.assertIsNone(effective_provenance_error(eps))
        actual = {}
        for path in sorted((ROOT / "profiles/fixtures/valid").glob("*.profile.json")):
            m = load_json(path)
            actual[keyver_of(m)] = sha256_bytes(path)
        for ref in eps["candidate_universe"] + eps["effective_profiles"]:
            self.assertEqual(actual[keyver_of(ref)], ref["manifest_sha256"])

    def test_schema_invalid_fixtures_fail(self):
        for name in ["cross-type-extends.profile.json", "core-invariant-weakening.profile.json", "merge-strategy-value-type.profile.json"]:
            self.assertTrue(list(self.profile_validator.iter_errors(load_json(ROOT / "profiles/fixtures/invalid" / name))), name)
        for name in ["effective-profile-set-status-provenance.json", "effective-profile-set-invalid-resolution.json"]:
            self.assertTrue(list(self.effective_validator.iter_errors(load_json(ROOT / "profiles/fixtures/invalid" / name))), name)

    def test_semantic_invalid_fixtures_are_schema_valid_then_fail_expected_code(self):
        cases = load_json(ROOT / "profiles/fixtures/contract-cases.json")["semantic_invalid"]
        for case in cases:
            objs = [load_json(ROOT / p) for p in case["fixtures"]]
            if case["kind"] == "profile_core_compatibility":
                self.assertFalse(list(self.profile_validator.iter_errors(objs[0])))
                actual = core_compatibility_error(objs[0], {"research_contract": "0.1.0", "invariant_contract": "0.1.0"})
            elif case["kind"] == "effective_identity":
                self.assertFalse(list(self.effective_validator.iter_errors(objs[0])))
                actual = effective_identity_error(objs[0])
            elif case["kind"] == "constraint_composition":
                for obj in objs:
                    self.assertFalse(list(self.profile_validator.iter_errors(obj)))
                actual = constraint_composition_error(objs)
            elif case["kind"] == "strengthening":
                self.assertFalse(list(self.profile_validator.iter_errors(objs[0])))
                actual = strengthening_error(objs[0], self.registry)
            else:
                self.fail(f"unknown case kind: {case['kind']}")
            self.assertEqual(case["expected_error"], actual, case["id"])

    def test_registered_strengthening_fixture_is_machine_distinguishable(self):
        valid = load_json(ROOT / "profiles/fixtures/valid/research-strict.profile.json")
        invalid = load_json(ROOT / "profiles/fixtures/invalid/unverifiable-core-strengthening.profile.json")
        self.assertIsNone(strengthening_error(valid, self.registry))
        self.assertEqual("PROFILE-CORE-STRENGTHENING-001", strengthening_error(invalid, self.registry))

    def test_version_resolution_intersects_transitive_ranges_and_selects_deterministically(self):
        case_dir = ROOT / "profiles/fixtures/semantic/version-resolution"
        case = load_json(case_dir / "case.json")
        base_candidates = [load_candidate(case_dir / "candidates" / name) for name in case["candidate_files"]]
        expected = [(x["profile_type"], x["profile_id"], x["profile_version"]) for x in case["expected_selected"]]
        expected_output = None
        for seed in range(20):
            candidates = base_candidates[:]
            random.Random(seed).shuffle(candidates)
            output, error = resolve_candidates(candidates, case["requested_profiles"], case["core_contracts"])
            self.assertIsNone(error)
            self.assertEqual(expected, [(x["profile_type"], x["profile_id"], x["profile_version"]) for x in output])
            normalized = json.dumps(output, sort_keys=True, separators=(",", ":"))
            expected_output = normalized if expected_output is None else expected_output
            self.assertEqual(expected_output, normalized)
        target = next(x for x in output if x["profile_id"] == "fixture.version-target")
        deps = [x for x in target["selection_provenance"] if x["relation"] == "requires"]
        self.assertEqual({">=1.5.0 <3.0.0", ">=2.0.0 <2.5.0"}, {x["required_version"] for x in deps})
        self.assertEqual({"fixture.version-org", "fixture.version-root"}, {x["introduced_by"]["profile_id"] for x in deps})
        root = next(x for x in output if x["profile_id"] == "fixture.version-root")
        self.assertEqual([{"relation": "requested", "required_version": "1.0.0"}], root["selection_provenance"])

    def test_dependency_provenance_in_effective_fixture_matches_manifest_edges_losslessly(self):
        eps = load_json(ROOT / "profiles/fixtures/valid/effective-profile-set.json")
        selected = {(p["profile_type"], p["profile_id"], p["profile_version"]): p for p in eps["effective_profiles"]}
        manifests = {}
        for path in (ROOT / "profiles/fixtures/valid").glob("*.profile.json"):
            m = load_json(path)
            manifests[keyver_of(m)] = m
        requests = {key_of(r): r for r in eps["requested_profiles"]}
        for profile in eps["effective_profiles"]:
            target_key = key_of(profile)
            for src in profile["selection_provenance"]:
                if src["relation"] == "requested":
                    self.assertEqual(requests[target_key]["version"], src["required_version"])
                    continue
                intro = src["introduced_by"]
                intro_keyver = keyver_of(intro)
                self.assertIn(intro_keyver, manifests)
                self.assertEqual(selected[intro_keyver]["manifest_sha256"], intro["manifest_sha256"])
                self.assertTrue(any(key_of(e) == target_key and e["version"] == src["required_version"] for e in manifests[intro_keyver].get(src["relation"], [])))

    def test_constraint_composition_is_input_order_independent_and_serialized(self):
        paths = [ROOT / "profiles/fixtures/valid" / name for name in ["research-base.profile.json", "research-strict.profile.json", "organization.profile.json", "narrative.profile.json", "publication.profile.json"]]
        base = [load_candidate(p) for p in paths]
        expected = None
        for seed in range(20):
            items = base[:]
            random.Random(seed).shuffle(items)
            composed = canonical_compose_constraints(items)
            normalized = json.dumps(composed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            expected = normalized if expected is None else expected
            self.assertEqual(expected, normalized)
        self.assertEqual(sorted(c["path"] for c in composed), [c["path"] for c in composed])
        union = next(c for c in composed if c["path"] == "evidence.capture.required_fields")
        self.assertEqual(["captured_hash", "locator", "source_id"], union["value"])
        self.assertEqual(sorted(union["provenance"], key=canonical_constraint_source_key), union["provenance"])


if __name__ == "__main__":
    unittest.main()
