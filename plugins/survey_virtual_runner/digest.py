from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any, Mapping

from core.conversation.validation import canonical_digest


def with_digest(document: Mapping[str, Any], field: str = "extension_digest") -> dict[str, Any]:
    result = deepcopy(dict(document))
    result.pop(field, None)
    result[field] = canonical_digest(result)
    return result


def file_digest(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
