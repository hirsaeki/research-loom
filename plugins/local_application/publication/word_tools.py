"""Materialize pinned, inert Word support files from a verified public preview."""

import hashlib
import re
from pathlib import Path

from plugins.application_errors import LocalApplicationError


def export_word_tools(preview: dict, output: Path) -> list[dict]:
    bundle = preview["build"]["publication_policy"].get("word_tools")
    if not bundle or bundle.get("schema_version") != "1.0.0":
        raise LocalApplicationError("PUBLICATION-WORD-TOOLS-001", "No supported pinned Word tools")
    prepared = {}
    for row in bundle["files"]:
        name = row["filename"]
        payload = row["content"].encode("utf-8")
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\.(bas|ps1|md)", name)
            or name.casefold() in {key.casefold() for key in prepared}
            or hashlib.sha256(payload).hexdigest() != row["sha256"]
        ):
            raise LocalApplicationError(
                "PUBLICATION-WORD-TOOLS-001", "Invalid support-file pin or name"
            )
        prepared[name] = payload
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in prepared.items():
        (output / name).write_bytes(payload)
    return [
        {"path": str(output / name), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in prepared.items()
    ]
