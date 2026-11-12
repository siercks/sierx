"""Failure metadata must expose no untrusted console or environment content."""
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
import offline_host_diagnostics as diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_service_failure_binds_kernel_exit_and_operation_to_the_two_main_tasks(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            instance = home / 'tracefs'
            stats = instance / 'per_cpu' / 'cpu0'
            stats.mkdir(parents=True)
            (stats / 'stats').write_text('overrun: 0\ncommit overrun: 0\ndropped events: 0\n')
            (home / 'progress.json').write_text('{"phase":"two-release-stress-1"}')
            events = [
                (40, 'tracing_mark_write: sierx-tracer-start'),
                (40, 'tracing_mark_write: sierx-tracer-errors-ready'),
                (42, 'tracing_mark_write: sierx-installer-start'),
                (42, 'tracing_mark_write: sierx-phase two-release-stress-1'),
                (42, 'tracing_mark_write: sierx-operation start apply'),
                (45, 'sys_exit_group(error_code: 49)'),
                (45, 'sys_ptrace -> 0xfffffffffffffffb'),
                (40, 'sys_ptrace -> 0xfffffffffffffffb'),
                (40, 'sys_exit_group(error_code: 1)'),
                (42, 'sched_process_exit: comm=private pid=42 prio=120'),
                (40, 'sched_process_exit: comm=private pid=40 prio=120'),
            ]
            trace = (instance / 'trace')
            count = len(events)
            trace.write_text(f'# entries-in-buffer/entries-written: {count}/{count}   #P:1\n' +
                             ''.join(f' task-{pid} [000] ..... 101.{i * 1000:06d}: {event}\n'
                                     for i, (pid, event) in enumerate(events)))
            journal = __import__('subprocess').CompletedProcess([], 0, stdout=b'')
            with patch.object(diagnostics.subprocess, 'run', return_value=journal), \
                    patch.object(diagnostics.os, 'sync'), contextlib.redirect_stdout(io.StringIO()) as console:
                result = diagnostics.checkpoint_service_failure(home, home,
                    {'SERVICE_RESULT': 'exit-code', 'EXIT_CODE': 'exited', 'EXIT_STATUS': '1'}, instance)
            self.assertEqual(result['kernel_exit'], {
                'installer': {'task_exited': True},
                'tracer': {'task_exited': True, 'requested_exit_code': 1},
            })
            self.assertEqual(result['kernel_exit_capture'], 'observed')
            self.assertEqual(result['tracer_syscall_errors'], [{'call': 'ptrace', 'errno': 5, 'age_ms': 1}])
            self.assertEqual(result['last_operation'], 'start apply')
            self.assertEqual(result['service_exit'], {
                'service_result': 'exit-code', 'exit_kind': 'exited', 'exit_status': 1,
            })
            self.assertNotIn('private', console.getvalue() + json.dumps(result))
            (stats / 'stats').write_text('overrun: 0\ncommit overrun: 0\ndropped events: 1\n')
            self.assertEqual(diagnostics.read_installer_exit_trace(instance),
                             {'kernel_exit_capture': 'lost-events'})
            incomplete = trace.read_text().replace(f'{count}/{count}', f'{count}/{count+1}').splitlines()
            self.assertEqual(diagnostics.installer_exit_events(incomplete), {})
            reused = trace.read_text().replace(f'{count}/{count}', f'{count+1}/{count+1}') + (
                ' task-42 [000] ..... 101.011000: sched_process_exit: comm=other pid=42 prio=120\n')
            self.assertEqual(diagnostics.installer_exit_events(reused.splitlines()), {})

    def test_caught_rollback_error_retains_public_locations_only(self):
        suite_dir = Path(diagnostics.__file__).parent
        outside = compile("raise ValueError('private fixture contents')\n",
                          '/private/offline-host-scenarios.py', 'exec')
        scenario = compile('\nexec(outside)\n', str(suite_dir / 'offline-host-scenarios.py'), 'exec')
        try:
            exec(scenario, {'outside': outside})
        except ValueError as error:
            failure = diagnostics.failure_record(error, 'failed-health-rollback')
        self.assertEqual(failure, {
            'result': 'failed',
            'phase': 'failed-health-rollback',
            'failure_type': 'ValueError',
            'guest_frames': [{'file': 'offline-host-scenarios.py', 'line': 2}],
        })

    def test_empty_browser_report_retains_only_fixed_service_status(self):
        error = json.JSONDecodeError('No report', '', 0)
        status = {'service_result': 'success', 'exit_kind': 'killed', 'exit_status': 'TERM'}
        error.browser_service_exit = status
        failure = diagnostics.failure_record(error, 'delivered-browser-workflows')
        self.assertEqual(failure['result'], 'failed')
        self.assertEqual(failure['json_input'], 'empty')
        self.assertEqual(failure['browser_service_exit'], status)
        self.assertNotIn('browser_service_exit', diagnostics.failure_record(error, 'two-approved-releases'))
        for invalid in ({**status, 'private': 'credential'}, {**status, 'exit_status': 'private'},
                        {**status, 'exit_status': True}, {**status, 'exit_kind': []}):
            error.browser_service_exit = invalid
            failure = diagnostics.failure_record(error, 'delivered-browser-workflows')
            self.assertNotIn('browser_service_exit', failure)
            self.assertNotIn('private', json.dumps(failure))

    def test_service_checkpoint_distinguishes_installer_exit_from_child_and_tracer_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'progress.json').write_text('{"phase":"two-release-stress-2"}')
            trace = directory / 'installer.trace'
            prefix = ('42 1700000000.000001 execve("/usr/sbin/sierx-observed-installer", '
                      '["private argument"], 0x1234) = 0\n'
                      '421<child> 1700000001.000000 +++ exited with 7 +++\n')
            journal = __import__('subprocess').CompletedProcess([], 0, stdout=b'')
            for terminal, expected in (
                ('42<python3> 1700000002.000000 +++ exited with 73 +++\n', {'kind':'exited','status':73}),
                ('42<python3> 1700000002.000000 +++ killed by SIGKILL +++\n', {'kind':'killed','status':'KILL'}),
                ('42<python3> 1700000002.000000 +++ exited with 999 +++\n', None),
                ('', None),
            ):
                with self.subTest(expected=expected):
                    trace.write_text(prefix + terminal)
                    with patch.object(diagnostics.subprocess, 'run', return_value=journal), \
                            patch.object(diagnostics.os, 'sync'), contextlib.redirect_stdout(io.StringIO()) as console:
                        result = diagnostics.checkpoint_service_failure(directory, directory,
                            {'SERVICE_RESULT':'exit-code','EXIT_CODE':'exited','EXIT_STATUS':'1'})
                    self.assertEqual(result['service_exit_code'], 1)
                    self.assertEqual(result['phase'], 'two-release-stress-2')
                    self.assertEqual(result.get('tracee_exit'), expected)
                    self.assertNotIn('private', console.getvalue())

    def test_direct_root_tracee_stderr_survives_empty_journal_without_disclosing_messages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);home=root/'home';directory=root/'observer'
            home.mkdir();directory.mkdir()
            (home/'progress.json').write_text('{"phase":"two-approved-releases"}')
            direct=directory/'installer-guest.stderr'
            direct.write_text('Traceback (most recent call last):\n'
                '  File "/opt/acceptance/tests/offline-host-guest.py", line 88, in private_function\n'
                '    private credential\nRuntimeError: private credential\n')
            direct.chmod(0o600)
            journal=__import__('subprocess').CompletedProcess([],0,stdout=b'')
            with patch.object(diagnostics.subprocess,'run',return_value=journal),patch.object(diagnostics.os,'sync'), \
                    contextlib.redirect_stdout(io.StringIO()) as console:
                result=diagnostics.checkpoint_service_failure(home,directory,
                    {'SERVICE_RESULT':'exit-code','EXIT_CODE':'exited','EXIT_STATUS':'1'})
            self.assertEqual(result['failure_type'],'RuntimeError')
            self.assertEqual(result['guest_frames'],[{'file':'offline-host-guest.py','line':88}])
            self.assertEqual(result['tracee_stderr_bytes'],direct.stat().st_size)
            self.assertEqual(direct.stat().st_mode&0o777,0o600)
            self.assertFalse((home/'result.json').exists())
            self.assertNotIn('private',console.getvalue()+json.dumps(result))
            for value in (-1,True,2**32,'private'):
                self.assertNotIn('tracee_stderr_bytes',diagnostics.sanitize_failure(
                    {'result':'failed','tracee_stderr_bytes':value}))

    def test_root_service_checkpoint_survives_missing_guest_reports_and_failed_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);home=root/'home';directory=root/'root-observer'
            home.mkdir();directory.mkdir()
            (home/'progress.json').write_text(json.dumps({'phase':'failed-health-rollback','private':'credential'}))
            (directory/'installer.stderr').write_text(
                'strace: Process 42 attached\nstrace: ptrace(PTRACE_SYSCALL, private): Input/output error\n')
            with patch.object(diagnostics.subprocess,'run',side_effect=PermissionError('private journal')), \
                    patch.object(diagnostics.os,'sync'),contextlib.redirect_stdout(io.StringIO()) as console:
                result=diagnostics.checkpoint_service_failure(home,directory,
                    {'SERVICE_RESULT':'exit-code','EXIT_CODE':'exited','EXIT_STATUS':'1','private':'credential'})
            self.assertEqual(result['phase'],'failed-health-rollback')
            self.assertEqual(result['failure_type'],'ServiceExit')
            self.assertEqual(result['service_exit_code'],1)
            self.assertEqual(result['observer_errors'],{'installer':['io-error','ptrace']})
            self.assertEqual(json.loads((directory/'service-failure.json').read_text()),result)
            self.assertEqual((directory/'service-failure.json').stat().st_mode&0o077,0)
            self.assertFalse((home/'result.json').exists())
            self.assertFalse((home/'failure.json').exists())
            self.assertNotIn('private',console.getvalue()+json.dumps(result))

    def test_root_journal_retains_only_known_source_locations_and_exception_classes(self):
        journal=('Traceback (most recent call last):\n'
            '  File "/opt/acceptance/tests/offline-host-guest.py", line 344, in private_function\n'
            '    private argument and credential\n'
            '  File "/private/credential.py", line 1, in private_function\n'
            'BrokenPipeError: private traceback message\n')
        expected={'failure_type':'BrokenPipeError','guest_frames':[{'file':'offline-host-guest.py','line':344}]}
        self.assertEqual(diagnostics.journal_failure(journal),expected)
        planted={'result':'failed',**expected,'observer_errors':{'installer':['ptrace','private',[],12],
            'private':['ptrace']},'private':'credential'}
        planted['guest_frames'] += [{'file':'private','line':2}, {'file':[],'line':True},
                                   {'file':'offline.py','line':100001}]
        result=diagnostics.sanitize_failure(planted)
        self.assertEqual(result['guest_frames'],expected['guest_frames'][:1])
        self.assertEqual(result['observer_errors'],{'installer':['ptrace']})
        self.assertNotIn('private',json.dumps(result))

    def test_successful_service_exit_and_unknown_journal_cannot_make_acceptance(self):
        with patch.object(diagnostics.subprocess,'run') as journal:
            self.assertIsNone(diagnostics.checkpoint_service_failure('/unused','/unused',
                {'SERVICE_RESULT':'success','EXIT_CODE':'exited','EXIT_STATUS':'0'}))
            journal.assert_not_called()
        self.assertEqual(diagnostics.journal_failure('PrivateException: credential\n'),{})
        self.assertIsNone(diagnostics.latest('SIERX_FAILURE: {"result":"passed"}', 'SIERX_FAILURE'))
        value=diagnostics.latest('SIERX_FAILURE: '+json.dumps({'result':'failed',
            'phase':'failed-health-rollback','failure_type':'ServiceExit','private':'credential'}),'SIERX_FAILURE')
        self.assertNotIn('private',json.dumps(value))
        self.assertEqual(value['result'],'failed')

    def test_checkpoint_is_failed_only_and_sanitized_before_any_console_or_disk_output(self):
        with tempfile.TemporaryDirectory() as temporary,contextlib.redirect_stdout(io.StringIO()) as console:
            home=Path(temporary)
            with self.assertRaises(ValueError):diagnostics.checkpoint_failure(home,{'result':'passed'})
            self.assertFalse((home/'failure.json').exists())
            value=diagnostics.checkpoint_failure(home,{'result':'failed','phase':'acquisition-inspect',
                'failure_type':'RuntimeError','private':'credential','guest_command':'private argument'})
            self.assertEqual(json.loads((home/'failure.json').read_text()),value)
            self.assertNotIn('private',console.getvalue()+(home/'failure.json').read_text())
            self.assertFalse((home/'result.json').exists())
            self.assertFalse((home/'failure.pending.json').exists())

    def test_json_decode_failure_keeps_fixed_type_and_position_without_private_output(self):
        for document,kind in (('', 'empty'), ('private-credential', 'other'), ('{private-credential', 'object')):
            error=json.JSONDecodeError('private exception message',document,0)
            value=diagnostics.failure_record(error,'delivered-browser-workflows')
            self.assertEqual(value['result'],'failed')
            self.assertEqual(value['failure_type'],'JSONDecodeError')
            self.assertEqual(value['json_input'],kind)
            self.assertEqual(value['json_chars'],len(document))
            self.assertEqual(value['json_position'],0)
            self.assertNotIn('private',json.dumps(value))

    def test_failure_metadata_rejects_private_types_phases_and_unbounded_values(self):
        value=diagnostics.sanitize_failure({'result':'failed','phase':'private-credential',
            'failure_type':['private'],'command_exit_code':True,'json_input':'private',
            'json_chars':10**50,'json_position':-1,'json_line':'private','json_column':True,
            'private':'credential'})
        self.assertEqual(value,{'result':'failed','phase':'unknown','failure_type':'unknown'})
        error=RuntimeError('private fixture command')
        error.fixture_exit_code=-9
        self.assertEqual(diagnostics.failure_record(error,'delivered-browser-workflows')['command_exit_code'],-9)
        with self.assertRaises(ValueError):diagnostics.sanitize_failure({'result':'passed'})

    def test_reads_only_numeric_resource_metadata_and_marks_missing_values_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'proc').mkdir()
            (root/'proc/meminfo').write_text('Secret: private\nMemAvailable: 4096 kB\n')
            (root/'proc/vmstat').write_text('other_field 999\noom_kill 2\n')
            trace = root/'var/log/sierx-network'
            trace.mkdir(parents=True)
            (trace/'manager.trace').write_text('private synthetic credential')
            value = diagnostics.resources(root)
            self.assertEqual(value['memory_available_bytes'], 4096*1024)
            self.assertEqual(value['oom_kills'], 2)
            self.assertEqual(value['manager_trace_bytes'], (trace/'manager.trace').stat().st_size)
            self.assertIsNone(value['installer_trace_bytes'])
            self.assertGreater(value['disk_available_bytes'], 0)
            self.assertNotIn('private', json.dumps(value))
            (root/'proc/meminfo').write_text('MemAvailable: private\n')
            self.assertIsNone(diagnostics.resources(root)['memory_available_bytes'])

    def test_guest_service_exit_does_not_emit_arbitrary_environment_values(self):
        value = diagnostics.service_exit({'SERVICE_RESULT':'oom-kill', 'EXIT_CODE':'killed',
                                          'EXIT_STATUS':'KILL', 'DATABASE_URL':'private'})
        self.assertEqual(value, {'service_result':'oom-kill','exit_kind':'killed','exit_status':'KILL'})
        value = diagnostics.service_exit({'SERVICE_RESULT':'private', 'EXIT_CODE':'private', 'EXIT_STATUS':'private'})
        self.assertEqual(set(value.values()), {'unknown'})
        self.assertEqual(diagnostics.service_exit({'EXIT_STATUS':'17'})['exit_status'], 17)

    def test_console_only_accepts_complete_allowlisted_records(self):
        valid = dict.fromkeys(diagnostics.RESOURCE_KEYS, 123)
        marker = 'SIERX_RESOURCES: '
        console = marker+json.dumps(valid)+'\n'
        for invalid in ({**valid,'private':'credential'}, {**valid,'oom_kills':True},
                        {**valid,'oom_kills':-1}, {**valid,'oom_kills':'credential'}, {}, []):
            with self.subTest(value=invalid):
                self.assertEqual(diagnostics.latest(console+marker+json.dumps(invalid), 'SIERX_RESOURCES'), valid)
        self.assertIsNone(diagnostics.latest(marker+'{broken private}', 'SIERX_RESOURCES'))
        self.assertIsNone(diagnostics.latest('SIERX_GUEST_EXIT: '+json.dumps({'service_result':'private'}), 'SIERX_GUEST_EXIT'))
        for key in ('service_result', 'exit_kind', 'exit_status'):
            invalid = {'service_result':'signal','exit_kind':'killed','exit_status':'KILL',key:[]}
            self.assertIsNone(diagnostics.latest('SIERX_GUEST_EXIT: '+json.dumps(invalid), 'SIERX_GUEST_EXIT'))

    def test_incomplete_result_stays_diagnostic_and_redacts_raw_error_content(self):
        resource = dict.fromkeys(diagnostics.RESOURCE_KEYS, None)
        guest = diagnostics.service_exit({'SERVICE_RESULT':'signal','EXIT_CODE':'killed','EXIT_STATUS':'KILL'})
        console = ('SIERX_RESOURCES: '+json.dumps(resource)+'\nSIERX_GUEST_EXIT: '+json.dumps(guest)
                   +'\nOut of memory: Killed process private\nNo space left on device: private')
        value = diagnostics.stopped(-9, console, 'Assertion private failed; secret private')
        self.assertEqual(value['qemu_exit_code'], -9)
        self.assertEqual(value['guest_exit'], guest)
        self.assertTrue(value['oom_message_observed'])
        self.assertTrue(value['storage_error_observed'])
        self.assertTrue(value['emulator_assertion_observed'])
        self.assertNotIn('private', json.dumps(value))
        self.assertNotIn('result', value)
        self.assertIsNone(diagnostics.stopped(None, 'private', 'private')['guest_exit'])


if __name__ == '__main__':
    unittest.main()
