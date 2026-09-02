from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from plugins.survey_analysis import validate_aggregate_result, validate_analysis_spec

SURVEY_ANALYSIS_STORE_SCHEMA_VERSION = "0.1.0"
_REQUIRED_COLUMNS = {
    "survey_analysis_store_meta": {"schema_version"},
    "survey_analysis_specs": {
        "project_id", "analysis_spec_id", "content_digest", "dataset_id",
        "dataset_digest", "instrument_id", "instrument_version", "instrument_digest",
        "created_at", "document_json",
    },
    "survey_aggregate_results": {
        "project_id", "aggregate_result_id", "content_digest", "analysis_spec_id",
        "analysis_spec_digest", "dataset_id", "dataset_digest", "instrument_id",
        "instrument_version", "instrument_digest", "response_origin", "epistemic_status",
        "generated_at", "document_json",
    },
}


class LocalSurveyAnalysisStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS survey_analysis_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS survey_analysis_specs (
    project_id TEXT NOT NULL,
    analysis_spec_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_digest TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    instrument_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, analysis_spec_id)
);
CREATE TABLE IF NOT EXISTS survey_aggregate_results (
    project_id TEXT NOT NULL,
    aggregate_result_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    analysis_spec_id TEXT NOT NULL,
    analysis_spec_digest TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_digest TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    instrument_digest TEXT NOT NULL,
    response_origin TEXT NOT NULL,
    epistemic_status TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, aggregate_result_id)
);
CREATE INDEX IF NOT EXISTS survey_aggregate_results_by_spec
ON survey_aggregate_results(project_id, analysis_spec_id, dataset_id);
"""


class LocalSurveyAnalysisStore:
    """Immutable local registry for Survey analysis specifications and aggregate results."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @staticmethod
    def _encoded(value: Mapping[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> None:
        try:
            rows = connection.execute(
                "SELECT schema_version FROM survey_analysis_store_meta"
            ).fetchall()
            if len(rows) != 1 or str(rows[0][0]) != SURVEY_ANALYSIS_STORE_SCHEMA_VERSION:
                raise LocalSurveyAnalysisStoreError(
                    "SURVEY-ANALYSIS-STORE-SCHEMA-001",
                    "Survey analysis registry schema version is incompatible",
                )
            for table_name, required in _REQUIRED_COLUMNS.items():
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        f"PRAGMA table_info({table_name})"
                    ).fetchall()
                }
                if not required <= columns:
                    raise LocalSurveyAnalysisStoreError(
                        "SURVEY-ANALYSIS-STORE-SCHEMA-001",
                        f"Survey analysis registry table is incompatible: {table_name}",
                    )
        except LocalSurveyAnalysisStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-SCHEMA-001",
                "Survey analysis registry schema is missing or incompatible",
            ) from exc

    def _read(self) -> sqlite3.Connection | None:
        if not self.exists:
            return None
        try:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            self._schema_version(connection)
            return connection
        except LocalSurveyAnalysisStoreError:
            if "connection" in locals():
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.close()
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-DB-001",
                "Survey analysis registry is unreadable",
            ) from exc

    def _write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.executescript(_SCHEMA_SQL)
            rows = connection.execute(
                "SELECT schema_version FROM survey_analysis_store_meta"
            ).fetchall()
            if not rows:
                connection.execute(
                    "INSERT OR IGNORE INTO survey_analysis_store_meta(schema_version) VALUES (?)",
                    (SURVEY_ANALYSIS_STORE_SCHEMA_VERSION,),
                )
            self._schema_version(connection)
            connection.commit()
            return connection
        except LocalSurveyAnalysisStoreError:
            if "connection" in locals():
                connection.rollback()
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.rollback()
                connection.close()
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-DB-001",
                "Survey analysis registry could not be initialized",
            ) from exc

    @staticmethod
    def _decode_spec(row: sqlite3.Row) -> dict[str, Any]:
        try:
            document = json.loads(str(row["document_json"]))
            validate_analysis_spec(document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-INTEGRITY-001",
                "stored SurveyAnalysisSpec is invalid",
            ) from exc
        dataset = document["dataset_ref"]
        instrument = document["instrument_ref"]
        if (
            str(document["project_id"]) != str(row["project_id"])
            or str(document["analysis_spec_id"]) != str(row["analysis_spec_id"])
            or str(document["content_digest"]) != str(row["content_digest"])
            or str(dataset["id"]) != str(row["dataset_id"])
            or str(dataset["content_digest"]) != str(row["dataset_digest"])
            or str(instrument["id"]) != str(row["instrument_id"])
            or str(instrument["version"]) != str(row["instrument_version"])
            or str(instrument["content_digest"]) != str(row["instrument_digest"])
            or str(document["created_at"]) != str(row["created_at"])
        ):
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-INTEGRITY-001",
                "stored SurveyAnalysisSpec row metadata does not match its document",
            )
        return deepcopy(document)

    @staticmethod
    def _decode_result(row: sqlite3.Row) -> dict[str, Any]:
        try:
            document = json.loads(str(row["document_json"]))
            validate_aggregate_result(document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-INTEGRITY-001",
                "stored SurveyAggregateResult is invalid",
            ) from exc
        spec = document["analysis_spec_ref"]
        dataset = document["dataset_ref"]
        instrument = document["instrument_ref"]
        if (
            str(document["project_id"]) != str(row["project_id"])
            or str(document["aggregate_result_id"]) != str(row["aggregate_result_id"])
            or str(document["content_digest"]) != str(row["content_digest"])
            or str(spec["id"]) != str(row["analysis_spec_id"])
            or str(spec["content_digest"]) != str(row["analysis_spec_digest"])
            or str(dataset["id"]) != str(row["dataset_id"])
            or str(dataset["content_digest"]) != str(row["dataset_digest"])
            or str(instrument["id"]) != str(row["instrument_id"])
            or str(instrument["version"]) != str(row["instrument_version"])
            or str(instrument["content_digest"]) != str(row["instrument_digest"])
            or str(document["response_origin"]) != str(row["response_origin"])
            or str(document["epistemic_status"]) != str(row["epistemic_status"])
            or str(document["generated_at"]) != str(row["generated_at"])
        ):
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-INTEGRITY-001",
                "stored SurveyAggregateResult row metadata does not match its document",
            )
        return deepcopy(document)

    def capture_spec(self, document: Mapping[str, Any]) -> bool:
        try:
            validate_analysis_spec(document)
        except ValueError as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-INTEGRITY-001", str(exc)
            ) from exc
        connection = self._write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT * FROM survey_analysis_specs WHERE project_id=? AND analysis_spec_id=?",
                (str(document["project_id"]), str(document["analysis_spec_id"])),
            ).fetchone()
            if prior is not None:
                stored = self._decode_spec(prior)
                if stored["content_digest"] == document["content_digest"]:
                    connection.rollback()
                    return False
                raise LocalSurveyAnalysisStoreError(
                    "SURVEY-ANALYSIS-SPEC-IMMUTABLE-001",
                    "SurveyAnalysisSpec identity is single-use",
                )
            dataset = document["dataset_ref"]
            instrument = document["instrument_ref"]
            connection.execute(
                """
                INSERT INTO survey_analysis_specs(
                    project_id,analysis_spec_id,content_digest,dataset_id,dataset_digest,
                    instrument_id,instrument_version,instrument_digest,created_at,document_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(document["project_id"]),
                    str(document["analysis_spec_id"]),
                    str(document["content_digest"]),
                    str(dataset["id"]),
                    str(dataset["content_digest"]),
                    str(instrument["id"]),
                    str(instrument["version"]),
                    str(instrument["content_digest"]),
                    str(document["created_at"]),
                    self._encoded(document),
                ),
            )
            connection.commit()
            return True
        except LocalSurveyAnalysisStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-DB-001",
                "Survey analysis specification write failed",
            ) from exc
        finally:
            connection.close()

    def capture_result(self, document: Mapping[str, Any]) -> bool:
        try:
            validate_aggregate_result(document)
        except ValueError as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-INTEGRITY-001", str(exc)
            ) from exc
        connection = self._write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT * FROM survey_aggregate_results WHERE project_id=? AND aggregate_result_id=?",
                (str(document["project_id"]), str(document["aggregate_result_id"])),
            ).fetchone()
            if prior is not None:
                stored = self._decode_result(prior)
                if stored["content_digest"] == document["content_digest"]:
                    connection.rollback()
                    return False
                raise LocalSurveyAnalysisStoreError(
                    "SURVEY-AGGREGATE-RESULT-IMMUTABLE-001",
                    "SurveyAggregateResult identity is single-use",
                )
            spec = document["analysis_spec_ref"]
            dataset = document["dataset_ref"]
            instrument = document["instrument_ref"]
            connection.execute(
                """
                INSERT INTO survey_aggregate_results(
                    project_id,aggregate_result_id,content_digest,analysis_spec_id,
                    analysis_spec_digest,dataset_id,dataset_digest,instrument_id,
                    instrument_version,instrument_digest,response_origin,epistemic_status,
                    generated_at,document_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(document["project_id"]),
                    str(document["aggregate_result_id"]),
                    str(document["content_digest"]),
                    str(spec["id"]),
                    str(spec["content_digest"]),
                    str(dataset["id"]),
                    str(dataset["content_digest"]),
                    str(instrument["id"]),
                    str(instrument["version"]),
                    str(instrument["content_digest"]),
                    str(document["response_origin"]),
                    str(document["epistemic_status"]),
                    str(document["generated_at"]),
                    self._encoded(document),
                ),
            )
            connection.commit()
            return True
        except LocalSurveyAnalysisStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-DB-001",
                "Survey aggregate result write failed",
            ) from exc
        finally:
            connection.close()

    def load_spec(self, project_id: str, analysis_spec_id: str) -> dict[str, Any] | None:
        connection = self._read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                "SELECT * FROM survey_analysis_specs WHERE project_id=? AND analysis_spec_id=?",
                (project_id, analysis_spec_id),
            ).fetchone()
            return None if row is None else self._decode_spec(row)
        except LocalSurveyAnalysisStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-DB-001",
                "Survey analysis specification read failed",
            ) from exc
        finally:
            connection.close()


    def find_results_by_dataset(self, project_id: str, dataset_id: str) -> list[dict[str, Any]]:
        connection = self._read()
        if connection is None:
            return []
        try:
            rows = connection.execute(
                "SELECT * FROM survey_aggregate_results WHERE project_id=? AND dataset_id=? ORDER BY generated_at,aggregate_result_id",
                (project_id, dataset_id),
            ).fetchall()
            return [self._decode_result(row) for row in rows]
        except LocalSurveyAnalysisStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-DB-001",
                "Survey analysis registry read failed",
            ) from exc
        finally:
            connection.close()

    def load_result(self, project_id: str, aggregate_result_id: str) -> dict[str, Any] | None:
        connection = self._read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                "SELECT * FROM survey_aggregate_results WHERE project_id=? AND aggregate_result_id=?",
                (project_id, aggregate_result_id),
            ).fetchone()
            return None if row is None else self._decode_result(row)
        except LocalSurveyAnalysisStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalSurveyAnalysisStoreError(
                "SURVEY-ANALYSIS-STORE-DB-001",
                "Survey aggregate result read failed",
            ) from exc
        finally:
            connection.close()
