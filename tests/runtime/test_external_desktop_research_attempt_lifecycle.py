from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from plugins.local_application import LocalApplicationError
from test_external_desktop_research_intake import ExternalDesktopResearchIntakeTests


def test_collect_rejects_in_progress_attempt_and_leaves_run_open_for_completion():
    helper = ExternalDesktopResearchIntakeTests(methodName="runTest")
    with tempfile.TemporaryDirectory() as temp:
        app, facade = helper.make_facade(Path(temp))
        try:
            run_id = helper.prepare(facade)["run_id"]
            facade.start_external_retrieval_attempt(run_id, {
                "attempt_id": "ATT-IN-PROGRESS",
                "strategy": "support search",
                "coverage_dimension_ids": ["COV-SUPPORT"],
            })

            with pytest.raises(LocalApplicationError) as blocked:
                facade.collect_external(run_id, {"handoff": {"invalid": True}, "extension": {}})
            assert blocked.value.code == "APPLICATION-EXTERNAL-ATTEMPT-001"
            assert "ATT-IN-PROGRESS" in str(blocked.value)
            assert app.execution_store.load_run(run_id).status.value == "RUNNING"

            completed = facade.complete_external_retrieval_attempt(run_id, {
                "attempt_id": "ATT-IN-PROGRESS",
                "outcome": "no_relevant_source",
            })
            assert completed["attempt"]["outcome"] == "no_relevant_source"
        finally:
            facade.close()
