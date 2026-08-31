from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from core.runtime.ports import RepositoryError, StaleHeadError

from ._support import rollback_quietly


@contextmanager
def guard_research_state_head(
    repository,
    project_ref: str,
    *,
    lineage_ref: str,
    snapshot_ref: str,
    snapshot_digest: str,
) -> Iterator[None]:
    """Hold the SQLite writer boundary while an external registry binds to one HEAD."""
    connection = getattr(repository, "_connection", None)
    if connection is None:
        raise RepositoryError("Research State repository does not expose the local SQLite guard")
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute(
            "SELECT active_lineage_ref FROM project_active_lineage WHERE project_ref=?",
            (str(project_ref),),
        ).fetchone()
        if active is None or str(active["active_lineage_ref"]) != str(lineage_ref):
            raise StaleHeadError("active Research Lineage changed before guarded operation")
        head = connection.execute(
            """
            SELECT project_ref, head_snapshot_ref, head_snapshot_digest
            FROM lineages WHERE lineage_id=?
            """,
            (str(lineage_ref),),
        ).fetchone()
        if (
            head is None
            or str(head["project_ref"]) != str(project_ref)
            or str(head["head_snapshot_ref"]) != str(snapshot_ref)
            or str(head["head_snapshot_digest"]) != str(snapshot_digest)
        ):
            raise StaleHeadError("Research Lineage HEAD changed before guarded operation")
        yield
        connection.execute("COMMIT")
    except Exception:
        rollback_quietly(connection)
        raise
