"""Collector control tests; actual reference-hardware acceptance is separate."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest
import tempfile

spec=importlib.util.spec_from_file_location('bench_process',Path(__file__).parents[2]/'scripts/bench-process.py')
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)

class ProcessBenchmarkTests(unittest.TestCase):
    def test_rss_is_measured_in_bytes_and_missing_data_fails(self):
        with mock.patch('builtins.open',mock.mock_open(read_data='Name: fixture\nVmRSS: 123 kB\n')):
            self.assertEqual(collector.rss_bytes(42),123*1024)
        for data in ('VmRSS: bad kB\n','VmRSS: 42 MB\n','Name: fixture\n'):
            with mock.patch('builtins.open',mock.mock_open(read_data=data)),self.assertRaises(ValueError):collector.rss_bytes(42)
        with mock.patch('builtins.open',side_effect=OSError()),self.assertRaises(ValueError):collector.rss_bytes(42)

    def test_conditioning_is_fixed_and_does_not_wait_for_passing_memory(self):
        client=mock.Mock()
        with mock.patch.object(collector.time,'monotonic',side_effect=[0,0,1,2,2]):
            report=collector.condition(client,{'read':['/fixture']},lambda:collector.RSS_LIMIT+1,seconds=2)
        self.assertEqual(client.get.call_count,2)
        self.assertEqual(report['rss_max_bytes'],collector.RSS_LIMIT+1)
        self.assertEqual(report['fixed_seconds'],2)

    def test_start_passes_app_inputs_only_and_waits_for_guarded_database(self):
        process=mock.Mock();process.poll.return_value=None
        response=mock.MagicMock();response.__enter__.return_value=response;response.status=200;response.read.return_value=b'{"database":"reachable"}'
        environment={'SIERX_RUNTIME_DATABASE_URL':'runtime-fixture','SIERX_AUTH_DATABASE_URL':'auth-fixture',
          'SIERX_SESSION_KEY':'app-fixture','DATABASE_URL':'operator-secret',
          'SIERX_MAINTENANCE_DATABASE_URL':'operator-secret','SIERX_LIFECYCLE_KEY_FILE':'master-secret',
          'SIERX_BENCH_PASSWORD':'benchmark-secret','SIERX_LIFECYCLE_CHECKPOINT':'checkpoint',
          'SIERX_LIFECYCLE_GUARD_KEY_FILE':'verification'}
        with mock.patch.dict(os.environ,environment,clear=True),mock.patch.object(collector,'port',return_value=9001),mock.patch.object(collector.subprocess,'Popen',return_value=process) as spawn,mock.patch.object(collector.urllib.request,'urlopen',return_value=response):
            actual,origin,elapsed=collector.start(Path('/accepted/sierx'))
        self.assertIs(actual,process);self.assertEqual(origin,'http://localhost:9001');self.assertGreaterEqual(elapsed,0)
        child=spawn.call_args.kwargs['env']
        self.assertEqual(child['SIERX_RUNTIME_DATABASE_URL'],'runtime-fixture')
        self.assertFalse({'DATABASE_URL','SIERX_MAINTENANCE_DATABASE_URL','SIERX_LIFECYCLE_KEY_FILE','SIERX_BENCH_PASSWORD'} & child.keys())

    def test_process_failure_is_stopped_without_sensitive_output(self):
        process=mock.Mock();process.poll.return_value=1
        with mock.patch.object(collector.subprocess,'Popen',return_value=process),mock.patch.object(collector,'stop') as stop,self.assertRaises(ValueError):collector.start(Path('/accepted/sierx'))
        stop.assert_called_once_with(process)

    def test_run_collects_every_scenario_and_reports_failed_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'native';binary.write_bytes(b'accepted-fixture');binary.chmod(0o700)
            process=SimpleNamespace(pid=42)
            args=SimpleNamespace(binary=str(binary),starts=5,samples=500,warmups=1)
            original=collector.bench.Client
            def workload(options):
                for _ in range(options.samples*len(collector.bench.LIMITS_MS)):options.sample_observer()
                return {'target_label':'test fixture','hardware':{},'active_fixture_items':10000,'results':{}}
            with mock.patch.object(collector.sys,'platform','linux'),mock.patch.dict(os.environ,{'SIERX_BENCH_URL':'https://original.example.test'}),mock.patch.object(collector,'start',return_value=(process,'http://localhost:9001',1001)),mock.patch.object(collector,'stop') as stop,mock.patch.object(collector,'rss_bytes',return_value=collector.RSS_LIMIT+1),mock.patch.object(collector.bench,'run',side_effect=workload):
                report=collector.run(args)
                self.assertEqual(os.environ['SIERX_BENCH_URL'],'https://original.example.test')
            self.assertIs(collector.bench.Client,original)
            self.assertEqual(report['rss']['samples'],500*len(collector.bench.LIMITS_MS))
            self.assertEqual(report['cold_start']['samples'],5)
            self.assertFalse(report['rss']['within_limit']);self.assertFalse(report['cold_start']['within_limit'])
            stop.assert_called_with(process)
            self.assertNotIn('native',json.dumps(report))

    def test_missing_samples_fail_and_restore_process_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'native';binary.write_bytes(b'fixture');binary.chmod(0o700)
            args=SimpleNamespace(binary=str(binary),starts=5,samples=500,warmups=1)
            with mock.patch.object(collector.sys,'platform','linux'),mock.patch.object(collector,'start',return_value=(SimpleNamespace(pid=42),'http://localhost:9001',1)),mock.patch.object(collector,'stop') as stop,mock.patch.object(collector.bench,'run',return_value={}),self.assertRaises(ValueError):collector.run(args)
            stop.assert_called()

if __name__=='__main__':unittest.main()
