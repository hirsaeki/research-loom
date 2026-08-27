from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import rfc8785

from plugins.local_application import LocalWorkspace, LocalWorkspaceError
from plugins.local_conversation_store import LocalConversationStore, LocalConversationStoreError


ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG = ROOT / "projects/fixtures/valid/generic-project-config.json"
EFFECTIVE_PROFILES = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


def bootstrap_config(path: Path) -> Path:
    config = json.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    payload = deepcopy(config)
    payload.pop("configuration_digest", None)
    config["configuration_digest"] = "sha256:" + hashlib.sha256(
        rfc8785.dumps(payload)
    ).hexdigest()
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class PR27ConversationStoreSchemaTests(unittest.TestCase):
    def test_missing_documents_payload_column_fails_closed_before_activation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = bootstrap_config(root / "project.json")
            workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config, EFFECTIVE_PROFILES)
            opened.close()

            conversation = workspace / ".research-loom/conversation.db"
            connection = sqlite3.connect(conversation)
            try:
                connection.execute("ALTER TABLE documents RENAME TO documents_valid")
                connection.execute(
                    """
                    CREATE TABLE documents(
                      message_type TEXT NOT NULL,
                      document_id TEXT NOT NULL,
                      digest TEXT NOT NULL,
                      PRIMARY KEY(message_type, document_id)
                    )
                    """
                )
                connection.execute("DROP TABLE documents_valid")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(LocalConversationStoreError) as direct:
                LocalConversationStore(conversation)
            self.assertEqual(direct.exception.code, "CONVERSATION-STORE-SCHEMA-001")
            self.assertIn("documents", direct.exception.message)
            self.assertIn("payload_json", direct.exception.message)

            with self.assertRaises(LocalWorkspaceError) as reopened:
                LocalWorkspace.open(workspace)
            self.assertEqual(reopened.exception.code, "WORKSPACE-CONVERSATION-DB-001")

            doctor = LocalWorkspace.doctor(workspace)
            self.assertEqual(doctor["status"], "ERROR")
            self.assertEqual(doctor["issues"][0]["code"], "WORKSPACE-CONVERSATION-DB-001")
            self.assertIn("documents", doctor["issues"][0]["message"])
            self.assertIn("payload_json", doctor["issues"][0]["message"])


if __name__ == "__main__":
    unittest.main()
