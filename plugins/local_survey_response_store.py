from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from plugins.survey_response.contracts import (
    canonical_digest,
    validate_canonical_response,
    validate_dataset,
)


SURVEY_RESPONSE_STORE_SCHEMA_VERSION = "0.1.0"
_REQUIRED_COLUMNS = {
    "survey_response_store_meta": {"schema_version"},
    "survey_responses": {
        "project_id", "response_id", "identity_namespace", "instrument_id",
        "instrument_version", "content_digest", "response_origin",
        "validation_status", "ingested_at", "document_json", "raw_input_json",
    },
    "survey_response_datasets": {
        "project_id", "dataset_id", "instrument_id", "instrument_version",
        "content_digest", "response_origin", "created_at", "summary_digest",
        "summary_json", "document_json",
    },
    "survey_response_dataset_entries": {
        "project_id", "dataset_id", "entry_index", "kind", "payload_json",
    },
    "survey_response_dataset_entry_counts": {
        "project_id", "dataset_id", "entry_count", "accepted_count",
    },
}


class LocalSurveyResponseStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS survey_response_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS survey_responses (
    project_id TEXT NOT NULL,
    response_id TEXT NOT NULL,
    identity_namespace TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    response_origin TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    raw_input_json TEXT NOT NULL,
    PRIMARY KEY(project_id, identity_namespace, response_id)
);
CREATE TABLE IF NOT EXISTS survey_response_datasets (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    response_origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary_digest TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, dataset_id)
);
CREATE TABLE IF NOT EXISTS survey_response_dataset_entries (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    entry_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(project_id, dataset_id, entry_index)
);
CREATE TABLE IF NOT EXISTS survey_response_dataset_entry_counts (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    entry_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(project_id, dataset_id)
);
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_init
AFTER INSERT ON survey_response_datasets
BEGIN
    INSERT OR IGNORE INTO survey_response_dataset_entry_counts(
        project_id,dataset_id,entry_count,accepted_count
    ) VALUES (NEW.project_id,NEW.dataset_id,0,0);
END;
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_insert
AFTER INSERT ON survey_response_dataset_entries
BEGIN
    INSERT INTO survey_response_dataset_entry_counts(
        project_id,dataset_id,entry_count,accepted_count
    ) VALUES (
        NEW.project_id,
        NEW.dataset_id,
        1,
        CASE WHEN NEW.kind='accepted_response' THEN 1 ELSE 0 END
    )
    ON CONFLICT(project_id,dataset_id) DO UPDATE SET
        entry_count=entry_count+1,
        accepted_count=accepted_count+
            CASE WHEN NEW.kind='accepted_response' THEN 1 ELSE 0 END;
END;
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_delete
AFTER DELETE ON survey_response_dataset_entries
BEGIN
    UPDATE survey_response_dataset_entry_counts
    SET entry_count=entry_count-1,
        accepted_count=accepted_count-
            CASE WHEN OLD.kind='accepted_response' THEN 1 ELSE 0 END
    WHERE project_id=OLD.project_id AND dataset_id=OLD.dataset_id;
END;
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_kind_update
AFTER UPDATE OF kind ON survey_response_dataset_entries
BEGIN
    UPDATE survey_response_dataset_entry_counts
    SET accepted_count=accepted_count
        - CASE WHEN OLD.kind='accepted_response' THEN 1 ELSE 0 END
        + CASE WHEN NEW.kind='accepted_response' THEN 1 ELSE 0 END
    WHERE project_id=NEW.project_id AND dataset_id=NEW.dataset_id;
