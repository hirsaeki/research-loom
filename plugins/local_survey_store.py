from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

import rfc8785


SURVEY_STORE_SCHEMA_VERSION = "0.1.0"


class LocalSurveyStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_document_digest(document: Mapping[str, Any], field: str) -> str:
    payload = {key: deepcopy(value) for key, value in document.items() if key != field}
    try:
        encoded = rfc8785.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise LocalSurveyStoreError(
            "SURVEY-DIGEST-001", "Survey document is not canonicalizable"
        ) from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def registry_digest(document: Mapping[str, Any]) -> str:
    return canonical_document_digest(document, "registry_digest")


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", f"Survey {field} is invalid"
        )
    return value


def _validate_snapshot_binding(value: Any) -> None:
    expected = {"lineage_ref", "snapshot_ref", "snapshot_digest"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "Survey snapshot binding is invalid"
        )
    for field in expected:
        _nonempty_string(value.get(field), f"snapshot binding {field}")


def _validate_common(document: Mapping[str, Any]) -> None:
    for field in (
        "schema_version",
        "project_id",
        "project_config_digest",
        "effective_profile_set_digest",
        "captured_at",
        "capture_origin",
        "registry_digest",
    ):
        _nonempty_string(document.get(field), field)
    if document["schema_version"] != "0.1.0":
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "Survey registry document version is incompatible"
        )
    rq_ids = document.get("rq_ids")
    if (
        not isinstance(rq_ids, list)
        or not rq_ids
        or any(not isinstance(item, str) or not item for item in rq_ids)
        or len(rq_ids) != len(set(rq_ids))
    ):
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "Survey RQ bindings are invalid"
        )
    _validate_snapshot_binding(document.get("captured_against"))
    if document["registry_digest"] != registry_digest(document):
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "Survey registry digest does not match content"
        )


def validate_design_record(document: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "project_id",
        "rq_ids",
        "captured_against",
        "project_config_digest",
        "effective_profile_set_digest",
        "captured_at",
        "capture_origin",
        "design",
        "registry_digest",
    }
    if not isinstance(document, Mapping) or set(document) != expected:
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Survey Design record shape is invalid"
        )
    _validate_common(document)
    design = document.get("design")
    if not isinstance(design, Mapping):
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Survey Design is invalid"
        )
    for field in ("survey_design_id", "version", "content_digest"):
        _nonempty_string(design.get(field), f"Survey Design {field}")
    if design["content_digest"] != canonical_document_digest(design, "content_digest"):
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Survey Design digest does not match content"
        )


