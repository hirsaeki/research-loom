from __future__ import annotations

import json
import sqlite3

from plugins.local_attention_store import (
    LocalAttentionStoreError,
    attention_event_digest,
    validate_attention_map,
)


def attention_maps_for_project(store, project_id: str, *, limit: int):
    """Return bounded stored Attention Maps with objective activation references."""
    if limit <= 0:
        raise ValueError("Attention Map query limit must be positive")
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
            event_rows = connection.execute(
                "SELECT activation_id,project_id,map_id,map_digest,event_digest,document_json "
                "FROM attention_activation_events WHERE project_id=? AND map_id=? ORDER BY rowid",
                (str(project_id), str(row["map_id"])),
            ).fetchall()
            activation_ids = []
            for event_row in event_rows:
                try:
                    event = json.loads(str(event_row["document_json"]))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise LocalAttentionStoreError(
                        "ATTENTION-STORE-INTEGRITY-001", "stored Attention activation is not valid JSON"
                    ) from exc
                if not isinstance(event, dict):
                    raise LocalAttentionStoreError(
                        "ATTENTION-STORE-INTEGRITY-001", "stored Attention activation must be an object"
                    )
                if (
                    str(event.get("activation_id") or "") != str(event_row["activation_id"])
                    or str(event.get("project_id") or "") != str(project_id)
                    or str(event.get("map_id") or "") != str(row["map_id"])
                    or str(event.get("map_digest") or "") != str(row["map_digest"])
                    or str(event.get("event_digest") or "") != str(event_row["event_digest"])
                    or attention_event_digest(event) != str(event_row["event_digest"])
                ):
                    raise LocalAttentionStoreError(
                        "ATTENTION-STORE-INTEGRITY-001", "stored Attention activation binding or digest is invalid"
                    )
                activation_ids.append(str(event["activation_id"]))
            result.append({"map": document, "activation_ids": tuple(activation_ids)})
        return tuple(result)
    except LocalAttentionStoreError:
        raise
    except sqlite3.Error as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-DB-001", "Attention Map listing is unreadable"
        ) from exc
    finally:
        connection.close()