END;
CREATE INDEX IF NOT EXISTS survey_response_dataset_entries_page
ON survey_response_dataset_entries(project_id, dataset_id, entry_index);
"""


class LocalSurveyResponseStore:
    """Immutable local registry for canonical Survey responses and datasets."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @staticmethod
    def _encoded(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> None:
        try:
            rows = connection.execute(
                "SELECT schema_version FROM survey_response_store_meta"
            ).fetchall()
            if (
                len(rows) != 1
                or str(rows[0][0]) != SURVEY_RESPONSE_STORE_SCHEMA_VERSION
            ):
                raise LocalSurveyResponseStoreError(
                    "SURVEY-RESPONSE-STORE-SCHEMA-001",
                    "Survey response registry schema version is incompatible",
                )
            for table_name, required in _REQUIRED_COLUMNS.items():
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        f"PRAGMA table_info({table_name})"
                    ).fetchall()
                }
                if not required <= columns:
                    raise LocalSurveyResponseStoreError(
                        "SURVEY-RESPONSE-STORE-SCHEMA-001",
                        f"Survey response registry table is incompatible: {table_name}",
                    )
        except LocalSurveyResponseStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-SCHEMA-001",
                "Survey response registry schema is missing or incompatible",
            ) from exc

    def _read(self) -> sqlite3.Connection | None:
        if not self.exists:
            return None
        try:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            self._schema_version(connection)
            return connection
        except LocalSurveyResponseStoreError:
            if "connection" in locals():
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.close()
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry is unreadable",
            ) from exc

    def _write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.executescript(_SCHEMA_SQL)
            rows = connection.execute(
                "SELECT schema_version FROM survey_response_store_meta"
            ).fetchall()
            if not rows:
                connection.execute(
                    "INSERT OR IGNORE INTO survey_response_store_meta(schema_version) VALUES (?)",
                    (SURVEY_RESPONSE_STORE_SCHEMA_VERSION,),
                )
            self._schema_version(connection)
            connection.commit()
            return connection
        except LocalSurveyResponseStoreError:
            if "connection" in locals():
                connection.rollback()
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.rollback()
                connection.close()
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry could not be initialized",
            ) from exc

    @staticmethod
    def _dataset_summary(document: Mapping[str, Any]) -> dict[str, Any]:
        summary = deepcopy(dict(document))
        for field in (
            "accepted_response_refs",
            "rejected_response_refs",
            "rejected_inputs",
        ):
            summary.pop(field, None)
        return summary

    @staticmethod
    def _dataset_entries(document: Mapping[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for ref in document["accepted_response_refs"]:
            entries.append({
                "kind": "accepted_response",
                "response_ref": deepcopy(ref),
            })

        rejected_by_ref = {
            (
                str(item["canonical_response_ref"]["identity_namespace"]),
                str(item["canonical_response_ref"]["response_id"]),
            ): item
            for item in document["rejected_inputs"]
            if item.get("canonical_response_ref")
        }
        for ref in document["rejected_response_refs"]:
            key = (str(ref["identity_namespace"]), str(ref["response_id"]))
            rejected = rejected_by_ref.get(key)
            if rejected is None:
                raise ValueError(
                    "SurveyResponseDataset rejected response lacks rejected-input provenance"
                )
            entries.append({
                "kind": "rejected_response",
                "response_ref": deepcopy(ref),
                "issues": deepcopy(rejected["issues"]),
            })

        for rejected in document["rejected_inputs"]:
            if rejected.get("canonical_response_ref"):
                continue
            entries.append({
                "kind": "rejected_raw_input",
                "raw_input_digest": str(rejected["raw_input_digest"]),
                "raw_input": deepcopy(rejected["raw_input"]),
                "issues": deepcopy(rejected["issues"]),
            })

        entries.sort(
            key=lambda item: (
                str(item["kind"]),
                str((item.get("response_ref") or {}).get("identity_namespace", "")),
                str((item.get("response_ref") or {}).get("response_id", "")),
                str((item.get("response_ref") or {}).get("content_digest", "")),
                str(item.get("raw_input_digest", "")),
                canonical_digest(item),
            )
        )
        if len(entries) != int(document["response_count"]):
            raise ValueError("SurveyResponseDataset entry projection is inconsistent")
        return entries

    @staticmethod
    def _decode_response(row: sqlite3.Row) -> dict[str, Any]:
        try:
            document = json.loads(str(row["document_json"]))
            raw_input = json.loads(str(row["raw_input_json"]))
            validate_canonical_response(document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                "stored SurveyResponse is invalid",
            ) from exc
        instrument = document["instrument_ref"]
        if (
            str(document["project_id"]) != str(row["project_id"])
            or str(document["response_id"]) != str(row["response_id"])
            or str(document["identity_namespace"]) != str(row["identity_namespace"])
            or str(instrument["id"]) != str(row["instrument_id"])
            or str(instrument["version"]) != str(row["instrument_version"])
            or str(document["content_digest"]) != str(row["content_digest"])
            or str(document["response_origin"]) != str(row["response_origin"])
            or str(document["validation"]["status"]) != str(row["validation_status"])
            or str(document["ingested_at"]) != str(row["ingested_at"])
        ):
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                "stored SurveyResponse row metadata does not match its document",
            )
        return {"response": deepcopy(document), "raw_input": deepcopy(raw_input)}

    @staticmethod
    def _validate_dataset_row(document: Mapping[str, Any], row: sqlite3.Row) -> None:
        instrument = document["instrument_ref"]
        if (
            str(document["project_id"]) != str(row["project_id"])
            or str(document["dataset_id"]) != str(row["dataset_id"])
            or str(instrument["id"]) != str(row["instrument_id"])
            or str(instrument["version"]) != str(row["instrument_version"])
            or str(document["content_digest"]) != str(row["content_digest"])
            or str(document["response_origin"]) != str(row["response_origin"])
            or str(document["created_at"]) != str(row["created_at"])
        ):
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                "stored SurveyResponseDataset row metadata does not match its document",
            )

    @classmethod
    def _decode_dataset(cls, row: sqlite3.Row) -> dict[str, Any]:
        try:
            document = json.loads(str(row["document_json"]))
            validate_dataset(document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                "stored SurveyResponseDataset is invalid",
            ) from exc
        cls._validate_dataset_row(document, row)
        return deepcopy(document)

    @classmethod
    def _decode_dataset_summary(cls, row: sqlite3.Row) -> dict[str, Any]:
        try:
            summary = json.loads(str(row["summary_json"]))
            if canonical_digest(summary) != str(row["summary_digest"]):
                raise ValueError("summary digest mismatch")
        except (json.JSONDecodeError, ValueError) as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                "stored SurveyResponseDataset summary is invalid",
            ) from exc
        cls._validate_dataset_row(summary, row)
        return deepcopy(summary)

    def capture_dataset(
        self,
        dataset: Mapping[str, Any],
        responses: Sequence[tuple[Mapping[str, Any], Any]],
    ) -> bool:
        try:
            validate_dataset(dataset)
            entries = self._dataset_entries(dataset)
            summary = self._dataset_summary(dataset)
            summary_digest = canonical_digest(summary)
            response_by_id: dict[tuple[str, str], Mapping[str, Any]] = {}
            for response, _raw in responses:
                validate_canonical_response(response)
                response_id = str(response["response_id"])
                response_key = (str(response["identity_namespace"]), response_id)
                if response_key in response_by_id:
                    raise ValueError("SurveyResponseDataset persistence input contains duplicate response identity")
                response_by_id[response_key] = response
                if (
                    response["instrument_ref"] != dataset["instrument_ref"]
                    or response["response_origin"] != dataset["response_origin"]
                    or response["epistemic_status"] != dataset["epistemic_status"]
                ):
                    raise ValueError("SurveyResponseDataset contains mixed Instrument/origin/epistemic response content")
            for field, expected_status in (
                ("accepted_response_refs", "accepted"),
                ("rejected_response_refs", "rejected"),
            ):
                for ref in dataset[field]:
                    response = response_by_id.get(
                        (str(ref["identity_namespace"]), str(ref["response_id"]))
                    )
                    if (
                        response is None
                        or response["content_digest"] != ref["content_digest"]
                        or response["validation"]["status"] != expected_status
                    ):
                        raise ValueError(f"SurveyResponseDataset {field} does not resolve exactly")
        except ValueError as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                str(exc),
            ) from exc

        connection = self._write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            prior_dataset = connection.execute(
                "SELECT * FROM survey_response_datasets WHERE project_id=? AND dataset_id=?",
                (str(dataset["project_id"]), str(dataset["dataset_id"])),
            ).fetchone()
            if prior_dataset is not None:
                stored_dataset = self._decode_dataset(prior_dataset)
                if (
                    stored_dataset["content_digest"] == dataset["content_digest"]
                    and stored_dataset["registry_digest"] == dataset["registry_digest"]
                ):
                    connection.rollback()
                    return False
                raise LocalSurveyResponseStoreError(
                    "SURVEY-RESPONSE-DATASET-IMMUTABLE-001",
                    "SurveyResponseDataset identity is single-use",
                )

            for response, raw_input in responses:
                response_id = str(response["response_id"])
                identity_namespace = str(response["identity_namespace"])
                existing = connection.execute(
                    "SELECT * FROM survey_responses WHERE project_id=? AND identity_namespace=? AND response_id=?",
                    (str(response["project_id"]), identity_namespace, response_id),
                ).fetchone()
                if existing is not None:
                    stored = self._decode_response(existing)
                    if (
                        stored["response"]["content_digest"] == response["content_digest"]
                        and stored["response"]["raw_input_digest"] == response["raw_input_digest"]
                    ):
                        continue
                    raise LocalSurveyResponseStoreError(
                        "SURVEY_RESPONSE_DUPLICATE_RECORD",
                        f"immutable Survey response_id already exists with different content: {response_id}",
                    )
                instrument = response["instrument_ref"]
                connection.execute(
                    """
                    INSERT INTO survey_responses(
                        project_id,response_id,identity_namespace,instrument_id,instrument_version,
                        content_digest,response_origin,validation_status,ingested_at,
                        document_json,raw_input_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(response["project_id"]),
                        response_id,
                        identity_namespace,
                        str(instrument["id"]),
                        str(instrument["version"]),
                        str(response["content_digest"]),
                        str(response["response_origin"]),
                        str(response["validation"]["status"]),
                        str(response["ingested_at"]),
                        self._encoded(response),
                        self._encoded(raw_input),
                    ),
                )

            instrument = dataset["instrument_ref"]
            connection.execute(
                """
                INSERT INTO survey_response_datasets(
                    project_id,dataset_id,instrument_id,instrument_version,
                    content_digest,response_origin,created_at,summary_digest,
                    summary_json,document_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(dataset["project_id"]),
                    str(dataset["dataset_id"]),
                    str(instrument["id"]),
                    str(instrument["version"]),
                    str(dataset["content_digest"]),
                    str(dataset["response_origin"]),
                    str(dataset["created_at"]),
                    summary_digest,
                    self._encoded(summary),
                    self._encoded(dataset),
                ),
            )
            for index, entry in enumerate(entries):
                connection.execute(
                    """
                    INSERT INTO survey_response_dataset_entries(
                        project_id,dataset_id,entry_index,kind,payload_json
                    ) VALUES (?,?,?,?,?)
                    """,
                    (
                        str(dataset["project_id"]),
                        str(dataset["dataset_id"]),
                        index,
                        str(entry["kind"]),
                        self._encoded(entry),
                    ),
                )
            connection.commit()
            return True
        except LocalSurveyResponseStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry write failed",
            ) from exc
        finally:
            connection.close()

    def load_response(
        self,
        project_id: str,
        response_id: str,
        *,
        identity_namespace: str | None = None,
    ) -> dict[str, Any] | None:
        connection = self._read()
        if connection is None:
            return None
        try:
            if identity_namespace is None:
                rows = connection.execute(
                    "SELECT * FROM survey_responses WHERE project_id=? AND response_id=? ORDER BY identity_namespace",
                    (project_id, response_id),
                ).fetchall()
                if len(rows) > 1:
                    raise LocalSurveyResponseStoreError(
                        "SURVEY-RESPONSE-AMBIGUOUS-001",
                        "response_id exists in multiple identity namespaces; identity_namespace is required",
                    )
                row = rows[0] if rows else None
            else:
                row = connection.execute(
                    "SELECT * FROM survey_responses WHERE project_id=? AND identity_namespace=? AND response_id=?",
                    (project_id, identity_namespace, response_id),
                ).fetchone()
            return None if row is None else self._decode_response(row)
        except LocalSurveyResponseStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry read failed",
            ) from exc
        finally:
            connection.close()

    def load_responses(
        self,
        project_id: str,
        response_keys: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        keys = list(dict.fromkeys((str(namespace), str(response_id)) for namespace, response_id in response_keys))
        if not keys:
            return {}
        connection = self._read()
        if connection is None:
            return {}
        try:
            loaded: dict[tuple[str, str], dict[str, Any]] = {}
            # Keep well below SQLite's common 999-parameter limit while reusing one connection.
            chunk_size = 400
            for start in range(0, len(keys), chunk_size):
                chunk = keys[start:start + chunk_size]
                pairs = ",".join("(?,?)" for _ in chunk)
                parameters: list[str] = [project_id]
                for identity_namespace, response_id in chunk:
                    parameters.extend((identity_namespace, response_id))
                rows = connection.execute(
                    f"""
                    SELECT * FROM survey_responses
                    WHERE project_id=?
                      AND (identity_namespace,response_id) IN ({pairs})
                    """,
                    parameters,
                ).fetchall()
                for row in rows:
                    key = (str(row["identity_namespace"]), str(row["response_id"]))
                    loaded[key] = self._decode_response(row)
            return loaded
        except LocalSurveyResponseStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry read failed",
            ) from exc
        finally:
            connection.close()

    def find_datasets_by_source_run(self, project_id: str, run_id: str) -> list[dict[str, Any]]:
        connection = self._read()
        if connection is None:
            return []
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT d.*
                FROM survey_response_datasets AS d
                JOIN json_each(d.document_json, '$.source_run_ids') AS source_run
                WHERE d.project_id=? AND source_run.value=?
                ORDER BY d.created_at, d.dataset_id
                """,
                (project_id, run_id),
            ).fetchall()
            return [self._decode_dataset(row) for row in rows]
        except LocalSurveyResponseStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry source-Run lookup failed",
            ) from exc
        finally:
            connection.close()

    def load_dataset(self, project_id: str, dataset_id: str) -> dict[str, Any] | None:
        connection = self._read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                "SELECT * FROM survey_response_datasets WHERE project_id=? AND dataset_id=?",
                (project_id, dataset_id),
            ).fetchone()
            return None if row is None else self._decode_dataset(row)
        except LocalSurveyResponseStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry read failed",
            ) from exc
        finally:
            connection.close()

    def load_dataset_entries(
        self,
        project_id: str,
        dataset_id: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, Any] | None:
        connection = self._read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                "SELECT * FROM survey_response_datasets WHERE project_id=? AND dataset_id=?",
                (project_id, dataset_id),
            ).fetchone()
            if row is None:
                return None
            summary = self._decode_dataset_summary(row)
            total = int(summary["response_count"])
            counts = connection.execute(
                """
                SELECT entry_count,accepted_count
                FROM survey_response_dataset_entry_counts
                WHERE project_id=? AND dataset_id=?
                """,
                (project_id, dataset_id),
            ).fetchone()
            if (
                counts is None
                or int(counts["entry_count"]) != total
                or int(counts["accepted_count"]) != int(summary["accepted_count"])
                or int(counts["entry_count"]) - int(counts["accepted_count"])
                != int(summary["rejected_count"])
            ):
                raise LocalSurveyResponseStoreError(
                    "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                    "stored SurveyResponseDataset entry index is inconsistent",
                )
            expected = min(limit, max(total - offset, 0))
            rows = connection.execute(
                """
                SELECT entry_index,kind,payload_json
                FROM survey_response_dataset_entries
                WHERE project_id=? AND dataset_id=? AND entry_index>=?
                ORDER BY entry_index
                LIMIT ?
                """,
                (project_id, dataset_id, offset, limit),
            ).fetchall()
            if len(rows) != expected:
                raise LocalSurveyResponseStoreError(
                    "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                    "stored SurveyResponseDataset entry index is inconsistent",
                )
            entries: list[dict[str, Any]] = []
            for position, entry_row in enumerate(rows):
                if int(entry_row["entry_index"]) != offset + position:
                    raise LocalSurveyResponseStoreError(
                        "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                        "stored SurveyResponseDataset entry index is inconsistent",
                    )
                try:
                    entry = json.loads(str(entry_row["payload_json"]))
                except json.JSONDecodeError as exc:
                    raise LocalSurveyResponseStoreError(
                        "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                        "stored SurveyResponseDataset entry is invalid",
                    ) from exc
                if (
                    not isinstance(entry, Mapping)
                    or str(entry.get("kind")) != str(entry_row["kind"])
                ):
                    raise LocalSurveyResponseStoreError(
                        "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                        "stored SurveyResponseDataset entry metadata is inconsistent",
                    )
                entries.append(deepcopy(dict(entry)))
            return {
                "dataset": summary,
                "entries": entries,
                "total": total,
            }
        except LocalSurveyResponseStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry bounded read failed",
            ) from exc
        finally:
            connection.close()
