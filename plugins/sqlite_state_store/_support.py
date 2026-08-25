from __future__ import annotations

import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping

from core.runtime.ports import AtomicCommitError, RepositoryError
from core.runtime.transition_models import (
    Actor,
    CommitReceipt,
    LineageView,
    canonical_digest,
    canonical_json,
)

MIGRATION_DIR = Path(__file__).with_name("migrations")
_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql$")


def repository_read(method):
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RepositoryError:
            raise
        except sqlite3.Error as exc:
            raise RepositoryError(f"SQLite read failed in {method.__name__}") from exc
    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped


def bootstrap_write(method):
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (RepositoryError, AtomicCommitError):
            raise
        except sqlite3.Error as exc:
            raise AtomicCommitError("SQLite bootstrap failed atomically") from exc
    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped


def object_key(obj: Mapping[str, Any]) -> tuple[str, str, int]:
    return str(obj["kind"]), str(obj["id"]), int(obj.get("revision", 0))


def optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def lineage_from_row(row: Mapping[str, Any]) -> LineageView:
    return LineageView(
        lineage_id=str(row["lineage_id"]),
        lineage_kind=str(row["lineage_kind"]),
        head_snapshot_ref=str(row["head_snapshot_ref"]),
        head_snapshot_digest=str(row["head_snapshot_digest"]),
        head_snapshot_revision=int(row["head_snapshot_revision"]),
        execution_mode=str(row["execution_mode"]),
        status=str(row["status"]),
        parent_lineage_ref=optional_text(row["parent_lineage_ref"]),
        baseline_snapshot_ref=optional_text(row["baseline_snapshot_ref"]),
        project_config_ref=optional_text(row["project_config_ref"]),
        project_config_digest=optional_text(row["project_config_digest"]),
        effective_profile_set_ref=optional_text(row["effective_profile_set_ref"]),
        effective_profile_set_digest=optional_text(row["effective_profile_set_digest"]),
    )


def encode_json(value: Any) -> str:
    _assert_finite_json(value)
    return canonical_json(value)


def decode_json(payload_json: str) -> Any:
    try:
        value = json.loads(payload_json, parse_constant=_reject_non_finite)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RepositoryError("stored canonical JSON is invalid") from exc
    _assert_finite_json(value)
    if canonical_json(value) != payload_json:
        raise RepositoryError("stored canonical JSON is not in deterministic form")
    return value


def decode_payload_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = decode_json(str(row["payload_json"]))
    if not isinstance(payload, Mapping):
        raise RepositoryError("stored canonical object payload is not a JSON object")
    if canonical_digest(payload) != str(row["payload_digest"]):
        raise RepositoryError("stored canonical payload digest mismatch")
    expected_content = str(payload.get("content_digest") or row["payload_digest"])
    if expected_content != str(row["content_digest"]):
        raise RepositoryError("stored object content digest index mismatch")
    return payload


def verify_embedded_content_digest(payload: Mapping[str, Any]) -> None:
    stored = payload.get("content_digest")
    if not isinstance(stored, str) or not stored:
        raise RepositoryError("Snapshot content_digest is missing")
    basis = dict(payload)
    basis.pop("content_digest", None)
    if canonical_digest(basis) != stored:
        raise RepositoryError("Snapshot content_digest does not match canonical payload")


def receipt_from_json(payload_json: str) -> CommitReceipt:
    try:
        payload = decode_json(payload_json)
        actor = payload["actor"]
        return CommitReceipt(
            transition_id=str(payload["transition_id"]),
            commit_id=str(payload["commit_id"]),
            prior_snapshot_ref=str(payload["prior_snapshot_ref"]),
            prior_snapshot_digest=str(payload["prior_snapshot_digest"]),
            new_snapshot_ref=optional_text(payload.get("new_snapshot_ref")),
            new_snapshot_digest=optional_text(payload.get("new_snapshot_digest")),
            lineage_ref=str(payload["lineage_ref"]),
            applied_typed_actions=tuple(str(x) for x in payload["applied_typed_actions"]),
            resolving_decision_refs=tuple(str(x) for x in payload["resolving_decision_refs"]),
            bundle_digest=str(payload["bundle_digest"]),
            timestamp=str(payload["timestamp"]),
            actor=Actor(str(actor["actor_id"]), str(actor["actor_type"])),
            idempotency_key=str(payload["idempotency_key"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RepositoryError("stored CommitReceipt is invalid") from exc


def load_migrations(directory: Path | None = None) -> list[tuple[int, str, str]]:
    directory = directory or MIGRATION_DIR
    if not directory.is_dir():
        raise RepositoryError(f"SQLite migration directory is missing: {directory}")
    result: list[tuple[int, str, str]] = []
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if match is None:
            raise RepositoryError(f"invalid SQLite migration filename: {path.name}")
        result.append(
            (int(match.group("version")), match.group("name"), path.read_text(encoding="utf-8"))
        )
    actual = [item[0] for item in result]
    expected = list(range(1, len(result) + 1))
    if actual != expected:
        raise RepositoryError(f"SQLite migrations must be contiguous from 0001: found {actual}")
    return result


def split_sql_statements(sql: str) -> Iterable[str]:
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise RepositoryError("incomplete SQLite migration statement")


def rollback_quietly(connection: sqlite3.Connection) -> None:
    try:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def debug_active_lineage(connection: sqlite3.Connection) -> Any:
    rows = [
        (str(row["project_ref"]), str(row["active_lineage_ref"]))
        for row in connection.execute(
            "SELECT project_ref, active_lineage_ref "
            "FROM project_active_lineage ORDER BY project_ref"
        )
    ]
    return rows[0][1] if len(rows) == 1 else rows


def _assert_finite_json(value: Any) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RepositoryError("canonical JSON forbids NaN and Infinity")
    elif isinstance(value, Mapping):
        for item in value.values():
            _assert_finite_json(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_finite_json(item)


def _reject_non_finite(token: str) -> None:
    raise ValueError(f"non-finite JSON token {token!r}")
