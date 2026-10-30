"""Build the opt-in MISCO 1.3.0 Writer resources; --check verifies bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "profiles/narrative/misco/1.2.0"
TARGET = ROOT / "profiles/narrative/misco/1.3.0"
GUIDE = "docs/architecture/misco-recommendation-writing.md"
RULE_IDS = ("PUB-RC-01", "PUB-RC-02", "PUB-RC-04", "PUB-RC-05")


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def build() -> dict[Path, bytes]:
    guide = (ROOT / GUIDE).read_text(encoding="utf-8")
    rules = json.loads((BASE / "resources/writer-clean-rules.json").read_text(encoding="utf-8"))
    rules["asset_version"] = "1.3.0"
    rules["authority"] = (
        "Inherited approved rules plus user-requested recommendation writing refinement; see per-rule sources"
    )
    for rule in rules["items"]:
        if rule["id"] not in RULE_IDS:
            continue
        body = guide.split(f"## {rule['id']}\n\n", 1)[1].split("\n## ", 1)[0].rstrip()
        rule["body"] = body
        rule["adoption"] = "clarified_in_1.3.0"
        rule["approval"] += (
            "; recommendation writing refinement requested by user on 2026-10-31, not original Clean Source Pack authority"
        )
        rule.setdefault("additional_sources", []).append(
            {"path": GUIDE, "locator": f"## {rule['id']}"}
        )
    sources = json.loads(
        (BASE / "resources/writer-clean-source-documents.json").read_text(encoding="utf-8")
    )
    sources["asset_version"] = "1.3.0"
    sources["authority"] = rules["authority"]
    raw = guide.encode()
    sources["source_documents"].append(
        {
            "path": GUIDE,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
            "content": guide,
            "writer_rule_ids": list(RULE_IDS),
            "authority": "User-requested editorial refinement; papers are examples, not research Evidence or original Clean Source Pack authority",
        }
    )
    sources["document_count"] = len(sources["source_documents"])
    outputs = {
        TARGET / "resources/writer-clean-rules.json": encoded(rules),
        TARGET / "resources/writer-clean-source-documents.json": encoded(sources),
    }
    manifest = json.loads((BASE / "profile.json").read_text(encoding="utf-8"))
    manifest["profile_version"] = "1.3.0"
    manifest["description"] = (
        "MISCO Writer with concrete, evidence-preserving recommendation writing guidance derived from six supplied past papers."
    )
    for resource in manifest["resources"]:
        resource["sha256"] = hashlib.sha256(outputs[TARGET / resource["path"]]).hexdigest()
    outputs[TARGET / "profile.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, content in build().items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit(
                    f"Stale {path.relative_to(ROOT)}; rerun this script without --check"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


if __name__ == "__main__":
    main()
