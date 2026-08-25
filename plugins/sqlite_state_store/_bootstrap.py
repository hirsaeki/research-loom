from __future__ import annotations

from typing import TYPE_CHECKING

from core.runtime.ports import AtomicCommitError
from core.runtime.transition_models import StateView

from ._support import bootstrap_write, encode_json, object_key

if TYPE_CHECKING:
    from .adapter import SQLiteResearchStateRepository


class BootstrapMixin:
    @bootstrap_write
    def initialize_from_validated_state_view(
        self: "SQLiteResearchStateRepository",
        seed: StateView,
    ) -> None:
        """Bootstrap an empty DB from an already validated PR20 StateView."""

        with self._write_transaction():
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM project_state"
            ).fetchone()
            if row is None or int(row["n"]) != 0:
                raise AtomicCommitError(
                    "SQLite bootstrap requires an empty Research State store"
                )

            self._connection.execute(
                """
                INSERT INTO project_state(
                    project_ref, project_config_ref, project_config_digest,
                    project_config_json, effective_profile_set_ref,
                    effective_profile_set_digest, effective_constraints_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed.project_ref,
                    seed.project_config_ref,
                    seed.project_config_digest,
                    encode_json(seed.project_config),
                    seed.effective_profile_set_ref,
                    seed.effective_profile_set_digest,
                    encode_json(seed.effective_constraints),
                ),
            )

            seen: set[tuple[str, str, int]] = set()
            for obj in seed.objects:
                key = object_key(obj)
                if key not in seen:
                    self._insert_immutable_object(obj, created_commit_id=None)
                    seen.add(key)

            current_key = object_key(seed.current_snapshot)
            if current_key not in seen:
                self._insert_immutable_object(
                    seed.current_snapshot,
                    created_commit_id=None,
                )
                seen.add(current_key)

            snapshots = [
                obj for obj in seed.objects
                if str(obj.get("kind")) == "snapshot"
            ]
            if not any(
                str(obj.get("id")) == str(seed.current_snapshot["id"])
                for obj in snapshots
            ):
                snapshots.append(seed.current_snapshot)
            for snapshot in sorted(
                snapshots,
                key=lambda obj: (str(obj["id"]), int(obj.get("revision", 0))),
            ):
                self._insert_snapshot_index(
                    snapshot,
                    created_commit_id=None,
                )

            for decision in sorted(seed.decisions, key=lambda item: str(item["id"])):
                key = object_key(decision)
                if key not in seen:
                    self._insert_immutable_object(
                        decision,
                        created_commit_id=None,
                    )
                    seen.add(key)
                self._insert_decision_index(
                    decision,
                    created_commit_id=None,
                )

            for lineage in sorted(seed.lineages, key=lambda item: item.lineage_id):
                self._insert_new_lineage(
                    seed.project_ref,
                    lineage,
                    created_commit_id=None,
                    updated_commit_id=None,
                )

            if not any(
                item.lineage_id == seed.active_lineage_ref
                for item in seed.lineages
            ):
                raise AtomicCommitError(
                    "bootstrap active lineage does not resolve"
                )
            self._connection.execute(
                """
                INSERT INTO project_active_lineage(
                    project_ref, active_lineage_ref, updated_commit_id
                ) VALUES (?, ?, NULL)
                """,
                (seed.project_ref, seed.active_lineage_ref),
            )

            for decision_ref in sorted(set(seed.used_decision_ids)):
                self._connection.execute(
                    """
                    INSERT INTO used_decisions(
                        decision_ref, consuming_transition_id, consuming_commit_id
                    ) VALUES (?, NULL, NULL)
                    """,
                    (decision_ref,),
                )
            for ref in sorted(set(seed.adoption_refs)):
                self._connection.execute(
                    """
                    INSERT INTO adoption_refs(
                        adoption_ref, project_ref, lineage_ref, created_commit_id
                    ) VALUES (?, ?, ?, NULL)
                    """,
                    (ref, seed.project_ref, seed.lineage_ref),
                )
            for ref in sorted(set(seed.non_reusable_refs)):
                self._connection.execute(
                    "INSERT INTO non_reusable_refs(ref, project_ref) VALUES (?, ?)",
                    (ref, seed.project_ref),
                )
            for ref, mode in sorted(seed.source_modes.items()):
                self._connection.execute(
                    """
                    INSERT INTO source_modes(source_ref, project_ref, source_mode)
                    VALUES (?, ?, ?)
                    """,
                    (str(ref), seed.project_ref, str(mode)),
                )