def validate_instrument_record(document: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "project_id",
        "rq_ids",
        "captured_against",
        "project_config_digest",
        "effective_profile_set_digest",
        "captured_at",
        "capture_origin",
        "title",
        "description",
        "design_ref",
        "questionnaire",
        "registry_digest",
    }
    if not isinstance(document, Mapping) or set(document) != expected:
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Survey Instrument record shape is invalid"
        )
    _validate_common(document)
    _nonempty_string(document.get("title"), "Survey Instrument title")
    if not isinstance(document.get("description"), str):
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Survey Instrument description is invalid"
        )
    design_ref = document.get("design_ref")
    if not isinstance(design_ref, Mapping) or set(design_ref) != {
        "survey_design_id", "version", "content_digest"
    }:
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Survey Instrument Design binding is invalid"
        )
    for field in ("survey_design_id", "version", "content_digest"):
        _nonempty_string(design_ref.get(field), f"Survey Instrument Design binding {field}")
    questionnaire = document.get("questionnaire")
    if not isinstance(questionnaire, Mapping):
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Questionnaire is invalid"
        )
    for field in ("questionnaire_id", "version", "content_digest"):
        _nonempty_string(questionnaire.get(field), f"Questionnaire {field}")
    if questionnaire["content_digest"] != canonical_document_digest(
        questionnaire, "content_digest"
    ):
        raise LocalSurveyStoreError(
            "SURVEY-STORE-INTEGRITY-001", "stored Questionnaire digest does not match content"
        )


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS survey_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS survey_designs (
    project_id TEXT NOT NULL,
    survey_design_id TEXT NOT NULL,
    version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, survey_design_id, version)
);
CREATE TABLE IF NOT EXISTS survey_instruments (
    project_id TEXT NOT NULL,
    questionnaire_id TEXT NOT NULL,
    version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, questionnaire_id, version)
);
"""


class LocalSurveyStore:
    """Small immutable registry for canonical Survey Design and Questionnaire revisions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> None:
        try:
            row = connection.execute("SELECT schema_version FROM survey_store_meta").fetchone()
        except sqlite3.Error as exc:
            raise LocalSurveyStoreError(
                "SURVEY-STORE-SCHEMA-001", "Survey registry schema is missing or incompatible"
            ) from exc
        if row is None or str(row[0]) != SURVEY_STORE_SCHEMA_VERSION:
            raise LocalSurveyStoreError(
                "SURVEY-STORE-SCHEMA-001", "Survey registry schema version is incompatible"
            )

    def _read(self) -> sqlite3.Connection | None:
        if not self.exists:
            return None
        try:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            self._schema_version(connection)
            return connection
        except LocalSurveyStoreError:
            if "connection" in locals():
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.close()
            raise LocalSurveyStoreError(
                "SURVEY-STORE-DB-001", "Survey registry is unreadable"
            ) from exc

    def _write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.executescript(_SCHEMA_SQL)
            connection.execute(
                "INSERT OR IGNORE INTO survey_store_meta(schema_version) VALUES (?)",
                (SURVEY_STORE_SCHEMA_VERSION,),
            )
            self._schema_version(connection)
            connection.commit()
            return connection
        except LocalSurveyStoreError:
            if "connection" in locals():
                connection.rollback()
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.rollback()
                connection.close()
            raise LocalSurveyStoreError(
                "SURVEY-STORE-DB-001", "Survey registry could not be initialized"
            ) from exc

    @staticmethod
    def _encoded(document: Mapping[str, Any]) -> str:
        return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode_and_validate(
        row: sqlite3.Row,
        *,
        validator,
        payload_field: str,
        payload_id_field: str,
        id_column: str,
    ) -> Mapping[str, Any]:
        try:
            value = json.loads(str(row["document_json"]))
        except json.JSONDecodeError as exc:
            raise LocalSurveyStoreError(
                "SURVEY-STORE-INTEGRITY-001", "stored Survey registry document is invalid JSON"
            ) from exc
        validator(value)
        payload = value[payload_field]
        if (
            str(value["project_id"]) != str(row["project_id"])
            or str(payload[payload_id_field]) != str(row[id_column])
            or str(payload["version"]) != str(row["version"])
            or str(payload["content_digest"]) != str(row["content_digest"])
            or str(value["captured_at"]) != str(row["captured_at"])
        ):
            raise LocalSurveyStoreError(
                "SURVEY-STORE-INTEGRITY-001",
                "stored Survey registry row metadata does not match its document",
            )
        return deepcopy(value)

    def _capture(
        self,
        *,
        table: str,
        id_column: str,
        payload_field: str,
        payload_id_field: str,
        identity: str,
        project_id: str,
        version: str,
        content_digest: str,
        captured_at: str,
        document: Mapping[str, Any],
        validator,
    ) -> bool:
        validator(document)
        connection = self._write()
        try:
            existing = connection.execute(
                f"SELECT project_id,{id_column},version,content_digest,captured_at,document_json "
                f"FROM {table} WHERE project_id=? AND {id_column}=? AND version=?",
                (project_id, identity, version),
            ).fetchone()
            if existing is not None:
                stored = self._decode_and_validate(
                    existing,
                    validator=validator,
                    payload_field=payload_field,
                    payload_id_field=payload_id_field,
                    id_column=id_column,
                )
                comparable_stored = deepcopy(dict(stored))
                comparable_new = deepcopy(dict(document))
                for item in (comparable_stored, comparable_new):
                    item.pop("captured_at", None)
                    item.pop("registry_digest", None)
                if comparable_stored == comparable_new:
                    return False
                raise LocalSurveyStoreError(
                    "SURVEY-IMMUTABLE-001",
                    f"Survey revision already exists with different content: {identity}@{version}",
                )
            connection.execute(
                f"INSERT INTO {table}(project_id,{id_column},version,content_digest,captured_at,document_json) VALUES (?,?,?,?,?,?)",
                (project_id, identity, version, content_digest, captured_at, self._encoded(document)),
            )
            connection.commit()
            return True
        except LocalSurveyStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise LocalSurveyStoreError(
                "SURVEY-STORE-DB-001", "Survey registry write failed"
            ) from exc
        finally:
            connection.close()

    def capture_design(self, document: Mapping[str, Any]) -> bool:
        design = document["design"]
        return self._capture(
            table="survey_designs",
            id_column="survey_design_id",
            payload_field="design",
            payload_id_field="survey_design_id",
            identity=str(design["survey_design_id"]),
            project_id=str(document["project_id"]),
            version=str(design["version"]),
            content_digest=str(design["content_digest"]),
            captured_at=str(document["captured_at"]),
            document=document,
            validator=validate_design_record,
        )

    def capture_instrument(self, document: Mapping[str, Any]) -> bool:
        questionnaire = document["questionnaire"]
        return self._capture(
            table="survey_instruments",
            id_column="questionnaire_id",
            payload_field="questionnaire",
            payload_id_field="questionnaire_id",
            identity=str(questionnaire["questionnaire_id"]),
            project_id=str(document["project_id"]),
            version=str(questionnaire["version"]),
            content_digest=str(questionnaire["content_digest"]),
            captured_at=str(document["captured_at"]),
            document=document,
            validator=validate_instrument_record,
        )

    def _load(
        self,
        *,
        table: str,
        id_column: str,
        payload_field: str,
        payload_id_field: str,
        project_id: str,
        identity: str,
        version: str,
        validator,
    ):
        connection = self._read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                f"SELECT project_id,{id_column},version,content_digest,captured_at,document_json "
                f"FROM {table} WHERE project_id=? AND {id_column}=? AND version=?",
                (project_id, identity, version),
            ).fetchone()
            if row is None:
                return None
            return self._decode_and_validate(
                row,
                validator=validator,
                payload_field=payload_field,
                payload_id_field=payload_id_field,
                id_column=id_column,
            )
        except sqlite3.Error as exc:
            raise LocalSurveyStoreError(
                "SURVEY-STORE-DB-001", "Survey registry read failed"
            ) from exc
        finally:
            connection.close()

    def load_design(self, project_id: str, survey_design_id: str, version: str):
        return self._load(
            table="survey_designs",
            id_column="survey_design_id",
            payload_field="design",
            payload_id_field="survey_design_id",
            project_id=project_id,
            identity=survey_design_id,
            version=version,
            validator=validate_design_record,
        )

    def load_instrument(self, project_id: str, questionnaire_id: str, version: str):
        return self._load(
            table="survey_instruments",
            id_column="questionnaire_id",
            payload_field="questionnaire",
            payload_id_field="questionnaire_id",
            project_id=project_id,
            identity=questionnaire_id,
            version=version,
            validator=validate_instrument_record,
        )
