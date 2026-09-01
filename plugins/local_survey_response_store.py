from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from plugins.survey_response.contracts import validate_canonical_response, validate_dataset


SURVEY_RESPONSE_STORE_SCHEMA_VERSION = "0.1.0"


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
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, dataset_id)
);
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
            row = connection.execute("SELECT schema_version FROM survey_response_store_meta").fetchone()
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-SCHEMA-001",
                "Survey response registry schema is missing or incompatible",
            ) from exc
        if row is None or str(row[0]) != SURVEY_RESPONSE_STORE_SCHEMA_VERSION:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-SCHEMA-001",
                "Survey response registry schema version is incompatible",
            )

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
        existed = self.exists
        try:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            if existed:
                self._schema_version(connection)
            else:
                connection.executescript(_SCHEMA_SQL)
                connection.execute(
                    "INSERT INTO survey_response_store_meta(schema_version) VALUES (?)",
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
    def _decode_dataset(row: sqlite3.Row) -> dict[str, Any]:
        try:
            document = json.loads(str(row["document_json"]))
            validate_dataset(document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                "stored SurveyResponseDataset is invalid",
            ) from exc
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
        return deepcopy(document)

    def capture_dataset(
        self,
        dataset: Mapping[str, Any],
        responses: Sequence[tuple[Mapping[str, Any], Any]],
    ) -> bool:
        try:
            validate_dataset(dataset)
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
                    content_digest,response_origin,created_at,document_json
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    str(dataset["project_id"]),
                    str(dataset["dataset_id"]),
                    str(instrument["id"]),
                    str(instrument["version"]),
                    str(dataset["content_digest"]),
                    str(dataset["response_origin"]),
                    str(dataset["created_at"]),
                    self._encoded(dataset),
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
        except sqlite3.Error as exc:
            raise LocalSurveyResponseStoreError(
                "SURVEY-RESPONSE-STORE-DB-001",
                "Survey response registry read failed",
            ) from exc
        finally:
            connection.close()
