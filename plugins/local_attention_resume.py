from __future__ import annotations

import json
import sqlite3
from typing import Mapping

from plugins.local_attention_store import (
    LocalAttentionStoreError,
    attention_event_digest,
    validate_attention_map,
)


def _validated_activation_event(row, *, project_id: str, map_id: str, map_digest: str):
    try:
        event = json.loads(str(row["document_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-INTEGRITY-001", "stored Attention activation is not valid JSON"
        ) from exc
    if not isinstance(event, dict):
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-INTEGRITY-001", "stored Attention activation must be an object"
        )
    if (
        str(event.get("activation_id") or "") != str(row["activation_id"])
        or str(event.get("project_id") or "") != str(project_id)
        or str(event.get("map_id") or "") != str(map_id)
        or str(event.get("map_digest") or "") != str(map_digest)
        or str(event.get("event_digest") or "") != str(row["event_digest"])
        or str(row["project_id"]) != str(project_id)
        or str(row["map_id"]) != str(map_id)
        or str(row["map_digest"]) != str(map_digest)
        or attention_event_digest(event) != str(row["event_digest"])
    ):
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-INTEGRITY-001", "stored Attention activation binding or digest is invalid"
        )
    return event


def _activation_ids_for_map(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    map_id: str,
    map_digest: str,
    limit: int,
):
    if limit <= 0:
        raise ValueError("Attention activation query limit must be positive")
    event_rows = connection.execute(
        "SELECT activation_id,project_id,map_id,map_digest,event_digest,document_json "
        "FROM attention_activation_events WHERE project_id=? AND map_id=? "
        "ORDER BY rowid DESC LIMIT ?",
        (str(project_id), str(map_id), int(limit) + 1),
    ).fetchall()
    events = [
        _validated_activation_event(
            event_row,
            project_id=str(project_id),
            map_id=str(map_id),
            map_digest=str(map_digest),
        )
        for event_row in event_rows
    ]
    selected = events[:limit]
    return tuple(str(event["activation_id"]) for event in reversed(selected)), len(events) > limit


def validate_active_attention_binding(store, project_id: str, active: Mapping[str, object]) -> str:
    """Validate the active pointer against its persisted activation event."""
    activation_id = active.get("activation_id")
    map_id = active.get("map_id")
    map_digest = active.get("map_digest")
    if (
        not isinstance(activation_id, str)
        or not activation_id
        or not isinstance(map_id, str)
        or not map_id
        or not isinstance(map_digest, str)
        or not map_digest
    ):
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-INTEGRITY-001", "active Attention activation binding is malformed"
        )
    try:
        connection = store._connect_read()
    except LocalAttentionStoreError:
        raise
    except sqlite3.Error as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-DB-001", "Attention store is unreadable"
        ) from exc
    if connection is None:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-INTEGRITY-001", "active Attention activation does not resolve"
        )
    try:
        row = connection.execute(
            "SELECT activation_id,project_id,map_id,map_digest,event_digest,document_json "
            "FROM attention_activation_events WHERE activation_id=?",
            (activation_id,),
        ).fetchone()
        if row is None:
            raise LocalAttentionStoreError(
                "ATTENTION-STORE-INTEGRITY-001", "active Attention activation does not resolve"
            )
        event = _validated_activation_event(
            row,
            project_id=str(project_id),
            map_id=map_id,
            map_digest=map_digest,
        )
        return str(event["activation_id"])
    except LocalAttentionStoreError:
        raise
    except sqlite3.Error as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-DB-001", "active Attention activation is unreadable"
        ) from exc
    finally:
        connection.close()


def attention_maps_for_project(
    store,
    project_id: str,
    *,
    limit: int,
    activation_limit: int = 100,
):
    """Return bounded stored Attention Maps with objective activation references."""
    if limit <= 0:
        raise ValueError("Attention Map query limit must be positive")
    if activation_limit <= 0:
        raise ValueError("Attention activation query limit must be positive")
    try:
        connection = store._connect_read()
    except LocalAttentionStoreError:
        raise
    except sqlite3.Error as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-DB-001", "Attention store is unreadable"
        ) from exc
    if connection is None:
        return ()
    try:
        rows = connection.execute(
            "SELECT map_id,project_id,map_digest,document_json FROM attention_maps "
            "WHERE project_id=? ORDER BY rowid DESC LIMIT ?",
            (str(project_id), int(limit)),
        ).fetchall()
        result = []
        for row in rows:
            try:
                document = json.loads(str(row["document_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LocalAttentionStoreError(
                    "ATTENTION-STORE-INTEGRITY-001", "stored Attention Map is not valid JSON"
                ) from exc
            if not isinstance(document, dict):
                raise LocalAttentionStoreError(
                    "ATTENTION-STORE-INTEGRITY-001", "stored Attention Map must be an object"
                )
            validate_attention_map(document)
            if (
                str(document.get("map_id") or "") != str(row["map_id"])
                or str(document.get("project_id") or "") != str(project_id)
                or str(document.get("map_digest") or "") != str(row["map_digest"])
            ):
                raise LocalAttentionStoreError(
                    "ATTENTION-STORE-INTEGRITY-001", "stored Attention Map row binding is invalid"
                )
            activation_ids, activations_truncated = _activation_ids_for_map(
                connection,
                project_id=str(project_id),
                map_id=str(row["map_id"]),
                map_digest=str(row["map_digest"]),
                limit=int(activation_limit),
            )
            result.append({
                "map": document,
                "activation_ids": activation_ids,
                "activation_ids_truncated": activations_truncated,
            })
        return tuple(result)
    except LocalAttentionStoreError:
        raise
    except sqlite3.Error as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-DB-001", "Attention Map listing is unreadable"
        ) from exc
    finally:
        connection.close()
