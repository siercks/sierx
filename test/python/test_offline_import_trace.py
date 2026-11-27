"""Unchanged helper errors stay failures; only fixed import metadata escapes."""
import ast
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import offline_import_trace as trace
import offline_host_diagnostics as diagnostics


def packet():
    return {'kind': 'CalledProcessError', 'stage': 'load-app', 'lines': [51, 243],
            'exit_code': 125, 'categories': ['permission-denied'],
            'stderr_kind': 'text', 'stderr_size': 37, 'stderr_tail_truncated': False}


class ImportTraceTests(unittest.TestCase):
    def test_rejects_malformed_ambiguous_and_private_category_metadata(self):
        for changed in ({'kind': 'private'}, {'stage': 'load-private'}, {'lines': [True]}, {'lines': []},
                        {'exit_code': True}, {'exit_code': -129}, {'stderr_kind': []},
                        {'stderr_size': True}, {'stderr_size': -1}, {'stderr_tail_truncated': 1},
                        {'categories': ['private-credential']}, {'categories': ['permission-denied'] * 2},
                        {'stderr_kind': 'unavailable', 'stderr_size': 0}, {'stderr_size': 9000},
                        {'stderr_kind': 'bytes', 'stderr_tail_truncated': True}):
            with self.subTest(changed=changed):
                self.assertIsNone(trace.sanitize({**packet(), **changed}))

    def test_failure_pipeline_keeps_only_import_failure_without_any_private_fields(self):
        value = {**packet(), 'message': 'private-credential', 'argv': ['private-path'], 'environment': {'token': 'secret'}}
        error = RuntimeError('private original failure')
        error.fixture_exit_code = 1
        error.import_failure = value
        safe = diagnostics.sanitize_failure(diagnostics.failure_record(error, 'import'))
        self.assertEqual(safe['import_failure'], packet())
        self.assertNotIn('private', json.dumps(safe))
        for changed in ({'phase': 'rootless-database'}, {'command_exit_code': 0}):
            self.assertNotIn('import_failure', diagnostics.sanitize_failure({**safe, **changed}))

    def test_duplicate_oversized_or_broken_marker_is_never_accepted(self):
        line = (trace.MARKER + json.dumps(packet()) + '\n').encode()
        self.assertEqual(trace.stderr_failure(line), packet())
        for raw in (line + line, b'x' * 8193, (trace.MARKER + '{broken\n').encode()):
            self.assertIsNone(trace.stderr_failure(raw))

    def execute(self, root, scenario='load', observe=True, operation='import'):
        hook = root / 'trace'
        hook.mkdir(exist_ok=True)
        (hook / 'sitecustomize.py').write_bytes((ROOT / 'scripts/offline_import_trace.py').read_bytes())
        source = root / 'offline.py'
        fake = root / 'podman'
        fake.write_text("#!/bin/sh\nif [ \"$1\" = image ] || [ \"$CONTROL\" = load ]; then\n"
                        "  printf '%s\\n' 'Error: initializing source; permission denied; private-credential/private-path' >&2\n"
                        "  exit 125\nfi\nprintf '%s\\n' 'synthetic image imported'\n")
        fake.chmod(0o755)
        source.write_text('''import os,subprocess,sys
def command(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.PIPE).strip()
def inspect_image():
    command('podman','image','inspect','private-image')
def verify():
    if os.environ['CONTROL']=='guard':raise ValueError('private guard value')
def run_operation():
    verify()
    for role in ('app','caddy','postgres'):
        command('podman','load','--input','private-path')
        inspect_image()
def main():
    if os.environ['CONTROL']=='success':print('complete synthetic import');return
    run_operation()
try:main()
except (ValueError,subprocess.CalledProcessError):sys.exit('fixed original failure')
''')
        before = source.read_bytes()
        env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
               'CONTROL': scenario, 'PYTHONPATH': str(hook)}
        env.pop('SIERX_DIAGNOSTIC_IMPORT', None)
        if observe:
            env['SIERX_DIAGNOSTIC_IMPORT'] = str(source)
        result = subprocess.run([sys.executable, '-B', str(source), operation], env=env, capture_output=True, timeout=10)
        self.assertEqual(source.read_bytes(), before)
        return result

    def test_real_subprocess_failure_preserves_original_status_stdio_and_unchanged_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = self.execute(root, observe=False)
            after = self.execute(root)
            self.assertEqual(before.returncode, after.returncode)
            self.assertEqual(after.returncode, 1)
            self.assertEqual(before.stdout, after.stdout)
            clean = b'\n'.join(line for line in after.stderr.split(b'\n') if not line.startswith(trace.MARKER.encode()))
            self.assertEqual(clean, before.stderr)
            value = trace.stderr_failure(after.stderr)
            self.assertEqual(value['stage'], 'load-app')
            self.assertEqual(value['kind'], 'CalledProcessError')
            self.assertEqual(value['exit_code'], 125)
            self.assertEqual(value['categories'], ['permission-denied', 'source-initialization'])
            self.assertGreater(value['stderr_size'], 0)
            self.assertEqual(value['stderr_kind'], 'text')
            self.assertNotIn('private', json.dumps(value))

    def test_inspection_failure_reports_the_same_role_and_success_is_silent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inspect = self.execute(root, 'inspect')
            self.assertEqual(trace.stderr_failure(inspect.stderr)['stage'], 'inspect-app')
            passed = self.execute(root, 'success')
            self.assertEqual(passed.returncode, 0)
            self.assertEqual(passed.stdout, b'complete synthetic import\n')
            self.assertEqual(passed.stderr, b'')

    def test_original_guard_failure_and_nonimport_operations_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            failed = self.execute(root, 'guard')
            value = trace.stderr_failure(failed.stderr)
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(value['kind'], 'ValueError')
            self.assertEqual(value['stage'], 'verify-bundle')
            self.assertNotIn('private', json.dumps(value))
            other = self.execute(root, 'load', operation='db-up')
            self.assertEqual(other.returncode, 1)
            self.assertIsNone(trace.stderr_failure(other.stderr))
            self.assertEqual(other.stderr, b'fixed original failure\n')

    def test_stderr_observation_has_explicit_tail_bounds_and_cannot_claim_absence(self):
        source = str(Path(__file__).resolve())
        try:
            raise subprocess.CalledProcessError(125, ('podman', 'load'), stderr='private-prefix' * 900 + ' permission denied')
        except subprocess.CalledProcessError as error:
            value = trace.summarize(error, error.__traceback__, source, sys._getframe())
        self.assertTrue(value['stderr_tail_truncated'])
        self.assertGreater(value['stderr_size'], 8192)
        self.assertEqual(value['categories'], ['permission-denied'])
        self.assertNotIn('private', json.dumps(value))

    def test_diagnostic_option_only_adds_observation_to_import_and_preserves_all_arguments(self):
        tree = ast.parse((ROOT / 'scripts/offline-host-guest.py').read_text())
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'operation')
        for diagnostic, name in ((False, 'import'), (True, 'import'), (True, 'apply')):
            calls = []
            scope = {'BUNDLE': Path('/synthetic-bundle'), 'OPTIONS': {'bundle_sha256': 'a' * 64, 'observe_import_failure': diagnostic},
                     'ENV': {}, 'TRACK_INSTALLER_EXIT': False,
                     'diagnostics': SimpleNamespace(INSTALLER_OPERATIONS={'import', 'apply'}, emit_resources=lambda: None),
                     'require': lambda condition, text: self.assertTrue(condition),
                     'run': lambda *a, **k: calls.append((a, k)) or 'unchanged'}
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'guest-operation', 'exec'), scope)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(scope['operation'](name), 'unchanged')
            args, kwargs = calls[0]
            self.assertEqual(args, ('python3', '-B', Path('/synthetic-bundle/scripts/offline.py'), name))
            self.assertEqual('SIERX_DIAGNOSTIC_IMPORT' in kwargs['env'], diagnostic and name == 'import')
