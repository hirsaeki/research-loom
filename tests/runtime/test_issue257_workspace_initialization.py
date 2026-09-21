from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import queue
import threading
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalWorkspace
from plugins.local_application.workspace import LocalWorkspaceError, INTERNAL_DIR, BINDING_NAME, INITIALIZING_MARKER
from plugins.local_application.workspace_initialization import finish_initialization, initial_intent
import test_local_workspace_application_cli as support

ROOT = Path(__file__).resolve().parents[2]
CRASH = r'''
import os,sys
from pathlib import Path
from unittest.mock import patch
from plugins.local_application import workspace as w
stage,workspace,config,eps=sys.argv[1:]
write_json,copy_json,app,unlink=w._atomic_json_write,w._copy_json,w.LocalResearchApplication,Path.unlink
def after_json(path,value):
    write_json(path,value)
    if stage == 'live_binding' and Path(path).name == w.BINDING_NAME:
        print('READY',flush=True)
        sys.stdin.readline()
    if ((stage == 'intent' and Path(path).name == w.INITIALIZING_MARKER and value.get('phase') == 'PRE_STATE')
        or (stage == 'state_start' and Path(path).name == w.INITIALIZING_MARKER and value.get('phase') == 'STATE_STARTED')
        or (stage == 'binding' and Path(path).name == w.BINDING_NAME)):
        os._exit(77)
def after_copy(path,value):
    copy_json(path,value)
    if (stage == 'config' and Path(path).name == w.PROJECT_CONFIG_NAME) or (stage == 'profiles' and Path(path).name == w.EFFECTIVE_PROFILE_SET_NAME):
        os._exit(77)
def after_app(*args,**kwargs):
    result=app(*args,**kwargs)
    if stage == 'stores':
        os._exit(77)
    return result
def after_unlink(path,*args,**kwargs):
    result=unlink(path,*args,**kwargs)
    if stage == 'marker_removed' and path.name == w.INITIALIZING_MARKER:
        os._exit(77)
    return result
with patch.object(w,'_atomic_json_write',after_json), patch.object(w,'_copy_json',after_copy), patch.object(w,'LocalResearchApplication',after_app), patch.object(Path,'unlink',after_unlink):
    w.LocalWorkspace.init(workspace,config,eps).close()
'''


