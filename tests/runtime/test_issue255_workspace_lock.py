from __future__ import annotations

from contextlib import nullcontext
import errno
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade, LocalWorkspace
from plugins.local_application.workspace import LocalWorkspaceError
from plugins.local_application import profile_advancement as advancement
from plugins.local_application import workspace_lock as locking
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_profile_generation_advancement as profile


class Issue255WorkspaceLockTests(ResearchPackageAcceptanceSupport):
    _write_structured_workspace_inputs = profile.ProfileGenerationAdvancementTests._write_structured_workspace_inputs
    _normal_manifest_files = profile.ProfileGenerationAdvancementTests._normal_manifest_files
    _resolve_request = profile.ProfileGenerationAdvancementTests._resolve_request
    _resolve = profile.ProfileGenerationAdvancementTests._resolve

    def _child(self, body, *args, timeout=10):
        completed = subprocess.run([sys.executable, '-c', body, str(self.workspace), *args],
                                   cwd=profile.ROOT, capture_output=True, text=True, timeout=timeout)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        return json.loads(completed.stdout)

    def _holder(self, *, shared):
        body = '''
import sys
from pathlib import Path
from plugins.local_application.workspace_lock import workspace_lock
with workspace_lock(Path(sys.argv[1]), shared=sys.argv[2] == "shared"):
    print("READY", flush=True)
    sys.stdin.read()
'''
        process = subprocess.Popen([sys.executable, '-c', body, str(self.workspace), 'shared' if shared else 'exclusive'],
                                   cwd=profile.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        self.assertEqual(ready.get(timeout=10).strip(), 'READY')
        return process

    def _advance_payload(self):
        request, output, _ = self._resolve()
        return {'project_config_file': str(output / 'project-config.json'),
                'effective_profile_set_file': str(output / 'effective-profile-set.json'),
                'profile_manifest_files': request['profile_manifest_files'], 'origin': 'issue255'}

    def test_normal_opens_and_public_status_coexist_across_processes(self):
        with LocalWorkspace.open(self.workspace) as opened:
            result = self._child('''
import json, sys
from plugins.local_application import LocalApplicationFacade
with LocalApplicationFacade.open_workspace(sys.argv[1]) as facade:
    print(json.dumps(facade.status()))
''')
            self.assertEqual(result['status'], 'OK')
            self.assertEqual(opened.binding['effective_profile_set']['digest'],
                             opened.application.state_repository.load_state_view(
                                 opened.project_id, opened.application.state_repository.load_active_lineage_ref(opened.project_id)
                             ).effective_profile_set_digest)
            # A separate process can hold another shared lifetime too.
            process = self._holder(shared=True)
            process.communicate(input='', timeout=5)
            self.assertEqual(process.returncode, 0)

    def test_exclusive_rebind_is_bounded_busy_until_all_shared_handles_close(self):
        payload = self._advance_payload()
        outer, inner = LocalWorkspace.open(self.workspace), LocalWorkspace.open(self.workspace)
        self.addCleanup(outer.close)
        self.addCleanup(inner.close)
        original = dict(inner.binding)
        for closer in [lambda: None, outer.close]:
            closer()
            result = self._child('''
import json, sys, time
from pathlib import Path
from plugins.local_application.workspace_lock import workspace_lock
from plugins.local_application.workspace import LocalWorkspaceError
start = time.monotonic()
try:
    with workspace_lock(Path(sys.argv[1]), timeout=0.15):
        raise AssertionError("exclusive acquisition bypassed a live Workspace")
except LocalWorkspaceError as exc:
    print(json.dumps({"code": exc.code, "elapsed": time.monotonic()-start}))
''')
            self.assertEqual(result['code'], 'WORKSPACE-LOCK-BUSY-001')
            self.assertLess(result['elapsed'], 1.5)
            self.assertEqual(inner.binding, original)
        # Same-thread shared-to-exclusive upgrades are never hidden reentrancy.
        with self.assertRaises(LocalWorkspaceError) as rejected:
            advancement.advance_profile_generation(self.workspace, payload)
        self.assertEqual(rejected.exception.code, 'WORKSPACE-LOCK-BUSY-001')
        inner.close()
        result = advancement.advance_profile_generation(self.workspace, payload)
        self.assertEqual(result['result'], 'ADVANCED')
        with LocalWorkspace.open(self.workspace) as reopened:
            self.assertNotEqual(reopened.binding['effective_profile_set']['digest'], original['effective_profile_set']['digest'])

    def test_exclusive_holder_blocks_shared_with_timeout_and_crash_releases_lock(self):
        process = self._holder(shared=False)
        with self.assertRaises(LocalWorkspaceError) as rejected:
            with locking.workspace_lock(self.workspace, shared=True, timeout=0.1):
                self.fail('reader bypassed exclusive holder')
        self.assertEqual(rejected.exception.code, 'WORKSPACE-LOCK-BUSY-001')
        process.kill()
        process.communicate(timeout=5)
        with LocalWorkspace.open(self.workspace):
            pass
        # Shared holder death also releases the OS resource, without deleting a file.
        process = self._holder(shared=True)
        path = self.workspace / '.research-loom' / locking.ADVANCEMENT_LOCK
        before = path.stat().st_ino
        process.kill()
        process.communicate(timeout=5)
        with locking.workspace_lock(self.workspace, timeout=1):
            self.assertEqual(path.stat().st_ino, before)

    def test_io_and_permission_errors_are_immediate_not_contention(self):
        for error in [PermissionError(errno.EACCES, 'denied'), OSError(errno.EIO, 'I/O'),
                      OSError(errno.ENOSYS, 'locking unsupported')]:
            handle = io.BytesIO()
            start = time.monotonic()
            with patch.object(Path, 'open', return_value=handle), patch.object(locking, '_try_lock', side_effect=error) as attempt:
                with self.assertRaises(LocalWorkspaceError) as rejected:
                    with locking.workspace_lock(self.workspace):
                        self.fail('I/O failure bypassed lock')
            self.assertEqual(rejected.exception.code, 'WORKSPACE-LOCK-IO-001')
            self.assertEqual(attempt.call_count, 1)
            self.assertTrue(handle.closed)
            self.assertLess(time.monotonic() - start, 1)
        with patch.object(Path, 'open', side_effect=PermissionError('denied')):
            with self.assertRaises(LocalWorkspaceError) as rejected:
                with locking.workspace_lock(self.workspace):
                    self.fail('open failure bypassed lock')
        self.assertEqual(rejected.exception.code, 'WORKSPACE-LOCK-IO-001')
        # Classification uses Win32 status, not CRT errno aliases for EACCES.
        with patch.object(locking.os, 'name', 'nt'):
            for winerror, busy in [(33, True), (5, False), (1, False), (50, False)]:
                error = OSError(errno.EACCES, 'windows test')
                error.winerror = winerror
                self.assertIs(locking._contention(error), busy)

    def test_pending_recovery_and_degraded_operations_keep_their_boundaries(self):
        # A recoverable interrupted Profile operation still restores exact old
        # documents before a normal shared open, never while another reader is live.
        internal = self.workspace / '.research-loom'
        binding = json.loads((internal / 'workspace-binding.json').read_text())
        config = (internal / 'project-config.json').read_text()
        eps = (internal / 'effective-profile-set.json').read_text()
        marker = {'schema_version': '0.1.0', 'old_binding': binding, 'new_binding': binding,
                  'old_project_config': json.loads(config), 'old_effective_profile_set': json.loads(eps),
                  'old_project_config_text': config, 'old_effective_profile_set_text': eps,
                  'created_history_paths': [], 'event_locator': None}
        marker_path = internal / advancement.PENDING_MARKER
        with LocalWorkspace.open(self.workspace):
            marker_path.write_text(json.dumps(marker))
            with self.assertRaises(LocalWorkspaceError) as rejected:
                advancement.recover_incomplete_profile_advancement(self.workspace)
            self.assertEqual(rejected.exception.code, 'WORKSPACE-LOCK-BUSY-001')
            self.assertTrue(marker_path.exists())
        with LocalWorkspace.open(self.workspace):
            self.assertFalse(marker_path.exists())
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            source = self.workspace / 'theme.txt'
            source.write_text('retained input')
            snapshot = facade.status()['snapshot']
            facade.register_project_input({'file': str(source), 'role': 'theme',
                'expected_snapshot_id': snapshot['snapshot_id'],
                'expected_snapshot_digest': snapshot['content_digest']})
        # Register then lose only an optional child. Shared lifetimes must not
        # turn this into canonical failure or recreate an empty child.
        child = internal / 'project-inputs'
        saved = self.root / 'retained-inputs'
        child.rename(saved)
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            self.assertEqual(facade.status()['status'], 'DEGRADED')
            result = self._child('''
import json, sys
from plugins.local_application import LocalApplicationFacade
with LocalApplicationFacade.open_workspace(sys.argv[1]) as facade:
    print(json.dumps(facade.status()))
''')
            self.assertEqual(result['status'], 'DEGRADED')
        self.assertFalse(child.exists())
        saved.rename(child)
        # The supported whole-Parent backup remains a stopped copy, not a lease
        # token or hot-copy feature. Verify only after all application handles close.
        backup = self.root / 'whole-parent-backup'
        backup.mkdir()
        shutil.copytree(internal, backup / '.research-loom')
        self.assertEqual(LocalWorkspace.doctor(backup)['status'], 'OK')

    def test_ablation_removing_shared_lifetime_allows_stale_open_generation(self):
        payload = self._advance_payload()
        # Only remove the normal open's lock, leaving real advancement locking.
        with patch.object(advancement, '_workspace_advancement_lock', return_value=nullcontext()):
            opened = LocalWorkspace.open(self.workspace)
        try:
            old = opened.binding['effective_profile_set']['digest']
            self.assertEqual(advancement.advance_profile_generation(self.workspace, payload)['result'], 'ADVANCED')
            current = opened.application.state_repository.load_state_view(
                opened.project_id, opened.application.state_repository.load_active_lineage_ref(opened.project_id))
            self.assertNotEqual(old, current.effective_profile_set_digest)
            self.assertEqual(opened.binding['effective_profile_set']['digest'], old)
        finally:
            opened.close()
