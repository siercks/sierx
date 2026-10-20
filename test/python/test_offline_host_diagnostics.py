"""Failure metadata must expose no untrusted console or environment content."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
import offline_host_diagnostics as diagnostics


class DiagnosticsTests(unittest.TestCase):
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