class Issue257InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config, self.eps = support.write_inputs(self.root)
        self.workspace = self.root / 'workspace'

    def _crash(self, stage):
        result = subprocess.run([sys.executable, '-c', CRASH, stage, str(self.workspace), str(self.config), str(self.eps)],
                                cwd=ROOT, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 77, result.stderr + result.stdout)

    @staticmethod
    def _bytes(root):
        # SQLite read-only opens may create/refresh SHM coordination and empty
        # WAL sidecars. Nonempty WAL holds real committed bytes and IS protected.
        return {str(p.relative_to(root)): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in root.rglob('*') if p.is_file() and not p.name.endswith('-shm')
                and not (p.name.endswith('-wal') and p.stat().st_size == 0)}

    def test_process_exit_boundaries_have_safe_read_only_classification(self):
        expected = {'intent': 'PRECOMMIT_STAGING', 'config': 'PRECOMMIT_STAGING', 'profiles': 'PRECOMMIT_STAGING',
                    'state_start': 'INDETERMINATE', 'stores': 'RESEARCH_RECORDS_PRESENT', 'binding': 'COMMITTED_WORKSPACE'}
        for stage, classification in expected.items():
            with self.subTest(stage=stage):
                self.workspace = self.root / stage
                self._crash(stage)
                before = self._bytes(self.workspace)
                first = LocalWorkspace.doctor(self.workspace)
                self.assertEqual(first['status'], 'ERROR')
                diagnosis = first['initialization']
                self.assertEqual(diagnosis['classification'], classification)
                self.assertFalse(diagnosis['cleanup_allowed'])
                self.assertEqual(diagnosis['live_process_status'], 'NOT_DETERMINED')
                self.assertTrue(diagnosis['next_action'])
                self.assertEqual(LocalWorkspace.doctor(self.workspace), first)
                self.assertEqual(self._bytes(self.workspace), before)
                with self.assertRaises(LocalWorkspaceError) as rejected:
                    LocalWorkspace.open(self.workspace)
                self.assertEqual(rejected.exception.code, 'WORKSPACE-PARTIAL-001')
                with self.assertRaises(LocalWorkspaceError):
                    LocalWorkspace.init(self.workspace, self.config, self.eps)
                self.assertEqual(self._bytes(self.workspace), before)

    def test_public_finalization_requires_full_integrity_and_exact_binding(self):
        self._crash('binding')
        internal = self.workspace / INTERNAL_DIR
        diagnosis = LocalWorkspace.doctor(self.workspace)['initialization']
        binding_digest = diagnosis['binding_digest']
        before = self._bytes(self.workspace)
        with self.assertRaises(LocalWorkspaceError):
            finish_initialization(self.workspace, 'sha256:' + '0' * 64)
        self.assertEqual(self._bytes(self.workspace), before)
        code, _, result = support.run_cli(['init-finish', '--workspace', str(self.workspace), '--expected-binding-digest', binding_digest, '--json'])
        self.assertEqual(code, 0, result)
        self.assertEqual(result['result'], 'FINISHED')
        after = self._bytes(self.workspace)
        before.pop(f'{INTERNAL_DIR}/{INITIALIZING_MARKER}')
        self.assertEqual(before, after)
        self.assertEqual(finish_initialization(self.workspace, binding_digest)['result'], 'VERIFIED_REUSE')
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'OK')
        with LocalWorkspace.open(self.workspace):
            pass

    def test_failed_finalization_is_retryable_and_never_removes_research(self):
        self._crash('binding')
        digest = LocalWorkspace.doctor(self.workspace)['initialization']['binding_digest']
        before = self._bytes(self.workspace)
        original = Path.unlink
        def fail_marker(path, *args, **kwargs):
            if path.name == INITIALIZING_MARKER:
                raise PermissionError('injected unlink failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_marker):
            with self.assertRaises(LocalWorkspaceError) as rejected:
                finish_initialization(self.workspace, digest)
        self.assertEqual(rejected.exception.code, 'WORKSPACE-INIT-FINISH-001')
        self.assertEqual(self._bytes(self.workspace), before)
        self.assertEqual(finish_initialization(self.workspace, digest)['result'], 'FINISHED')
        # Process death after marker unlink is just a normal committed Workspace.
        self.workspace = self.root / 'after-unlink'
        self._crash('marker_removed')
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'OK')

    def test_marker_alone_missing_marker_unknown_files_and_wrong_target_are_not_proof(self):
        self._crash('profiles')
        marker = self.workspace / INTERNAL_DIR / INITIALIZING_MARKER
        original = marker.read_bytes()
        marker.write_text('initializing\n')
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['initialization']['classification'], 'INDETERMINATE')
        marker.write_bytes(original)
        intent = json.loads(original)
        wrong = deepcopy(intent); wrong['root'] = 'different workspace'
        marker.write_text(json.dumps(wrong))
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['initialization']['classification'], 'INDETERMINATE')
        marker.write_bytes(original)
        user = self.workspace / 'operator-input.txt'; user.write_text('never delete user data')
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['initialization']['classification'], 'INDETERMINATE')
        user.unlink()  # test-owned fixture, not a recovery operation
        stray = marker.parent / 'unexpected.db'; stray.write_bytes(b'incomplete or unknown')
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['initialization']['classification'], 'INDETERMINATE')
        stray.unlink()
        before = self._bytes(self.workspace)
        with self.assertRaises(LocalWorkspaceError):
            finish_initialization(self.workspace, 'sha256:' + '0' * 64)
        self.assertEqual(self._bytes(self.workspace), before)
        # Ablation: removing the marker cannot make missing canonical stores valid.
        marker.unlink()
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'ERROR')
        with self.assertRaises(LocalWorkspaceError):
            LocalWorkspace.open(self.workspace)

    def test_precommit_operator_quarantine_preserves_old_tree_and_new_init_is_separate(self):
        self._crash('profiles')
        diagnosis = LocalWorkspace.doctor(self.workspace)['initialization']
        self.assertTrue(diagnosis['quarantine_after_quiescence'])
        before = self._bytes(self.workspace)
        # Explicit stopped-operator runbook, not an automatic repair/delete API.
        quarantine = self.root / 'retained-incomplete-workspace'
        self.workspace.rename(quarantine)
        self.assertEqual(self._bytes(quarantine), before)
        with LocalWorkspace.init(self.workspace, self.config, self.eps) as opened:
            new_binding = dict(opened.binding)
        self.assertEqual(self._bytes(quarantine), before)
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'OK')
        # Existing valid data/user input cannot be reinitialized, even with an intent.
        user = self.workspace / 'keep.txt'; user.write_text('preserve')
        intent = initial_intent(self.workspace, json.loads(self.config.read_text()), json.loads(self.eps.read_text()))
        (self.workspace / INTERNAL_DIR / INITIALIZING_MARKER).write_text(json.dumps(intent))
        diagnosis = LocalWorkspace.doctor(self.workspace)['initialization']
        self.assertEqual(diagnosis['classification'], 'COMMITTED_WORKSPACE')
        self.assertFalse(diagnosis['quarantine_after_quiescence'])
        with self.assertRaises(LocalWorkspaceError):
            LocalWorkspace.init(self.workspace, self.config, self.eps)
        self.assertEqual(user.read_text(), 'preserve')
        self.assertEqual(finish_initialization(self.workspace, canonical_digest(new_binding))['result'], 'FINISHED')

    def test_open_failure_after_commit_preserves_state_and_stopped_backup(self):
        with patch.object(LocalWorkspace, 'open', side_effect=OSError('injected reopen failure')):
            with self.assertRaises(OSError):
                LocalWorkspace.init(self.workspace, self.config, self.eps)
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'OK')
        backup = self.root / 'backup'
        shutil.copytree(self.workspace, backup)
        self.assertEqual(LocalWorkspace.doctor(backup)['status'], 'OK')
        with LocalWorkspace.open(backup) as opened:
            self.assertEqual(opened.binding, json.loads((self.workspace / INTERNAL_DIR / BINDING_NAME).read_text()))

    def test_live_initializer_cannot_be_finalized_by_another_process(self):
        process = subprocess.Popen([sys.executable, '-c', CRASH, 'live_binding', str(self.workspace), str(self.config), str(self.eps)],
                                   cwd=ROOT, text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        self.assertEqual(ready.get(timeout=15).strip(), 'READY')
        diagnosis = LocalWorkspace.doctor(self.workspace)['initialization']
        self.assertEqual(diagnosis['classification'], 'COMMITTED_WORKSPACE')
        with self.assertRaises(LocalWorkspaceError) as rejected:
            finish_initialization(self.workspace, diagnosis['binding_digest'])
        self.assertEqual(rejected.exception.code, 'WORKSPACE-LOCK-BUSY-001')
        self.assertTrue((self.workspace / INTERNAL_DIR / INITIALIZING_MARKER).exists())
        process.communicate(input='finish\n', timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'OK')

    def test_corrupt_committed_state_and_linked_marker_never_pass_finalization(self):
        self._crash('binding')
        digest = LocalWorkspace.doctor(self.workspace)['initialization']['binding_digest']
        database = self.workspace / INTERNAL_DIR / 'research-state.sqlite3'
        raw = database.read_bytes()
        database.write_bytes(b'broken')
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['initialization']['classification'], 'INDETERMINATE')
        with self.assertRaises(LocalWorkspaceError):
            finish_initialization(self.workspace, digest)
        self.assertEqual(database.read_bytes(), b'broken')
        database.write_bytes(raw)
        marker = self.workspace / INTERNAL_DIR / INITIALIZING_MARKER
        marker.unlink()
        target = self.root / 'other-marker'; target.write_text('keep')
        try:
            marker.symlink_to(target)
        except OSError:
            self.skipTest('symlink creation requires privileges on this host')
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'ERROR')
        with self.assertRaises(LocalWorkspaceError):
            finish_initialization(self.workspace, digest)
        self.assertEqual(target.read_text(), 'keep')
